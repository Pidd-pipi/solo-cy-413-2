"""统一输入校验。所有规则集中在服务端这一处，非法输入一律返回 400 + 中文提示。"""
import re
from datetime import datetime, date

from .db import MOOD_LEVELS, ASSESSMENT_CATEGORIES, AVATAR_CHOICES


class AppError(Exception):
    """业务错误：status 为 HTTP 状态码，message 为可直接展示给用户的中文提示。"""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


USERNAME_RE = re.compile(r"^[\w一-龥-]{2,20}$", re.UNICODE)
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _bad(message):
    raise AppError(400, message)


def _str(value, field, min_len, max_len):
    if not isinstance(value, str):
        _bad("{}格式不正确".format(field))
    value = value.strip()
    if len(value) < min_len:
        _bad("{}不能少于 {} 个字符".format(field, min_len))
    if len(value) > max_len:
        _bad("{}不能超过 {} 个字符".format(field, max_len))
    return value


def username(value):
    value = _str(value, "用户名", 2, 20)
    if not USERNAME_RE.match(value):
        _bad("用户名只能包含中英文、数字、下划线或短横线")
    return value


def email(value):
    value = _str(value, "邮箱", 5, 120)
    if not EMAIL_RE.match(value):
        _bad("邮箱格式不正确")
    return value


def password(value):
    if not isinstance(value, str) or len(value) < 8:
        _bad("密码至少需要 8 个字符")
    if len(value) > 72:
        _bad("密码不能超过 72 个字符")
    return value


def display_name(value):
    return _str(value, "昵称", 1, 30)


def bio(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        _bad("简介格式不正确")
    value = value.strip()
    if len(value) > 200:
        _bad("简介不能超过 200 个字符")
    return value


def avatar_emoji(value):
    if value not in AVATAR_CHOICES:
        _bad("请从提供的头像中选择一个")
    return value


def mood_level(value, field="心情等级"):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("{}必须是 1-5 的整数".format(field))
    if value not in MOOD_LEVELS:
        _bad("{}必须在 1-5 之间".format(field))
    return value


def note(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        _bad("备注格式不正确")
    value = value.strip()
    if len(value) > 500:
        _bad("备注不能超过 500 个字符")
    return value


def record_date(value, allow_default=True):
    """校验 YYYY-MM-DD；缺省时取今天；不允许未来日期。"""
    if value is None or value == "":
        if allow_default:
            return date.today().isoformat()
        _bad("日期不能为空")
    if not isinstance(value, str) or not DATE_RE.match(value):
        _bad("日期格式应为 YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _bad("日期不存在，请检查")
    if parsed > date.today():
        _bad("不能记录未来的日期")
    if parsed.year < 2000:
        _bad("日期过早，请检查")
    return value


def diary_title(value):
    return _str(value, "日记标题", 1, 80)


def diary_content(value):
    return _str(value, "日记内容", 1, 10000)


def search_query(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        _bad("搜索词格式不正确")
    return value.strip()[:50]


def assessment_payload(body):
    """校验管理员创建测评的完整载荷，返回清洗后的 dict。"""
    if not isinstance(body, dict):
        _bad("请求格式不正确")
    title = _str(body.get("title"), "测评标题", 1, 80)
    description = body.get("description") or ""
    if not isinstance(description, str) or len(description.strip()) > 500:
        _bad("测评简介不能超过 500 个字符")
    category = body.get("category")
    if category not in ASSESSMENT_CATEGORIES:
        _bad("测评分类不正确")

    questions = body.get("questions")
    if not isinstance(questions, list) or not 1 <= len(questions) <= 30:
        _bad("测评需要 1-30 道题目")
    clean_questions = []
    for i, q in enumerate(questions, 1):
        if not isinstance(q, dict):
            _bad("第 {} 题格式不正确".format(i))
        text = _str(q.get("text"), "第 {} 题题干".format(i), 1, 200)
        options = q.get("options")
        if not isinstance(options, list) or not 2 <= len(options) <= 6:
            _bad("第 {} 题需要 2-6 个选项".format(i))
        clean_options = []
        for j, opt in enumerate(options, 1):
            if not isinstance(opt, dict):
                _bad("第 {} 题第 {} 个选项格式不正确".format(i, j))
            label = _str(opt.get("label"), "第 {} 题第 {} 个选项".format(i, j), 1, 60)
            score = opt.get("score")
            if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 20:
                _bad("第 {} 题第 {} 个选项的分值必须是 0-20 的整数".format(i, j))
            clean_options.append({"label": label, "score": score})
        clean_questions.append({"text": text, "options": clean_options})

    bands = body.get("bands")
    if not isinstance(bands, list) or not 1 <= len(bands) <= 8:
        _bad("测评需要 1-8 个结果区间")
    clean_bands = []
    for i, b in enumerate(bands, 1):
        if not isinstance(b, dict):
            _bad("第 {} 个结果区间格式不正确".format(i))
        lo, hi = b.get("min"), b.get("max")
        for v in (lo, hi):
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 1000:
                _bad("第 {} 个结果区间的分值范围不正确".format(i))
        if lo > hi:
            _bad("第 {} 个结果区间的下限不能大于上限".format(i))
        label = _str(b.get("label"), "第 {} 个结果名称".format(i), 1, 30)
        advice = b.get("advice") or ""
        if not isinstance(advice, str) or len(advice.strip()) > 300:
            _bad("第 {} 个结果的建议不能超过 300 个字符".format(i))
        clean_bands.append({"min": lo, "max": hi, "label": label, "advice": advice.strip()})

    return {
        "title": title,
        "description": description.strip(),
        "category": category,
        "questions": clean_questions,
        "bands": clean_bands,
    }


def assessment_answers(value, question_count):
    if not isinstance(value, list):
        _bad("答案格式不正确")
    if len(value) != question_count:
        _bad("请完成全部 {} 道题后再提交".format(question_count))
    for v in value:
        if isinstance(v, bool) or not isinstance(v, int):
            _bad("答案格式不正确")
    return value


def parse_date_param(value, field="日期"):
    """解析查询参数里的日期（用于按日筛选），非法时 400。"""
    if not isinstance(value, str) or not DATE_RE.match(value):
        _bad("{}格式应为 YYYY-MM-DD".format(field))
    try:
        date.fromisoformat(value)
    except ValueError:
        _bad("{}不存在，请检查".format(field))
    return value


def parse_id(value, field="ID"):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise AppError(404, "内容不存在或已被删除")
    if parsed <= 0:
        raise AppError(404, "内容不存在或已被删除")
    return parsed
