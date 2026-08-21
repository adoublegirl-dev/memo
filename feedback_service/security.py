from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

from .config import IP_HASH_SECRET, SESSION_SECRET, SESSION_SECONDS

CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]")


def clean_text(value: str, *, min_chars: int, max_chars: int, field: str, multiline: bool = False) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = CONTROL_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    if not multiline:
        text = " ".join(text.split())
    else:
        text = "\n".join(line.rstrip() for line in text.split("\n")).strip()
    if len(text) < min_chars or len(text) > max_chars:
        raise HTTPException(422, f"{field}长度必须在 {min_chars}～{max_chars} 个字符之间")
    return text


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:80]
    return (request.client.host if request.client else "unknown")[:80]


def hash_ip(value: str) -> str:
    return hmac.new(IP_HASH_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def hash_password(password: str, iterations: int = 240_000) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text)
        expected = base64.urlsafe_b64decode(digest_text)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hmac.new(SESSION_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()


def create_session(username: str) -> tuple[str, str]:
    from .database import create_admin_session

    token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS)
    create_admin_session(_token_hash(token), username, csrf, expires.isoformat(timespec="seconds"))
    return token, csrf


def read_session(request: Request) -> dict:
    from .database import get_admin_session

    token = request.cookies.get("__Host-memo_feedback_admin", "")
    if not token:
        raise HTTPException(401, "管理员登录已失效")
    session = get_admin_session(_token_hash(token))
    if not session:
        raise HTTPException(401, "管理员登录已失效")
    return {"sub": session["username"], "csrf": session["csrf"], "token_hash": _token_hash(token)}


def revoke_session(request: Request) -> None:
    from .database import revoke_admin_session

    token = request.cookies.get("__Host-memo_feedback_admin", "")
    if token:
        revoke_admin_session(_token_hash(token))


def require_csrf(request: Request, session: dict) -> None:
    supplied = request.headers.get("x-csrf-token", "")
    if not supplied or not hmac.compare_digest(supplied, str(session.get("csrf", ""))):
        raise HTTPException(403, "CSRF校验失败")
