"""业务逻辑层：所有 API 的具体实现。

一致性约定（与需求一一对应）：
- 归属：所有私人查询都带 user_id 条件；跨账号访问返回 404，不泄露数据是否存在。
- 等级：心情等级 1-5 只认 db.MOOD_LEVELS 这一份定义，校验走 validate.mood_level。
- 情绪记录同时进入「本周曲线」（week_summary）和「按日筛选」（list_moods_by_date），
  两者读的是同一张 moods 表，结论天然一致。
- 测评提交即写入 assessment_results，个人报告直接读该表。
"""
import json
import sqlite3
from datetime import date, datetime, timedelta

from . import db, security, validate
from .validate import AppError

# 登录：按 IP+账号 限流，防针对单个账号的暴力破解，且不因共享 IP 误伤他人
login_limiter = security.RateLimiter(max_attempts=10, window_seconds=300)
# 注册：按 IP+用户名 防针对性探测，按 IP 总量防批量注册
register_limiter = security.RateLimiter(max_attempts=10, window_seconds=300)
register_ip_limiter = security.RateLimiter(max_attempts=30, window_seconds=300)


# ---------------------------------------------------------------- 工具

def _user_public(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
        "displayName": row["display_name"],
        "bio": row["bio"],
        "avatarEmoji": row["avatar_emoji"],
        "createdAt": row["created_at"],
    }


def _mood_public(row):
    return {
        "id": row["id"],
        "level": row["level"],
        "note": row["note"],
        "date": row["record_date"],
        "createdAt": row["created_at"],
    }


def _diary_public(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "moodLevel": row["mood_level"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _create_session(user_id):
    token = security.new_session_token()
    db.get().execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, security.session_expiry()))
    db.get().commit()
    return token


def user_by_token(token):
    """根据会话令牌取用户；无效或过期返回 None。"""
    if not token:
        return None
    row = db.get().execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id"
        " WHERE s.token = ? AND s.expires_at > datetime('now', 'localtime')",
        (token,)).fetchone()
    return row


def require_user(token):
    user = user_by_token(token)
    if user is None:
        raise AppError(401, "请先登录")
    return user


def require_admin(user):
    if user["role"] != "admin":
        raise AppError(403, "只有管理员可以创建测评")


# ---------------------------------------------------------------- 认证

def register(body, ip):
    if not isinstance(body, dict):
        raise AppError(400, "请求格式不正确")
    username = validate.username(body.get("username"))
    email = validate.email(body.get("email"))
    password = validate.password(body.get("password"))
    display = body.get("displayName")
    display = validate.display_name(display) if display else username

    if not register_limiter.allow("register:{}:{}".format(ip, username.lower())):
        raise AppError(429, "该用户名的注册尝试过于频繁，请稍后再试")
    if not register_ip_limiter.allow("register:" + ip):
        raise AppError(429, "注册请求过于频繁，请稍后再试")

    conn = db.get()
    # 快速预检（覆盖常见的顺序重复场景）；并发下的唯一性由数据库
    # UNIQUE 约束（COLLATE NOCASE）最终保证，见下方 IntegrityError 处理。
    exists = conn.execute(
        "SELECT username, email FROM users WHERE username = ? OR email = ?",
        (username, email)).fetchone()
    if exists is not None:
        if exists["username"].lower() == username.lower():
            raise AppError(409, "该用户名已被使用")
        raise AppError(409, "该邮箱已被注册")

    # 先算哈希（耗时约 0.1-0.3s）再开事务，把写锁持有时间压到最短，
    # 降低并发注册时相互等待 / 超时的概率。
    password_hash = security.hash_password(password)
    token = security.new_session_token()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, email, password_hash, display_name)"
            " VALUES (?, ?, ?, ?)",
            (username, email, password_hash, display))
        user_id = cur.lastrowid
        # 账号与初始会话在同一事务提交：要么都成功，要么都不存在，不留半成品
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, security.session_expiry()))
        conn.commit()
    except sqlite3.IntegrityError:
        # 并发注册撞了唯一约束：整体回滚（不留半成品），再查明冲突方，
        # 给失败请求一个明确的 409 而不是通用 500。
        conn.rollback()
        clash = conn.execute(
            "SELECT username, email FROM users WHERE username = ? OR email = ?",
            (username, email)).fetchone()
        if clash is not None and clash["username"].lower() == username.lower():
            raise AppError(409, "该用户名已被使用")
        if clash is not None:
            raise AppError(409, "该邮箱已被注册")
        raise AppError(409, "该用户名或邮箱已被注册")

    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return 201, {"user": _user_public(user), "token": token}


