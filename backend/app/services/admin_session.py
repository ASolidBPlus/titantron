import hmac
import secrets
import time

from app.config import get_setting

# In-memory session store: {token: expiry_timestamp}
_sessions: dict[str, float] = {}
SESSION_TTL = 86400 * 7  # 7 days
COOKIE_NAME = "titantron_admin"


def is_password_required() -> bool:
    return bool(get_setting("admin_password"))


def verify_password(password: str) -> bool:
    return hmac.compare_digest(password, get_setting("admin_password"))


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_TTL
    return token


def validate_session(token: str) -> bool:
    expiry = _sessions.get(token)
    if not expiry:
        return False
    if time.time() > expiry:
        _sessions.pop(token, None)
        return False
    return True


def delete_session(token: str) -> None:
    _sessions.pop(token, None)


def invalidate_all_sessions() -> None:
    _sessions.clear()
