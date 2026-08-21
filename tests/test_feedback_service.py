import io
import os
import sqlite3

os.environ["FEEDBACK_ALLOW_INSECURE_DEV"] = "1"

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from feedback_service import app as app_module
from feedback_service import database
from feedback_service.security import hash_password


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data = tmp_path / "data"
    uploads = data / "uploads"
    monkeypatch.setattr(database, "DATA_DIR", data)
    monkeypatch.setattr(database, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(database, "DB_PATH", data / "feedback.db")
    monkeypatch.setattr(app_module, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(app_module, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(app_module, "ADMIN_PASSWORD_HASH", hash_password("safe-password"))
    monkeypatch.setattr(app_module, "COOKIE_SECURE", False)
    with TestClient(app_module.app) as test_client:
        yield test_client, database.DB_PATH, uploads


def valid_form(**overrides):
    data = {
        "category": "usage",
        "title": "启动器无法打开页面",
        "content": "点击启动器中的打开按钮后没有反应，希望能够显示明确的错误信息。",
        "contact": "tester@example.com",
        "memo_version": "0.10.1-alpha",
        "os_name": "windows-11",
        "privacy_confirmed": "1",
        "website": "",
    }
    data.update(overrides)
    return data


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (80, 60), (25, 120, 90)).save(output, format="PNG")
    return output.getvalue()


def test_parameterized_insert_preserves_sql_injection_text_and_schema(client):
    http, db_path, _ = client
    payload = "正常描述'); DROP TABLE feedback; -- 这段文本应该被当作普通反馈内容保存。"
    response = http.post("/api/feedback", data=valid_form(content=payload))
    assert response.status_code == 200
    with sqlite3.connect(db_path) as conn:
        stored = conn.execute("SELECT content FROM feedback").fetchone()[0]
        table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='feedback'").fetchone()
    assert stored == payload
    assert table == ("feedback",)


def test_honeypot_and_length_validation(client):
    http, _, _ = client
    assert http.post("/api/feedback", data=valid_form(website="spam.example")).status_code == 400
    assert http.post("/api/feedback", data=valid_form(title="短")).status_code == 422


def test_image_is_verified_and_reencoded_as_webp(client):
    http, _, uploads = client
    response = http.post(
        "/api/feedback",
        data=valid_form(),
        files=[("images", ("screen.png", png_bytes(), "image/png"))],
    )
    assert response.status_code == 200
    saved = list(uploads.glob("*.webp"))
    assert len(saved) == 1
    with Image.open(saved[0]) as image:
        assert image.format == "WEBP"
        assert image.size == (80, 60)


def test_fake_image_is_rejected(client):
    http, _, _ = client
    response = http.post(
        "/api/feedback",
        data=valid_form(),
        files=[("images", ("fake.png", b"<script>alert(1)</script>", "image/png"))],
    )
    assert response.status_code == 422


def test_admin_login_requires_csrf_for_update_and_returns_safe_detail(client):
    http, _, _ = client
    created = http.post("/api/feedback", data=valid_form()).json()
    assert created["feedbackNo"].startswith("MEMO-")
    login = http.post("/api/admin/login", json={"username": "admin", "password": "safe-password"})
    assert login.status_code == 200
    csrf = login.json()["csrfToken"]
    listing = http.get("/api/admin/feedback")
    feedback_id = listing.json()["items"][0]["id"]
    blocked = http.patch(f"/api/admin/feedback/{feedback_id}", json={"status": "resolved", "admin_note": "fixed"})
    assert blocked.status_code == 403
    updated = http.patch(
        f"/api/admin/feedback/{feedback_id}",
        json={"status": "resolved", "admin_note": "已在新版本修复"},
        headers={"X-CSRF-Token": csrf},
    )
    assert updated.status_code == 200
    detail = http.get(f"/api/admin/feedback/{feedback_id}").json()
    assert detail["status"] == "resolved"
    assert detail["admin_note"] == "已在新版本修复"
    deleted = http.delete(f"/api/admin/feedback/{feedback_id}", headers={"X-CSRF-Token": csrf})
    assert deleted.status_code == 200
    assert http.get("/api/admin/feedback").json()["total"] == 0