def login(body, ip):
    if not isinstance(body, dict):
        raise AppError(400, "请求格式不正确")
    username = validate.username(body.get("username"))
    if not login_limiter.allow("login:{}:{}".format(ip, username.lower())):
        raise AppError(429, "尝试次数过多，请 5 分钟后再试")
    password = body.get("password")
    if not isinstance(password, str) or not password:
        raise AppError(400, "请输入密码")

    user = db.get().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    # 用户不存在时也执行一次校验，避免时间侧信道泄露账号是否存在
    stored = user["password_hash"] if user else security.hash_password("placeholder")
    if not security.verify_password(password, stored) or user is None:
        raise AppError(401, "用户名或密码不正确")
    return 200, {"user": _user_public(user), "token": _create_session(user["id"])}


def logout(token):
    if token:
        conn = db.get()
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    return 200, {"ok": True}


def me(user):
    return 200, {"user": _user_public(user)}


# ---------------------------------------------------------------- 个人资料

def get_profile(user):
    conn = db.get()
    uid = user["id"]
    mood_count = conn.execute("SELECT COUNT(*) c FROM moods WHERE user_id = ?", (uid,)).fetchone()["c"]
    diary_count = conn.execute("SELECT COUNT(*) c FROM diaries WHERE user_id = ?", (uid,)).fetchone()["c"]
    report_count = conn.execute("SELECT COUNT(*) c FROM assessment_results WHERE user_id = ?", (uid,)).fetchone()["c"]
    active_days = conn.execute(
        "SELECT COUNT(DISTINCT record_date) c FROM moods WHERE user_id = ?", (uid,)).fetchone()["c"]
    return 200, {
        "user": _user_public(user),
        "stats": {
            "moodCount": mood_count,
            "diaryCount": diary_count,
            "reportCount": report_count,
            "activeDays": active_days,
        },
    }


def update_profile(user, body):
    if not isinstance(body, dict):
        raise AppError(400, "请求格式不正确")
    display = validate.display_name(body.get("displayName"))
    bio = validate.bio(body.get("bio"))
    avatar = validate.avatar_emoji(body.get("avatarEmoji"))
    conn = db.get()
    conn.execute(
        "UPDATE users SET display_name = ?, bio = ?, avatar_emoji = ? WHERE id = ?",
        (display, bio, avatar, user["id"]))
    conn.commit()
    fresh = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return 200, {"user": _user_public(fresh)}


# ---------------------------------------------------------------- 情绪记录

def create_mood(user, body):
    if not isinstance(body, dict):
        raise AppError(400, "请求格式不正确")
    level = validate.mood_level(body.get("level"))
    note = validate.note(body.get("note"))
    record_date = validate.record_date(body.get("date"))
    conn = db.get()
    cur = conn.execute(
        "INSERT INTO moods (user_id, level, note, record_date) VALUES (?, ?, ?, ?)",
        (user["id"], level, note, record_date))
    conn.commit()
    row = conn.execute("SELECT * FROM moods WHERE id = ?", (cur.lastrowid,)).fetchone()
    return 201, {"mood": _mood_public(row)}


def list_moods_by_date(user, date_str):
    """按日筛选：与本周曲线读同一张 moods 表。"""
    day = validate.parse_date_param(date_str)
    rows = db.get().execute(
        "SELECT * FROM moods WHERE user_id = ? AND record_date = ? ORDER BY created_at DESC",
        (user["id"], day)).fetchall()
    return 200, {"date": day, "moods": [_mood_public(r) for r in rows]}


def week_summary(user):
    """本周曲线：最近 7 天（含今天）的每日平均值，数据来自同一张 moods 表。"""
    today = date.today()
    start = today - timedelta(days=6)
    rows = db.get().execute(
        "SELECT record_date, level FROM moods WHERE user_id = ? AND record_date BETWEEN ? AND ?",
        (user["id"], start.isoformat(), today.isoformat())).fetchall()
    by_day = {}
    for r in rows:
        by_day.setdefault(r["record_date"], []).append(r["level"])
    days = []
    for i in range(7):
        d = (start + timedelta(days=i)).isoformat()
        levels = by_day.get(d, [])
        days.append({
            "date": d,
            "count": len(levels),
            "avg": round(sum(levels) / len(levels), 1) if levels else None,
        })
    recorded = [d["avg"] for d in days if d["avg"] is not None]
    return 200, {
        "days": days,
        "weekAvg": round(sum(recorded) / len(recorded), 1) if recorded else None,
    }


