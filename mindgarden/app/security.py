"""安全模块：密码哈希、会话令牌、登录限流。仅使用标准库。"""
import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta

PBKDF2_ITERATIONS = 260_000
SESSION_DAYS = 7


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2${}${}${}".format(PBKDF2_ITERATIONS, salt.hex(), digest.hex())


def verify_password(password, stored):
    try:
        scheme, iterations, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"),
            bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


def new_session_token():
    return secrets.token_urlsafe(32)


def session_expiry():
    return (datetime.now() + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")


class RateLimiter:
    """简单的内存滑动窗口限流：防止登录/注册被暴力尝试。"""

    def __init__(self, max_attempts=10, window_seconds=300):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._hits = {}
        self._lock = threading.Lock()

    def allow(self, key):
        now = time.time()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(hits) >= self.max_attempts:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            # 防止字典无限增长
            if len(self._hits) > 10000:
                self._hits = {k: v for k, v in self._hits.items() if v}
            return True
