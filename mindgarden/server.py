#!/usr/bin/env python3
"""心晴花园 MindGarden —— 一体化服务器（仅依赖 Python 3.8+ 标准库）。

用法：
    python3 server.py            # 默认 http://localhost:8000
    PORT=9000 python3 server.py  # 指定端口
    DB_PATH=/tmp/x.db python3 server.py
    MAINTENANCE=1 python3 server.py   # 维护模式：API 一律返回 503，用于演示降级提示

同时提供：
- /api/*  JSON API（会话 Cookie 认证）
- /*      前端静态文件（public/ 目录）
"""
import json
import os
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
sys.path.insert(0, BASE_DIR)

from app import db, handlers  # noqa: E402
from app.validate import AppError  # noqa: E402

PORT = int(os.environ.get("PORT", "8000"))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "data", "mindgarden.db"))
MAINTENANCE = os.environ.get("MAINTENANCE", "") == "1"
MAX_BODY = 256 * 1024  # 256KB

SESSION_COOKIE = "mg_session"

# 路由表：(方法, 路径模板, 处理函数, 是否需要登录)
# 处理函数签名：fn(ctx) -> (status, payload)；ctx 含 user/body/params/query/token/ip。
ROUTES = [
    ("GET",  "/api/health",                      lambda c: (200, {"ok": True, "service": "mindgarden"}), False),
    ("POST", "/api/auth/register",               lambda c: handlers.register(c["body"], c["ip"]), False),
    ("POST", "/api/auth/login",                  lambda c: handlers.login(c["body"], c["ip"]), False),
    ("POST", "/api/auth/logout",                 lambda c: handlers.logout(c["token"]), False),
    ("GET",  "/api/auth/me",                     lambda c: handlers.me(c["user"]), True),

    ("GET",  "/api/profile",                     lambda c: handlers.get_profile(c["user"]), True),
    ("PUT",  "/api/profile",                     lambda c: handlers.update_profile(c["user"], c["body"]), True),

    ("POST", "/api/moods",                       lambda c: handlers.create_mood(c["user"], c["body"]), True),
    ("GET",  "/api/moods",                       lambda c: handlers.list_moods_by_date(c["user"], c["query"].get("date", [""])[0]), True),
    ("GET",  "/api/moods/week",                  lambda c: handlers.week_summary(c["user"]), True),
    ("DELETE", "/api/moods/{id}",                lambda c: handlers.delete_mood(c["user"], c["params"]["id"]), True),

    ("GET",  "/api/garden",                      lambda c: handlers.garden(c["user"]), True),

    ("POST", "/api/diaries",                     lambda c: handlers.create_diary(c["user"], c["body"]), True),
    ("GET",  "/api/diaries",                     lambda c: handlers.list_diaries(c["user"], c["query"].get("mood", [None])[0], c["query"].get("q", [None])[0]), True),
    ("GET",  "/api/diaries/{id}",                lambda c: handlers.get_diary(c["user"], c["params"]["id"]), True),
    ("PUT",  "/api/diaries/{id}",                lambda c: handlers.update_diary(c["user"], c["params"]["id"], c["body"]), True),
    ("DELETE", "/api/diaries/{id}",              lambda c: handlers.delete_diary(c["user"], c["params"]["id"]), True),

    ("GET",  "/api/assessments",                 lambda c: handlers.list_assessments(c["user"]), True),
    ("POST", "/api/assessments",                 lambda c: handlers.create_assessment(c["user"], c["body"]), True),
    ("GET",  "/api/assessments/{id}",            lambda c: handlers.get_assessment(c["user"], c["params"]["id"]), True),
    ("PUT",  "/api/assessments/{id}",            lambda c: handlers.update_assessment(c["user"], c["params"]["id"], c["body"]), True),
    ("POST", "/api/assessments/{id}/submit",     lambda c: handlers.submit_assessment(c["user"], c["params"]["id"], c["body"]), True),

    ("GET",  "/api/reports",                     lambda c: handlers.list_reports(c["user"]), True),
    ("GET",  "/api/reports/{id}",                lambda c: handlers.get_report(c["user"], c["params"]["id"]), True),
]