def delete_mood(user, mood_id):
    mood_id = validate.parse_id(mood_id)
    conn = db.get()
    row = conn.execute(
        "SELECT id FROM moods WHERE id = ? AND user_id = ?", (mood_id, user["id"])).fetchone()
    if row is None:
        raise AppError(404, "这条情绪记录不存在或已被删除")
    conn.execute("DELETE FROM moods WHERE id = ? AND user_id = ?", (mood_id, user["id"]))
    conn.commit()
    return 200, {"ok": True}


def garden(user):
    """心情花园：最近 30 天的记录开成花，数据同样来自 moods 表。"""
    uid = user["id"]
    conn = db.get()
    start = (date.today() - timedelta(days=29)).isoformat()
    rows = conn.execute(
        "SELECT * FROM moods WHERE user_id = ? AND record_date >= ?"
        " ORDER BY record_date DESC, created_at DESC LIMIT 200",
        (uid, start)).fetchall()
    total = conn.execute("SELECT COUNT(*) c FROM moods WHERE user_id = ?", (uid,)).fetchone()["c"]
    distinct_days = [r["record_date"] for r in conn.execute(
        "SELECT DISTINCT record_date FROM moods WHERE user_id = ? ORDER BY record_date DESC",
        (uid,)).fetchall()]

    streak = 0
    if distinct_days:
        cursor = date.today()
        if distinct_days[0] != cursor.isoformat():
            cursor -= timedelta(days=1)  # 今天还没记，从昨天开始算连续
        day_set = set(distinct_days)
        while cursor.isoformat() in day_set:
            streak += 1
            cursor -= timedelta(days=1)

    flowers = []
    for r in rows:
        info = db.MOOD_LEVELS[r["level"]]
        flowers.append({
            "id": r["id"], "level": r["level"], "flower": info["flower"],
            "label": info["label"], "note": r["note"], "date": r["record_date"],
        })
    return 200, {
        "flowers": flowers,
        "stats": {"total": total, "streak": streak, "periodDays": 30},
    }


# ---------------------------------------------------------------- 日记本

def create_diary(user, body):
    if not isinstance(body, dict):
        raise AppError(400, "请求格式不正确")
    title = validate.diary_title(body.get("title"))
    content = validate.diary_content(body.get("content"))
    mood_level = validate.mood_level(body.get("moodLevel"))
    conn = db.get()
    cur = conn.execute(
        "INSERT INTO diaries (user_id, title, content, mood_level) VALUES (?, ?, ?, ?)",
        (user["id"], title, content, mood_level))
    conn.commit()
    row = conn.execute("SELECT * FROM diaries WHERE id = ?", (cur.lastrowid,)).fetchone()
    return 201, {"diary": _diary_public(row)}


def list_diaries(user, mood_filter, query):
    """时间轴列表：mood_filter 使用与情绪记录完全相同的 1-5 等级。"""
    sql = "SELECT * FROM diaries WHERE user_id = ?"
    params = [user["id"]]
    if mood_filter is not None and mood_filter != "":
        level = validate.mood_level(validate.parse_id(mood_filter, "心情等级"))
        sql += " AND mood_level = ?"
        params.append(level)
    query = validate.search_query(query)
    if query:
        sql += " AND (title LIKE ? OR content LIKE ?)"
        like = "%" + query.replace("%", "").replace("_", "") + "%"
        params.extend([like, like])
    sql += " ORDER BY created_at DESC LIMIT 200"
    rows = db.get().execute(sql, params).fetchall()
    return 200, {"diaries": [_diary_public(r) for r in rows]}


def _own_diary(user, diary_id):
    diary_id = validate.parse_id(diary_id)
    row = db.get().execute(
        "SELECT * FROM diaries WHERE id = ? AND user_id = ?",
        (diary_id, user["id"])).fetchone()
    if row is None:
        raise AppError(404, "这篇日记不存在或已被删除")
    return row


