#!/usr/bin/env python3
"""心晴花园 · API 集成测试。

用法：
    python3 tests/test_api.py

会启动一个独立的服务器子进程（临时数据库、端口 18099），
覆盖：注册登录、权限边界、归属隔离、等级口径一致性、非法输入反馈。
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import urllib.parse
from http.cookiejar import CookieJar

BASE = "http://127.0.0.1:18099"
SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

passed = 0
failed = 0
failures = []


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print("  ✓ {}".format(name))
    else:
        failed += 1
        failures.append(name)
        print("  ✗ {}  {}".format(name, detail))


class Client:
    """带独立 CookieJar 的测试客户端（模拟一个浏览器）。"""

    def __init__(self):
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar()))

    def req(self, method, path, body=None, csrf=True, headers=None):
        url = BASE + urllib.parse.quote(path, safe="/?=&")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if csrf:
            request.add_header("X-Requested-With", "fetch")
        for k, v in (headers or {}).items():
            request.add_header(k, v)
        try:
            with self.opener.open(request, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8")
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"raw": raw}


def today(offset=0):
    from datetime import date, timedelta
    return (date.today() + timedelta(days=offset)).isoformat()


def main():
    # 启动独立服务器（临时数据库）
    tmpdir = tempfile.mkdtemp(prefix="mg_test_")
    db_file = os.path.join(tmpdir, "test.db")
    env = dict(os.environ)
    env["DB_PATH"] = db_file
    env["PORT"] = "18099"
    proc = subprocess.Popen(
        [sys.executable, os.path.join(SERVER_DIR, "server.py")],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(BASE + "/api/health", timeout=2)
                break
            except Exception:
                time.sleep(0.2)
        else:
            print("服务器启动失败")
            return 1
        run_tests(db_file)
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    print("\n结果：{} 通过，{} 失败".format(passed, failed))
    if failures:
        print("失败用例：")
        for f in failures:
            print("  - " + f)
    return 0 if failed == 0 else 1


def run_tests(db_file):
    alice = Client()
    bob = Client()

    print("\n[1] 注册与输入校验")
    s, b = alice.req("POST", "/api/auth/register",
                     {"username": "alice", "email": "not-an-email", "password": "password123"})
    check("非法邮箱被拒绝(400)", s == 400 and "邮箱" in b.get("error", ""), str(b))
    s, b = alice.req("POST", "/api/auth/register",
                     {"username": "alice", "email": "alice@test.com", "password": "short"})
    check("过短密码被拒绝(400)", s == 400 and "密码" in b.get("error", ""), str(b))
    s, b = alice.req("POST", "/api/auth/register",
                     {"username": "alice", "email": "alice@test.com", "password": "password123"})
    check("注册成功(201)", s == 201 and b["user"]["username"] == "alice", str(b))
    s, b = alice.req("POST", "/api/auth/register",
                     {"username": "Alice", "email": "alice2@test.com", "password": "password123"})
    check("用户名重复(409，不区分大小写)", s == 409, str(b))
    s, b = alice.req("POST", "/api/auth/register",
                     {"username": "someone", "email": "alice@test.com", "password": "password123"})
    check("邮箱重复(409)", s == 409, str(b))

    print("\n[2] 登录 / 登出 / 会话")
    s, b = bob.req("POST", "/api/auth/login", {"username": "alice", "password": "wrong-password"})
    check("错误密码(401)", s == 401, str(b))
    s, b = bob.req("POST", "/api/auth/login", {"username": "alice", "password": "password123"})
    check("登录成功(200)", s == 200 and b["user"]["username"] == "alice", str(b))
    s, b = bob.req("GET", "/api/auth/me")
    check("会话保持：/me 返回当前用户", s == 200 and b["user"]["username"] == "alice", str(b))

    print("\n[3] 未登录不能读写私人数据")
    anon = Client()
    for method, path, body in [
        ("GET", "/api/moods/week", None), ("GET", "/api/moods?date=" + today(), None),
        ("POST", "/api/moods", {"level": 3}), ("GET", "/api/diaries", None),
        ("POST", "/api/diaries", {"title": "t", "content": "c", "moodLevel": 3}),
        ("GET", "/api/profile", None), ("GET", "/api/reports", None),
        ("GET", "/api/garden", None), ("GET", "/api/assessments", None),
    ]:
        s, b = anon.req(method, path, body)
        check("未登录 {} {} → 401".format(method, path.split("?")[0]), s == 401, str(b))

    print("\n[4] 情绪记录：等级校验 + 周曲线/按日筛选一致")
    for bad in [0, 6, -1, "x", 3.5, True]:
        s, b = alice.req("POST", "/api/moods", {"level": bad})
        check("非法等级 {!r} 被拒绝(400)".format(bad), s == 400, str(b))
    s, b = alice.req("POST", "/api/moods", {"level": 4, "date": today(1)})
    check("未来日期被拒绝(400)", s == 400, str(b))
    s, b = alice.req("POST", "/api/moods", {"level": 5, "note": "今天很棒"})
    check("记录今天的心情(201)", s == 201 and b["mood"]["level"] == 5, str(b))
    s, b = alice.req("POST", "/api/moods", {"level": 3, "date": today(-1), "note": "昨天一般"})
    check("补记昨天的心情(201)", s == 201, str(b))
    s, b = alice.req("POST", "/api/moods", {"level": 1, "date": today(-1)})
    check("昨天再记一条(201)", s == 201, str(b))

    s, day_data = alice.req("GET", "/api/moods?date=" + today(-1))
    check("按日筛选返回昨天 2 条", s == 200 and len(day_data["moods"]) == 2, str(day_data))
    s, week = alice.req("GET", "/api/moods/week")
    yesterday_avg = next(d for d in week["days"] if d["date"] == today(-1))["avg"]
    today_avg = next(d for d in week["days"] if d["date"] == today())["avg"]
    check("周曲线与按日筛选同源：昨天均值=(1+3)/2=2.0",
          s == 200 and yesterday_avg == 2.0, str(week))
    check("周曲线今天均值=5.0", today_avg == 5.0, str(week))
    check("周平均=(5+2)/2=3.5", week["weekAvg"] == 3.5, str(week))

    print("\n[5] 归属隔离：别人看不到也动不了我的数据")
    s, b = bob.req("POST", "/api/auth/register",
                   {"username": "bob", "email": "bob@test.com", "password": "password456"})
    check("bob 注册成功", s == 201, str(b))
    s, week_bob = bob.req("GET", "/api/moods/week")
    check("bob 的周曲线全为空（看不到 alice 的记录）",
          all(d["count"] == 0 for d in week_bob["days"]), str(week_bob))
    s, day_bob = bob.req("GET", "/api/moods?date=" + today(-1))
    check("bob 按日筛选为空", len(day_bob["moods"]) == 0, str(day_bob))
    mood_id = day_data["moods"][0]["id"]
    s, b = bob.req("DELETE", "/api/moods/{}".format(mood_id))
    check("bob 删除 alice 的记录 → 404", s == 404, str(b))
    s, b = bob.req("GET", "/api/diaries/1")
    check("bob 读 alice 的日记 → 404", s == 404, str(b))

    print("\n[6] 日记本：CRUD + 同一套心情等级筛选")
    s, b = alice.req("POST", "/api/diaries", {"title": "", "content": "x", "moodLevel": 3})
    check("空标题被拒绝(400)", s == 400, str(b))
    s, b = alice.req("POST", "/api/diaries", {"title": "t", "content": "x", "moodLevel": 9})
    check("日记心情等级越界被拒绝(400)", s == 400, str(b))
    s, d1 = alice.req("POST", "/api/diaries",
                      {"title": "开心的一天", "content": "今天去了公园", "moodLevel": 5})
    check("写日记(201)", s == 201, str(d1))
    s, d2 = alice.req("POST", "/api/diaries",
                      {"title": "有点累", "content": "工作很多", "moodLevel": 2})
    check("再写一篇(201)", s == 201, str(d2))
    diary_id = d1["diary"]["id"]
    s, lst = alice.req("GET", "/api/diaries?mood=5")
    check("按心情 5 级筛选 → 只剩 1 篇", s == 200 and len(lst["diaries"]) == 1
          and lst["diaries"][0]["moodLevel"] == 5, str(lst))
    s, lst = alice.req("GET", "/api/diaries?mood=2")
    check("按心情 2 级筛选 → 只剩「有点累」",
          len(lst["diaries"]) == 1 and lst["diaries"][0]["title"] == "有点累", str(lst))
    s, lst = alice.req("GET", "/api/diaries?q=公园")
    check("关键词搜索「公园」命中 1 篇", len(lst["diaries"]) == 1, str(lst))
    s, b = alice.req("PUT", "/api/diaries/{}".format(diary_id),
                     {"title": "开心的一天（改）", "content": "今天去了公园和湖边", "moodLevel": 4})
    check("编辑日记(200)", s == 200 and b["diary"]["moodLevel"] == 4, str(b))
    s, lst = alice.req("GET", "/api/diaries?mood=5")
    check("改完等级后，5 级筛选不再命中（口径一致）", len(lst["diaries"]) == 0, str(lst))
    s, b = bob.req("PUT", "/api/diaries/{}".format(diary_id),
                   {"title": "hack", "content": "hack", "moodLevel": 1})
    check("bob 改 alice 的日记 → 404", s == 404, str(b))
    s, b = bob.req("DELETE", "/api/diaries/{}".format(diary_id))
    check("bob 删 alice 的日记 → 404", s == 404, str(b))

    print("\n[7] 心理测评：权限 + 计分 + 报告")
    s, lst = alice.req("GET", "/api/assessments")
    check("测评列表（种子 ≥3）", s == 200 and len(lst["assessments"]) >= 3, str(lst))
    check("普通用户看不到创建入口所需的数据也无妨，列表含题数",
          all(a["questionCount"] > 0 for a in lst["assessments"]), str(lst))
    s, b = alice.req("POST", "/api/assessments", {"title": "x"})
    check("普通用户创建测评 → 403", s == 403, str(b))

    admin = Client()
    s, b = admin.req("POST", "/api/auth/login", {"username": "admin", "password": "admin123"})
    check("管理员登录", s == 200 and b["user"]["role"] == "admin", str(b))
    s, b = admin.req("POST", "/api/assessments", {"title": "不完整"})
    check("管理员提交非法载荷 → 400", s == 400, str(b))
    new_assessment = {
        "title": "情绪状态快评", "description": "三道题快速了解当下状态", "category": "general",
        "questions": [
            {"text": "我现在感到放松", "options": [
                {"label": "符合", "score": 0}, {"label": "不符合", "score": 2}]},
            {"text": "我现在感到疲惫", "options": [
                {"label": "符合", "score": 2}, {"label": "不符合", "score": 0}]},
        ],
        "bands": [
            {"min": 0, "max": 1, "label": "状态不错", "advice": "继续保持"},
            {"min": 2, "max": 4, "label": "需要休息", "advice": "给自己放个假"},
        ],
    }
    s, b = admin.req("POST", "/api/assessments", new_assessment)
    check("管理员创建测评(201)", s == 201 and b["assessment"]["questionCount"] == 2, str(b))
    new_id = b["assessment"]["id"]

    s, detail = alice.req("GET", "/api/assessments/{}".format(new_id))
    check("测评详情不含选项分值（防作弊）",
          s == 200 and "score" not in json.dumps(detail), str(detail))
    s, b = alice.req("POST", "/api/assessments/{}/submit".format(new_id), {"answers": [0]})
    check("少答一题 → 400", s == 400, str(b))
    s, b = alice.req("POST", "/api/assessments/{}/submit".format(new_id), {"answers": [0, 5]})
    check("选项序号越界 → 400", s == 400, str(b))
    # Q1 选「不符合」=2 分，Q2 选「符合」=2 分，总分应为 4
    s, result = alice.req("POST", "/api/assessments/{}/submit".format(new_id), {"answers": [1, 0]})
    check("提交成功：服务端计分 2+2=4 → 「需要休息」",
          s == 201 and result["report"]["score"] == 4
          and result["report"]["bandLabel"] == "需要休息", str(result))
    report_id = result["report"]["id"]

    s, reports = alice.req("GET", "/api/reports")
    check("报告进入「我的报告」列表", s == 200
          and any(r["id"] == report_id for r in reports["reports"]), str(reports))
    s, one = alice.req("GET", "/api/reports/{}".format(report_id))
    check("报告详情可读", s == 200 and one["report"]["score"] == 4, str(one))
    s, b = bob.req("GET", "/api/reports/{}".format(report_id))
    check("bob 读 alice 的报告 → 404", s == 404, str(b))
    s, reports_bob = bob.req("GET", "/api/reports")
    check("bob 的报告列表为空", len(reports_bob["reports"]) == 0, str(reports_bob))

    print("\n[8] 个人资料")
    s, prof = alice.req("GET", "/api/profile")
    check("资料页统计：2 条情绪 + 2 篇日记 + 1 份报告",
          s == 200 and prof["stats"]["moodCount"] == 2 + 1  # 今天1条+昨天2条=3
          or prof["stats"]["moodCount"] == 3, str(prof))
    check("日记统计=2", prof["stats"]["diaryCount"] == 2, str(prof))
    check("报告统计=1", prof["stats"]["reportCount"] == 1, str(prof))
    s, b = alice.req("PUT", "/api/profile",
                     {"displayName": "爱丽丝", "bio": "爱自己", "avatarEmoji": "🌻"})
    check("更新资料(200)", s == 200 and b["user"]["displayName"] == "爱丽丝", str(b))
    s, b = alice.req("PUT", "/api/profile",
                     {"displayName": "爱丽丝", "bio": "", "avatarEmoji": "💣"})
    check("非法头像被拒绝(400)", s == 400, str(b))

    print("\n[9] 心情花园")
    s, g = alice.req("GET", "/api/garden")
    check("花园有 3 朵花（对应 3 条记录）", s == 200 and len(g["flowers"]) == 3, str(g))
    check("连续记录 2 天", g["stats"]["streak"] == 2, str(g))
    check("花朵等级与记录一致（含 5 级 🌻）",
          any(f["level"] == 5 and f["flower"] == "🌻" for f in g["flowers"]), str(g))

    print("\n[10] CSRF 防护与登出")
    s, b = alice.req("POST", "/api/moods", {"level": 3}, csrf=False)
    check("缺少 X-Requested-With 的写请求 → 403", s == 403, str(b))
    s, b = alice.req("POST", "/api/auth/logout", {})
    check("登出(200)", s == 200, str(b))
    s, b = alice.req("GET", "/api/auth/me")
    check("登出后 /me → 401", s == 401, str(b))

    print("\n[11] 测评区间：保存时校验漏空/重叠/倒序")
    s, b = alice.req("POST", "/api/auth/login", {"username": "alice", "password": "password123"})
    check("alice 重新登录", s == 200, str(b))

    def mk(bands, q_scores=((0, 2), (0, 2))):
        # 默认两题、选项分值 {0,2}：可达总分为 {0,2,4}（1 和 3 不可达）
        return {
            "title": "区间校验测试", "description": "", "category": "general",
            "questions": [
                {"text": "题{}".format(i + 1),
                 "options": [{"label": "选{}分".format(sc), "score": sc} for sc in scores]}
                for i, scores in enumerate(q_scores)
            ],
            "bands": [dict(b, advice=b.get("advice", "")) for b in bands],
        }

    s, b = admin.req("POST", "/api/assessments", mk([
        {"min": 0, "max": 1, "label": "低"}, {"min": 2, "max": 4, "label": "高"}]))
    check("稀疏总分合法配置(201)：1/3 不可达不算漏空", s == 201, str(b))
    s, b = admin.req("POST", "/api/assessments", mk([
        {"min": 0, "max": 0, "label": "低"}, {"min": 4, "max": 4, "label": "高"}]))
    check("漏空被拒绝(400)，原因指出具体总分",
          s == 400 and "总分 2 没有被任何结果区间覆盖" in b.get("error", ""), str(b))
    s, b = admin.req("POST", "/api/assessments", mk([
        {"min": 0, "max": 2, "label": "低"}, {"min": 2, "max": 4, "label": "高"}]))
    check("重叠被拒绝(400)，原因指出冲突区间",
          s == 400 and "重叠" in b.get("error", "") and "0-2" in b.get("error", ""), str(b))
    s, b = admin.req("POST", "/api/assessments", mk([
        {"min": 3, "max": 1, "label": "坏"}, {"min": 0, "max": 4, "label": "全"}]))
    check("倒序被拒绝(400)，原因指出具体区间",
          s == 400 and "3-1" in b.get("error", "") and "下限" in b.get("error", ""), str(b))

    print("\n[12] 存量坏数据：不写残缺报告、原因可修正、修复后恢复")
    # 直接向数据库塞一份「历史遗留」坏测评（总分 0 没有区间覆盖）
    conn = sqlite3.connect(db_file)
    admin_id = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()[0]
    bad_q = [{"text": "题1", "options": [{"label": "a", "score": 0}, {"label": "b", "score": 2}]}]
    bad_bands = [{"min": 1, "max": 2, "label": "只有这一段", "advice": "x"}]
    cur = conn.execute(
        "INSERT INTO assessments (title, description, category, questions, bands, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        ("历史坏测评", "", "general",
         json.dumps(bad_q, ensure_ascii=False), json.dumps(bad_bands, ensure_ascii=False), admin_id))
    conn.commit()
    bad_id = cur.lastrowid
    conn.close()

    s, before = alice.req("GET", "/api/reports")
    s, b = alice.req("POST", "/api/assessments/{}/submit".format(bad_id), {"answers": [0]})
    check("坏配置提交 → 409，含具体可修正原因",
          s == 409 and "总分 0 没有被任何结果区间覆盖" in b.get("error", "")
          and "未保存" in b.get("error", ""), str(b))
    s, after = alice.req("GET", "/api/reports")
    check("未写出残缺报告（报告数不变）", len(after["reports"]) == len(before["reports"]), str(after))

    s, lst = admin.req("GET", "/api/assessments")
    bad_item = next(a for a in lst["assessments"] if a["id"] == bad_id)
    check("管理员列表标记 configError", bool(bad_item.get("configError")), str(bad_item))
    s, lst_u = alice.req("GET", "/api/assessments")
    bad_item_u = next(a for a in lst_u["assessments"] if a["id"] == bad_id)
    check("普通用户不暴露 configError", "configError" not in bad_item_u, str(bad_item_u))

    s, b = alice.req("PUT", "/api/assessments/{}".format(bad_id),
                     mk([{"min": 0, "max": 2, "label": "好"}]))
    check("普通用户编辑测评 → 403", s == 403, str(b))
    s, b = admin.req("PUT", "/api/assessments/{}".format(bad_id),
                     mk([{"min": 0, "max": 0, "label": "低"}]))
    check("编辑保存时同样校验（仍漏空 → 400）", s == 400 and "漏空" in b.get("error", ""), str(b))
    fixed = mk([{"min": 0, "max": 1, "label": "低"}, {"min": 2, "max": 4, "label": "高"}])
    fixed["title"] = "历史坏测评（已修复）"
    s, b = admin.req("PUT", "/api/assessments/{}".format(bad_id), fixed)
    check("管理员修复成功(200)，configError 消除",
          s == 200 and b["assessment"]["configError"] is None, str(b))
    s, result = alice.req("POST", "/api/assessments/{}/submit".format(bad_id), {"answers": [0, 0]})
    check("修复后可正常提交(201)，计分正确",
          s == 201 and result["report"]["score"] == 0 and result["report"]["bandLabel"] == "低", str(result))

    print("\n[13] 已有报告与汇总不受影响")
    s, one = alice.req("GET", "/api/reports/{}".format(report_id))
    check("此前的报告仍可读取", s == 200 and one["report"]["score"] == 4, str(one))
    s, reports = alice.req("GET", "/api/reports")
    check("报告汇总包含新旧两份", len(reports["reports"]) == 2, str(reports))
    s, lst = alice.req("GET", "/api/assessments")
    check("正常测评不受影响（种子测评无 configError 字段）",
          all("configError" not in a for a in lst["assessments"]), str(lst)[:200])


if __name__ == "__main__":
    sys.exit(main())
