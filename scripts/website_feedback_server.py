#!/usr/bin/env python3
"""Tiny feedback server for memo.zhaguzhagu.com.

Serves the static website and provides a minimal feedback API.
No third-party dependencies: JSON payload + base64 image uploads.

Environment:
  MEMO_WEBSITE_HOST         default 127.0.0.1
  MEMO_WEBSITE_PORT         default 9180
  MEMO_WEBSITE_ROOT         default <repo>/website
  MEMO_FEEDBACK_DATA_DIR    default <repo>/data/website_feedback
  MEMO_FEEDBACK_ADMIN_TOKEN required for admin APIs; default dev-token on localhost only
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
WEBSITE_ROOT = Path(os.getenv("MEMO_WEBSITE_ROOT", ROOT / "website")).resolve()
DATA_DIR = Path(os.getenv("MEMO_FEEDBACK_DATA_DIR", ROOT / "data" / "website_feedback")).resolve()
DB_PATH = DATA_DIR / "feedback.db"
UPLOAD_DIR = DATA_DIR / "uploads"
HOST = os.getenv("MEMO_WEBSITE_HOST", "127.0.0.1")
PORT = int(os.getenv("MEMO_WEBSITE_PORT", "9180"))
ADMIN_TOKEN = os.getenv("MEMO_FEEDBACK_ADMIN_TOKEN", "dev-token")
MAX_BODY = 22 * 1024 * 1024
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_MIME = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
ALLOWED_STATUS = {"new", "processing", "resolved", "closed"}
ALLOWED_TYPE = {
    "install",
    "startup",
    "agent",
    "memory",
    "ui",
    "suggestion",
    "other",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_name(name: str) -> str:
    stem = Path(name or "image").stem[:48] or "image"
    stem = re.sub(r"[^a-zA-Z0-9_.-]+", "-", stem).strip(".-") or "image"
    return stem


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback_items (
              id TEXT PRIMARY KEY,
              type TEXT NOT NULL,
              title TEXT NOT NULL,
              description TEXT NOT NULL,
              contact TEXT,
              status TEXT NOT NULL DEFAULT 'new',
              image_paths_json TEXT NOT NULL DEFAULT '[]',
              admin_note TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback_items(status)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback_items(created_at)")


def row_to_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["image_paths"] = json.loads(item.pop("image_paths_json") or "[]")
    return item


class FeedbackHandler(SimpleHTTPRequestHandler):
    server_version = "MemoFeedback/0.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEBSITE_ROOT), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[%s] %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), fmt % args))

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        super().end_headers()

    def send_json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self) -> dict | None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "empty body"})
            return None
        if length > MAX_BODY:
            self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "payload too large"})
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid json"})
            return None

    def is_admin(self) -> bool:
        token = self.headers.get("X-Admin-Token", "")
        return bool(token) and secrets.compare_digest(token, ADMIN_TOKEN)

    def require_admin(self) -> bool:
        if self.is_admin():
            return True
        self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "admin token required"})
        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/feedback":
            self.path = "/feedback.html"
            return super().do_GET()
        if path in {"/admin/feedback", "/admin"}:
            self.path = "/admin-feedback.html"
            return super().do_GET()
        if path == "/api/feedback":
            return self.handle_feedback_list(parsed)
        if path.startswith("/api/feedback/"):
            return self.handle_feedback_detail(path)
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/feedback":
            return self.handle_feedback_create()
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/feedback/"):
            return self.handle_feedback_update(parsed.path)
        self.send_error(HTTPStatus.NOT_FOUND)

    def handle_feedback_create(self) -> None:
        data = self.read_json()
        if data is None:
            return
        ftype = str(data.get("type") or "other")
        if ftype not in ALLOWED_TYPE:
            ftype = "other"
        title = str(data.get("title") or "").strip()
        description = str(data.get("description") or "").strip()
        contact = str(data.get("contact") or "").strip()[:500]
        if not title or len(title) > 120:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "title required, max 120 chars"})
        if not description or len(description) > 6000:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "description required, max 6000 chars"})
        images = data.get("images") or []
        if not isinstance(images, list) or len(images) > MAX_IMAGES:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"max {MAX_IMAGES} images"})

        fid = secrets.token_hex(8)
        month = datetime.now().strftime("%Y-%m")
        item_dir = UPLOAD_DIR / month / fid
        item_dir.mkdir(parents=True, exist_ok=True)
        saved: list[str] = []
        for idx, image in enumerate(images):
            if not isinstance(image, dict):
                continue
            mime = str(image.get("type") or "").lower()
            if mime == "image/jpg":
                mime = "image/jpeg"
            if mime not in ALLOWED_IMAGE_MIME:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "unsupported image type"})
            raw_data = str(image.get("data") or "")
            if raw_data.startswith("data:"):
                raw_data = raw_data.split(",", 1)[-1]
            try:
                blob = base64.b64decode(raw_data, validate=True)
            except Exception:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid image data"})
            if len(blob) > MAX_IMAGE_BYTES:
                return self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "image too large"})
            ext = ".jpg" if mime == "image/jpeg" else mimetypes.guess_extension(mime) or ".png"
            fname = f"{idx+1:02d}-{safe_name(str(image.get('name') or 'image'))}{ext}"
            dest = item_dir / fname
            dest.write_bytes(blob)
            saved.append(str(dest.relative_to(DATA_DIR)).replace("\\", "/"))

        ts = now_iso()
        with sqlite3.connect(DB_PATH) as con:
            con.execute(
                """
                INSERT INTO feedback_items
                  (id, type, title, description, contact, status, image_paths_json, admin_note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'new', ?, '', ?, ?)
                """,
                (fid, ftype, title, description, contact, json.dumps(saved, ensure_ascii=False), ts, ts),
            )
        return self.send_json(HTTPStatus.CREATED, {"ok": True, "id": fid})

    def handle_feedback_list(self, parsed) -> None:
        if not self.require_admin():
            return
        q = parse_qs(parsed.query)
        status = (q.get("status") or [""])[0]
        params: list[str] = []
        sql = "SELECT * FROM feedback_items"
        if status in ALLOWED_STATUS:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT 200"
        with sqlite3.connect(DB_PATH) as con:
            con.row_factory = sqlite3.Row
            rows = [row_to_dict(r) for r in con.execute(sql, params)]
        for item in rows:
            item["description"] = item["description"][:240]
        return self.send_json(HTTPStatus.OK, {"ok": True, "items": rows})

    def handle_feedback_detail(self, path: str) -> None:
        if not self.require_admin():
            return
        fid = unquote(path.rsplit("/", 1)[-1])
        with sqlite3.connect(DB_PATH) as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM feedback_items WHERE id = ?", (fid,)).fetchone()
        if not row:
            return self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
        item = row_to_dict(row)
        images = []
        for rel in item["image_paths"]:
            p = (DATA_DIR / rel).resolve()
            if DATA_DIR not in p.parents or not p.exists():
                continue
            mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            images.append({"name": p.name, "type": mime, "data": base64.b64encode(p.read_bytes()).decode("ascii")})
        item["images"] = images
        return self.send_json(HTTPStatus.OK, {"ok": True, "item": item})

    def handle_feedback_update(self, path: str) -> None:
        if not self.require_admin():
            return
        fid = unquote(path.rsplit("/", 1)[-1])
        data = self.read_json()
        if data is None:
            return
        status = str(data.get("status") or "").strip()
        admin_note = str(data.get("admin_note") or "")[:4000]
        if status not in ALLOWED_STATUS:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid status"})
        with sqlite3.connect(DB_PATH) as con:
            cur = con.execute(
                "UPDATE feedback_items SET status = ?, admin_note = ?, updated_at = ? WHERE id = ?",
                (status, admin_note, now_iso(), fid),
            )
        if cur.rowcount == 0:
            return self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
        return self.send_json(HTTPStatus.OK, {"ok": True})


def main() -> None:
    if not WEBSITE_ROOT.exists():
        raise SystemExit(f"website root not found: {WEBSITE_ROOT}")
    init_db()
    if ADMIN_TOKEN == "dev-token" and HOST not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Set MEMO_FEEDBACK_ADMIN_TOKEN before binding to a public host")
    httpd = ThreadingHTTPServer((HOST, PORT), FeedbackHandler)
    print(f"Memo feedback server: http://{HOST}:{PORT}  root={WEBSITE_ROOT}  data={DATA_DIR}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