def get_diary(user, diary_id):
    return 200, {"diary": _diary_public(_own_diary(user, diary_id))}


def update_diary(user, diary_id, body):
    row = _own_diary(user, diary_id)
    if not isinstance(body, dict):
        raise AppError(400, "请求格式不正确")
    title = validate.diary_title(body.get("title"))
    content = validate.diary_content(body.get("content"))
    mood_level = validate.mood_level(body.get("moodLevel"))
    conn = db.get()
    conn.execute(
        "UPDATE diaries SET title = ?, content = ?, mood_level = ?,"
        " updated_at = datetime('now', 'localtime') WHERE id = ? AND user_id = ?",
        (title, content, mood_level, row["id"], user["id"]))
    conn.commit()
    fresh = conn.execute("SELECT * FROM diaries WHERE id = ?", (row["id"],)).fetchone()
    return 200, {"diary": _diary_public(fresh)}


def delete_diary(user, diary_id):
    row = _own_diary(user, diary_id)
    conn = db.get()
    conn.execute("DELETE FROM diaries WHERE id = ? AND user_id = ?", (row["id"], user["id"]))
    conn.commit()
    return 200, {"ok": True}


# ---------------------------------------------------------------- 心理测评

def _assessment_public(row, user_id, conn, for_admin=False):
    questions = json.loads(row["questions"])
    attempts = conn.execute(
        "SELECT COUNT(*) c, MAX(created_at) last_at FROM assessment_results"
        " WHERE assessment_id = ? AND user_id = ?",
        (row["id"], user_id)).fetchone()
    data = {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "category": row["category"],
        "categoryLabel": db.ASSESSMENT_CATEGORIES.get(row["category"], "综合"),
        "questionCount": len(questions),
        "myAttempts": attempts["c"],
        "lastTakenAt": attempts["last_at"],
        "createdAt": row["created_at"],
    }
    if for_admin:
        # 管理员可以看到完整配置（含分值），并实时得到区间配置体检结果
        bands = json.loads(row["bands"])
        data["questions"] = questions
        data["bands"] = bands
        data["configError"] = validate.band_config_error(questions, bands)
    return data


def list_assessments(user):
    conn = db.get()
    is_admin = user["role"] == "admin"
    rows = conn.execute("SELECT * FROM assessments ORDER BY id").fetchall()
    return 200, {"assessments": [_assessment_public(r, user["id"], conn, for_admin=is_admin) for r in rows]}


def get_assessment(user, assessment_id):
    assessment_id = validate.parse_id(assessment_id)
    row = db.get().execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
    if row is None:
        raise AppError(404, "测评不存在或已下线")
    is_admin = user["role"] == "admin"
    data = _assessment_public(row, user["id"], db.get(), for_admin=is_admin)
    if not is_admin:
        # 普通用户不返回选项分值与区间配置（防作弊）
        data["questions"] = [
            {"text": q["text"], "options": [{"label": o["label"]} for o in q["options"]]}
            for q in json.loads(row["questions"])
        ]
    return 200, {"assessment": data}


def create_assessment(user, body):
    require_admin(user)
    payload = validate.assessment_payload(body)
    conn = db.get()
    cur = conn.execute(
        "INSERT INTO assessments (title, description, category, questions, bands, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (payload["title"], payload["description"], payload["category"],
         json.dumps(payload["questions"], ensure_ascii=False),
         json.dumps(payload["bands"], ensure_ascii=False), user["id"]))
    conn.commit()
    row = conn.execute("SELECT * FROM assessments WHERE id = ?", (cur.lastrowid,)).fetchone()
    return 201, {"assessment": _assessment_public(row, user["id"], conn, for_admin=True)}