_COMPILED = []
for _method, _pattern, _fn, _auth in ROUTES:
    _regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", _pattern) + "$")
    _COMPILED.append((_method, _regex, _fn, _auth))

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MindGarden/1.0"

    # -------------------------------------------------- 基础设施

    def log_message(self, fmt, *args):  # 简洁访问日志
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; "
                         "style-src 'self' 'unsafe-inline'; "
                         "script-src 'self'; connect-src 'self'")

    def _send_json(self, status, obj, extra_headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status, message):
        self._send_json(status, {"error": message})

    def _cookies(self):
        raw = self.headers.get("Cookie", "")
        jar = {}
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                jar[k] = v
        return jar

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise AppError(413, "请求内容过大")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise AppError(400, "请求体不是合法的 JSON")

    # -------------------------------------------------- 请求分发

    def _dispatch(self, method):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            self._handle_api(method, path, parse_qs(parsed.query))
        elif method == "GET":
            self._serve_static(path)
        else:
            self._send_error(404, "资源不存在")

    def _handle_api(self, method, path, query):
        # 维护模式：演示「服务暂时不可用」的可见反馈
        if MAINTENANCE and path != "/api/health":
            self._send_error(503, "服务维护中，请稍后再试")
            return

        # 写操作要求自定义头，配合 SameSite Cookie 抵御 CSRF
        if method in ("POST", "PUT", "DELETE"):
            if self.headers.get("X-Requested-With") != "fetch":
                self._send_error(403, "非法的请求来源")
                return

        try:
            body = self._read_body() if method in ("POST", "PUT", "DELETE") else {}
        except AppError as e:
            self._send_error(e.status, e.message)
            return

        for route_method, regex, fn, need_auth in _COMPILED:
            if route_method != method:
                continue
            m = regex.match(path)
            if not m:
                continue
            token = self._cookies().get(SESSION_COOKIE, "")
            ctx = {
                "body": body,
                "params": m.groupdict(),
                "query": query,
                "token": token,
                "ip": self.client_address[0] if self.client_address else "unknown",
                "user": None,
            }
            try:
                if need_auth:
                    ctx["user"] = handlers.require_user(token)
                status, payload = fn(ctx)
            except AppError as e:
                self._send_error(e.status, e.message)
                return
            except Exception:  # 未预期错误：记录日志，对外只给通用提示
                traceback.print_exc()
                self._send_error(500, "服务器开小差了，请稍后再试")
                return

            headers = {}
            if isinstance(payload, dict) and "token" in payload:
                token_value = payload.pop("token")
                headers["Set-Cookie"] = (
                    "{}={}; HttpOnly; Path=/; SameSite=Lax; Max-Age={}".format(
                        SESSION_COOKIE, token_value, 7 * 24 * 3600))
            if path == "/api/auth/logout":
                headers["Set-Cookie"] = (
                    "{}=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0".format(SESSION_COOKIE))
            self._send_json(status, payload, headers)
            return

        self._send_error(404, "接口不存在")

    def _serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        # 防目录穿越
        clean = os.path.normpath(path).lstrip("/")
        full = os.path.join(PUBLIC_DIR, clean)
        if not os.path.abspath(full).startswith(os.path.abspath(PUBLIC_DIR)):
            self._send_error(403, "禁止访问")
            return
        if not os.path.isfile(full):
            # SPA 兜底：非文件路径一律回到 index.html
            full = os.path.join(PUBLIC_DIR, "index.html")
            if not os.path.isfile(full):
                self._send_error(404, "页面不存在")
                return
        ext = os.path.splitext(full)[1].lower()
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        try:
            with open(full, "rb") as f:
                data = f.read()
        except OSError:
            self._send_error(404, "文件不存在")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self._security_headers()
        if ext in (".js", ".css"):
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")


def main():
    db.init(DB_PATH)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("🌿 心晴花园 MindGarden 已启动")
    print("   访问地址: http://localhost:{}".format(PORT))
    print("   数据库:   {}".format(DB_PATH))
    if MAINTENANCE:
        print("   ⚠️  维护模式已开启（MAINTENANCE=1），API 将返回 503")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
