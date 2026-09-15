"""SQLite 数据层：连接管理、表结构、种子数据。

设计要点：
- 所有私人数据表都带 user_id 外键，业务层查询一律附加 user_id 条件，
  从结构上保证「同一账号只能看到自己的数据」。
- 心情等级（1-5）全站只有 MOOD_LEVELS 这一份定义，情绪记录、日记、
  心情花园、本周曲线、时间轴筛选共用同一口径。
"""
import json
import os
import sqlite3
import threading

_local = threading.local()
_db_path = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL COLLATE NOCASE,
    email         TEXT NOT NULL COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    display_name  TEXT NOT NULL DEFAULT '',
    bio           TEXT NOT NULL DEFAULT '',
    avatar_emoji  TEXT NOT NULL DEFAULT '🌱',
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email    ON users(email);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS moods (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    level       INTEGER NOT NULL CHECK (level BETWEEN 1 AND 5),
    note        TEXT NOT NULL DEFAULT '',
    record_date TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_moods_user_date ON moods(user_id, record_date);

CREATE TABLE IF NOT EXISTS diaries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    content    TEXT NOT NULL,
    mood_level INTEGER NOT NULL CHECK (mood_level BETWEEN 1 AND 5),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_diaries_user ON diaries(user_id, created_at);

CREATE TABLE IF NOT EXISTS assessments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT 'general',
    questions   TEXT NOT NULL,   -- JSON: [{text, options:[{label, score}]}]
    bands       TEXT NOT NULL,   -- JSON: [{min, max, label, advice}]
    created_by  INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS assessment_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    score         INTEGER NOT NULL,
    band_label    TEXT NOT NULL,
    advice        TEXT NOT NULL DEFAULT '',
    answers       TEXT NOT NULL,  -- JSON: [optionIndex, ...]
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_results_user ON assessment_results(user_id, created_at);
"""

# 全站唯一的心情等级口径：1-5。情绪记录、日记、花园、周曲线、筛选器共用。
MOOD_LEVELS = {
    1: {"label": "很低落", "emoji": "😞", "flower": "🥀"},
    2: {"label": "低落",   "emoji": "😟", "flower": "🌱"},
    3: {"label": "平静",   "emoji": "😐", "flower": "🌿"},
    4: {"label": "不错",   "emoji": "🙂", "flower": "🌷"},
    5: {"label": "很好",   "emoji": "😄", "flower": "🌻"},
}

ASSESSMENT_CATEGORIES = {
    "anxiety": "焦虑", "depression": "抑郁", "stress": "压力",
    "sleep": "睡眠", "general": "综合",
}

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"  # 仅用于本地开发的种子账号，部署时请通过环境变量覆盖

AVATAR_CHOICES = ["🌱", "🌿", "🌻", "🌷", "🍀", "🌵", "🌙", "⭐", "🐱", "🦊", "🐼", "🐳", "🌳"]


def _likert4():
    return [
        {"label": "完全没有", "score": 0}, {"label": "偶尔有", "score": 1},
        {"label": "经常有", "score": 2}, {"label": "几乎总是", "score": 3},
    ]


def _freq4():
    return [
        {"label": "从不", "score": 0}, {"label": "很少", "score": 1},
        {"label": "有时", "score": 2}, {"label": "经常", "score": 3},
    ]


def _seed_assessments():
    return [
        {
            "title": "焦虑情绪自评（简版）",
            "description": "过去一周里，下列感受出现的频率如何？请凭直觉作答，结果仅用于自我了解，不构成医学诊断。",
            "category": "anxiety",
            "questions": [
                {"text": t, "options": _likert4()} for t in [
                    "我感到紧张、焦虑或心烦意乱",
                    "我无法停止或控制担心",
                    "我很难放松下来",
                    "我容易烦躁或坐立不安",
                    "我感到好像有可怕的事情要发生",
                ]
            ],
            "bands": [
                {"min": 0, "max": 4, "label": "状态平稳",
                 "advice": "近期焦虑水平较低，继续保持规律作息与适度运动。"},
                {"min": 5, "max": 9, "label": "轻度焦虑",
                 "advice": "有一些紧绷感。可以试试深呼吸、散步，或把担心的事情写下来。"},
                {"min": 10, "max": 12, "label": "中度焦虑",
                 "advice": "焦虑已影响到日常状态，建议规律进行放松练习，并与信任的人聊聊。"},
                {"min": 13, "max": 15, "label": "需要关注",
                 "advice": "焦虑水平偏高，建议尽快寻求心理咨询师或医生的专业支持。你不是一个人。"},
            ],
        },
        {
            "title": "压力感知小测",
            "description": "评估最近一个月你感知到的压力水平，帮助了解当前的负荷状态。",
            "category": "stress",
            "questions": [
                {"text": t, "options": _freq4()} for t in [
                    "因为发生意外的事情而感到心烦",
                    "感到无法控制自己生活中重要的事情",
                    "感到紧张和有压力",
                    "对要处理的事情感到没有把握",
                    "感到困难堆积如山，无法克服",
                ]
            ],
            "bands": [
                {"min": 0, "max": 4, "label": "压力较低",
                 "advice": "当前负荷在舒适区，记得留时间做让自己开心的事。"},
                {"min": 5, "max": 8, "label": "压力适中",
                 "advice": "压力在可管理范围，注意劳逸结合，睡前一小时远离屏幕。"},
                {"min": 9, "max": 12, "label": "压力偏高",
                 "advice": "担子有点重了。试着把任务拆小、向他人求助，每天安排 10 分钟放松。"},
                {"min": 13, "max": 15, "label": "压力过载",
                 "advice": "长期高压会消耗身心，请认真考虑调整节奏，必要时寻求专业帮助。"},
            ],
        },
        {
            "title": "睡眠质量评估",
            "description": "回顾最近一周的睡眠情况，了解休息质量对情绪的影响。",
            "category": "sleep",
            "questions": [
                {"text": t, "options": _freq4()} for t in [
                    "入睡困难（躺下 30 分钟以上仍清醒）",
                    "夜间易醒或早醒后难以再睡",
                    "白天感到困倦、精力不足",
                    "睡眠问题影响了白天的情绪或工作",
                ]
            ],
            "bands": [
                {"min": 0, "max": 2, "label": "睡眠良好",
                 "advice": "睡眠质量不错，继续保持稳定的作息时间。"},
                {"min": 3, "max": 5, "label": "轻度困扰",
                 "advice": "睡眠有些小状况。试试固定起床时间、睡前减少咖啡因和屏幕。"},
                {"min": 6, "max": 8, "label": "睡眠欠佳",
                 "advice": "睡眠已影响白天状态，建议建立睡前放松仪式，白天适量运动。"},
                {"min": 9, "max": 12, "label": "明显失眠",
                 "advice": "睡眠问题比较明显，建议记录睡眠日记并咨询医生或睡眠门诊。"},
            ],
        },
    ]


def init(path):
    """在服务器启动时调用一次：建目录、建表、写种子数据（幂等）。"""
    global _db_path
    _db_path = path
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = _new_conn()
    try:
        conn.executescript(SCHEMA)
        _seed(conn)
        conn.commit()
    finally:
        conn.close()


def _new_conn():
    conn = sqlite3.connect(_db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def get():
    """当前线程的连接（每线程一条，避免跨线程共享连接）。"""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _new_conn()
        _local.conn = conn
    return conn


def _seed(conn):
    from . import security  # 延迟导入避免循环依赖

    row = conn.execute("SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)).fetchone()
    if row is None:
        password = os.environ.get("ADMIN_PASSWORD", ADMIN_PASSWORD)
        conn.execute(
            "INSERT INTO users (username, email, password_hash, role, display_name, bio, avatar_emoji)"
            " VALUES (?, ?, ?, 'admin', ?, ?, ?)",
            (ADMIN_USERNAME, "admin@mindgarden.local", security.hash_password(password),
             "花园管理员", "系统内置管理员账号，负责维护心理测评。", "🌳"),
        )
    admin_id = conn.execute(
        "SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)).fetchone()["id"]

    count = conn.execute("SELECT COUNT(*) AS c FROM assessments").fetchone()["c"]
    if count == 0:
        for a in _seed_assessments():
            conn.execute(
                "INSERT INTO assessments (title, description, category, questions, bands, created_by)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (a["title"], a["description"], a["category"],
                 json.dumps(a["questions"], ensure_ascii=False),
                 json.dumps(a["bands"], ensure_ascii=False), admin_id),
            )
