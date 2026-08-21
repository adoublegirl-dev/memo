from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("FEEDBACK_DATA_DIR", BASE_DIR / "data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "feedback.db"
STATIC_DIR = BASE_DIR / "static"

ADMIN_USERNAME = os.getenv("FEEDBACK_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.getenv("FEEDBACK_ADMIN_PASSWORD_HASH", "")
SESSION_SECRET = os.getenv("FEEDBACK_SESSION_SECRET", "development-only-change-me")
IP_HASH_SECRET = os.getenv("FEEDBACK_IP_HASH_SECRET", SESSION_SECRET)
COOKIE_SECURE = os.getenv("FEEDBACK_COOKIE_SECURE", "1") != "0"

MAX_TITLE_CHARS = 80
MIN_TITLE_CHARS = 5
MAX_CONTENT_CHARS = 2000
MIN_CONTENT_CHARS = 20
MAX_CONTACT_CHARS = 100
MAX_VERSION_CHARS = 40
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_EDGE = 2560
SESSION_SECONDS = 12 * 60 * 60

CATEGORIES = {"usage", "install", "feature", "data", "mcp", "other"}
STATUSES = {"pending", "processing", "resolved", "closed"}
OS_OPTIONS = {"windows-10", "windows-11", "other", ""}
ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}

if os.getenv("FEEDBACK_ALLOW_INSECURE_DEV", "0") != "1":
    if not ADMIN_PASSWORD_HASH:
        raise RuntimeError("FEEDBACK_ADMIN_PASSWORD_HASH is required")
    if SESSION_SECRET == "development-only-change-me" or len(SESSION_SECRET) < 32:
        raise RuntimeError("FEEDBACK_SESSION_SECRET must be a random value of at least 32 characters")
    if IP_HASH_SECRET == SESSION_SECRET or len(IP_HASH_SECRET) < 32:
        raise RuntimeError("FEEDBACK_IP_HASH_SECRET must be independent and at least 32 characters")
