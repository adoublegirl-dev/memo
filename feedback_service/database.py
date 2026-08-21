from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .config import DB_PATH, DATA_DIR, UPLOAD_DIR

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  feedback_no TEXT UNIQUE,
  category TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  contact TEXT NOT NULL DEFAULT '',
  memo_version TEXT NOT NULL DEFAULT '',
  os_name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  admin_note TEXT NOT NULL DEFAULT '',
  ip_hash TEXT NOT NULL,
  user_agent TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_status_created ON feedback(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_category_created ON feedback(category, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_ip_created ON feedback(ip_hash, created_at DESC);
CREATE TABLE IF NOT EXISTS feedback_images (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
  stored_name TEXT NOT NULL UNIQUE,
  original_name TEXT NOT NULL DEFAULT '',
  mime_type TEXT NOT NULL,
  file_size INTEGER NOT NULL,
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_images_feedback ON feedback_images(feedback_id);
CREATE TABLE IF NOT EXISTS admin_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  feedback_id INTEGER REFERENCES feedback(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  admin_username TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_login_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ip_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_login_ip_created ON admin_login_attempts(ip_hash, created_at DESC);
CREATE TABLE IF NOT EXISTS admin_sessions (
  token_hash TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  csrf TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires ON admin_sessions(expires_at);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA journal_mode=WAL")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def insert_feedback(*, category: str, title: str, content: str, contact: str, memo_version: str, os_name: str, ip_hash: str, user_agent: str) -> tuple[int, str]:
    created = now_iso()
    with connect() as conn:
        cursor = conn.execute(
            """INSERT INTO feedback(category,title,content,contact,memo_version,os_name,status,ip_hash,user_agent,created_at,updated_at)
               VALUES(?,?,?,?,?,?,'pending',?,?,?,?)""",
            (category, title, content, contact, memo_version, os_name, ip_hash, user_agent, created, created),
        )
        feedback_id = int(cursor.lastrowid)
        feedback_no = f"MEMO-{datetime.now():%Y%m%d}-{feedback_id:06d}"
        conn.execute("UPDATE feedback SET feedback_no=? WHERE id=?", (feedback_no, feedback_id))
    return feedback_id, feedback_no


def insert_image(*, feedback_id: int, stored_name: str, original_name: str, mime_type: str, file_size: int, width: int, height: int) -> int:
    with connect() as conn:
        cursor = conn.execute(
            """INSERT INTO feedback_images(feedback_id,stored_name,original_name,mime_type,file_size,width,height,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (feedback_id, stored_name, original_name, mime_type, file_size, width, height, now_iso()),
        )
        return int(cursor.lastrowid)


def delete_images_for_feedback(feedback_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM feedback_images WHERE feedback_id=?", (feedback_id,))


def count_recent_by_ip(ip_hash: str, since_iso: str) -> int:
    with connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM feedback WHERE ip_hash=? AND created_at>=?", (ip_hash, since_iso)).fetchone()
        return int(row["total"])


def list_feedback(*, status: str = "", category: str = "", query: str = "", limit: int = 50, offset: int = 0) -> dict:
    clauses: list[str] = []
    values: list[object] = []
    if status:
        clauses.append("status=?")
        values.append(status)
    if category:
        clauses.append("category=?")
        values.append(category)
    if query:
        clauses.append("(feedback_no LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')")
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped}%"
        values.extend((term, term, term))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        total = int(conn.execute(f"SELECT COUNT(*) AS total FROM feedback{where}", values).fetchone()["total"])
        rows = conn.execute(
            f"""SELECT f.*, (SELECT COUNT(*) FROM feedback_images i WHERE i.feedback_id=f.id) AS image_count
                 FROM feedback f{where} ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (*values, limit, offset),
        ).fetchall()
    return {"total": total, "items": [dict(row) for row in rows]}


def get_feedback(feedback_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM feedback WHERE id=?", (feedback_id,)).fetchone()
        if not row:
            return None
        images = conn.execute("SELECT id,original_name,mime_type,file_size,width,height,created_at FROM feedback_images WHERE feedback_id=? ORDER BY id", (feedback_id,)).fetchall()
    result = dict(row)
    result["images"] = [dict(image) for image in images]
    return result


def get_image(image_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM feedback_images WHERE id=?", (image_id,)).fetchone()
    return dict(row) if row else None


def record_login_attempt(ip_hash: str, cutoff_iso: str) -> int:
    with connect() as conn:
        conn.execute("DELETE FROM admin_login_attempts WHERE created_at<?", (cutoff_iso,))
        conn.execute("INSERT INTO admin_login_attempts(ip_hash,created_at) VALUES(?,?)", (ip_hash, now_iso()))
        return int(conn.execute("SELECT COUNT(*) AS total FROM admin_login_attempts WHERE ip_hash=? AND created_at>=?", (ip_hash, cutoff_iso)).fetchone()["total"])


def create_admin_session(token_hash: str, username: str, csrf: str, expires_at: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE expires_at<? OR revoked=1", (now_iso(),))
        conn.execute("INSERT INTO admin_sessions(token_hash,username,csrf,expires_at,created_at) VALUES(?,?,?,?,?)", (token_hash, username, csrf, expires_at, now_iso()))


def get_admin_session(token_hash: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT username,csrf,expires_at FROM admin_sessions WHERE token_hash=? AND revoked=0 AND expires_at>=?", (token_hash, now_iso())).fetchone()
    return dict(row) if row else None


def revoke_admin_session(token_hash: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE admin_sessions SET revoked=1 WHERE token_hash=?", (token_hash,))


def delete_feedback(feedback_id: int, *, admin_username: str) -> list[str] | None:
    with connect() as conn:
        row = conn.execute("SELECT feedback_no FROM feedback WHERE id=?", (feedback_id,)).fetchone()
        if not row:
            return None
        images = [item["stored_name"] for item in conn.execute("SELECT stored_name FROM feedback_images WHERE feedback_id=?", (feedback_id,)).fetchall()]
        conn.execute("INSERT INTO admin_logs(feedback_id,action,detail,admin_username,created_at) VALUES(?,?,?,?,?)", (feedback_id, "delete", f"deleted:{row['feedback_no']}", admin_username, now_iso()))
        conn.execute("DELETE FROM feedback WHERE id=?", (feedback_id,))
    return images


def update_feedback(feedback_id: int, *, status: str, admin_note: str, admin_username: str) -> bool:
    with connect() as conn:
        previous = conn.execute("SELECT status,admin_note FROM feedback WHERE id=?", (feedback_id,)).fetchone()
        if not previous:
            return False
        conn.execute("UPDATE feedback SET status=?,admin_note=?,updated_at=? WHERE id=?", (status, admin_note, now_iso(), feedback_id))
        detail = f"status:{previous['status']}->{status}; note_changed:{previous['admin_note'] != admin_note}"
        conn.execute("INSERT INTO admin_logs(feedback_id,action,detail,admin_username,created_at) VALUES(?,?,?,?,?)", (feedback_id, "update", detail, admin_username, now_iso()))
    return True