def update_assessment(user, assessment_id, body):
    """管理员修正测评（含历史遗留的坏区间配置）；保存时同样做全量区间校验。"""
    require_admin(user)
    assessment_id = validate.parse_id(assessment_id)
    conn = db.get()
    row = conn.execute("SELECT id FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
    if row is None:
        raise AppError(404, "测评不存在或已下线")
    payload = validate.assessment_payload(body)
    conn.execute(
        "UPDATE assessments SET title = ?, description = ?, category = ?, questions = ?, bands = ?"
        " WHERE id = ?",
        (payload["title"], payload["description"], payload["category"],
         json.dumps(payload["questions"], ensure_ascii=False),
         json.dumps(payload["bands"], ensure_ascii=False), assessment_id))
    conn.commit()
    fresh = conn.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
    return 200, {"assessment": _assessment_public(fresh, user["id"], conn, for_admin=True)}


def submit_assessment(user, assessment_id, body):
    """计分只在服务端进行：客户端只提交选项序号，分数与结论由服务端算出并入库。

    历史遗留的坏区间配置（漏空/重叠/倒序）会在这里被拦截：不写入残缺报告，
    并返回具体、可修正的原因。
    """
    assessment_id = validate.parse_id(assessment_id)
    conn = db.get()
    row = conn.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
    if row is None:
        raise AppError(404, "测评不存在或已下线")
    if not isinstance(body, dict):
        raise AppError(400, "请求格式不正确")

    try:
        questions = json.loads(row["questions"])
        bands = json.loads(row["bands"])
    except ValueError:
        raise AppError(409, "该测评的配置数据已损坏，本次作答未保存，请通知管理员修正测评")

    config_err = validate.band_config_error(questions, bands)
    if config_err:
        raise AppError(
            409,
            "该测评的计分区间配置有误（{}），本次作答未保存，请通知管理员修正测评".format(config_err))

    answers = validate.assessment_answers(body.get("answers"), len(questions))
    score = 0
    for i, q in enumerate(questions):
        idx = answers[i]
        if idx < 0 or idx >= len(q["options"]):
            raise AppError(400, "第 {} 题的答案超出选项范围".format(i + 1))
        score += q["options"][idx]["score"]

    # 通过配置校验后，每个可达总分恰好落入一个区间
    band = next((b for b in bands if b["min"] <= score <= b["max"]), None)
    if band is None:  # 理论上不可达，兜底防御
        raise AppError(500, "测评计分配置有误，请联系管理员")

    cur = conn.execute(
        "INSERT INTO assessment_results (user_id, assessment_id, score, band_label, advice, answers)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (user["id"], assessment_id, score, band["label"], band["advice"],
         json.dumps(answers)))
    conn.commit()
    result = conn.execute(
        "SELECT * FROM assessment_results WHERE id = ?", (cur.lastrowid,)).fetchone()
    return 201, {"report": _report_public(result, row)}


# ---------------------------------------------------------------- 个人报告

def _report_public(result_row, assessment_row):
    return {
        "id": result_row["id"],
        "assessmentId": assessment_row["id"],
        "assessmentTitle": assessment_row["title"],
        "category": assessment_row["category"],
        "categoryLabel": db.ASSESSMENT_CATEGORIES.get(assessment_row["category"], "综合"),
        "score": result_row["score"],
        "bandLabel": result_row["band_label"],
        "advice": result_row["advice"],
        "createdAt": result_row["created_at"],
    }


def list_reports(user):
    rows = db.get().execute(
        "SELECT r.*, a.title, a.category FROM assessment_results r"
        " JOIN assessments a ON a.id = r.assessment_id"
        " WHERE r.user_id = ? ORDER BY r.created_at DESC LIMIT 100",
        (user["id"],)).fetchall()
    reports = [{
        "id": r["id"], "assessmentId": r["assessment_id"],
        "assessmentTitle": r["title"], "category": r["category"],
        "categoryLabel": db.ASSESSMENT_CATEGORIES.get(r["category"], "综合"),
        "score": r["score"], "bandLabel": r["band_label"], "advice": r["advice"],
        "createdAt": r["created_at"],
    } for r in rows]
    return 200, {"reports": reports}


def get_report(user, report_id):
    report_id = validate.parse_id(report_id)
    row = db.get().execute(
        "SELECT r.*, a.title, a.category FROM assessment_results r"
        " JOIN assessments a ON a.id = r.assessment_id"
        " WHERE r.id = ? AND r.user_id = ?",
        (report_id, user["id"])).fetchone()
    if row is None:
        raise AppError(404, "报告不存在或已被删除")
    return 200, {
        "report": {
            "id": row["id"], "assessmentId": row["assessment_id"],
            "assessmentTitle": row["title"], "category": row["category"],
            "categoryLabel": db.ASSESSMENT_CATEGORIES.get(row["category"], "综合"),
            "score": row["score"], "bandLabel": row["band_label"],
            "advice": row["advice"], "createdAt": row["created_at"],
        }
    }
