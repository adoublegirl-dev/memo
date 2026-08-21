from __future__ import annotations

import io
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from .config import (
    ADMIN_PASSWORD_HASH,
    ADMIN_USERNAME,
    ALLOWED_IMAGE_FORMATS,
    ALLOWED_IMAGE_MIME,
    CATEGORIES,
    COOKIE_SECURE,
    MAX_CONTACT_CHARS,
    MAX_CONTENT_CHARS,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_EDGE,
    MAX_IMAGE_PIXELS,
    MAX_IMAGES,
    MAX_TITLE_CHARS,
    MAX_TOTAL_IMAGE_BYTES,
    MAX_VERSION_CHARS,
    MIN_CONTENT_CHARS,
    MIN_TITLE_CHARS,
    OS_OPTIONS,
    SESSION_SECONDS,
    STATUSES,
    STATIC_DIR,
    UPLOAD_DIR,
)
from .database import count_recent_by_ip, delete_feedback, delete_images_for_feedback, get_feedback, get_image, init_db, insert_feedback, insert_image, list_feedback, record_login_attempt, update_feedback
from .security import clean_text, client_ip, create_session, hash_ip, read_session, require_csrf, revoke_session, verify_password

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Memo Feedback", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/feedback-admin-static", StaticFiles(directory=STATIC_DIR), name="feedback-admin-static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
    if request.url.path.startswith("/admin/") or request.url.path.startswith("/api/admin/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class LoginBody(BaseModel):
    username: str = Field(max_length=80)
    password: str = Field(max_length=200)


class UpdateBody(BaseModel):
    status: str = Field(max_length=20)
    admin_note: str = Field(default="", max_length=4000)


def validate_choice(value: str, allowed: set[str], field: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise HTTPException(422, f"{field}无效")
    return normalized


def enforce_feedback_rate(ip_digest: str) -> None:
    now = datetime.now(timezone.utc)
    if count_recent_by_ip(ip_digest, (now - timedelta(minutes=10)).isoformat(timespec="seconds")) >= 3:
        raise HTTPException(429, "提交过于频繁，请10分钟后再试")
    if count_recent_by_ip(ip_digest, (now - timedelta(days=1)).isoformat(timespec="seconds")) >= 10:
        raise HTTPException(429, "今日提交次数已达上限")


def enforce_login_rate(ip_digest: str) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(timespec="seconds")
    if record_login_attempt(ip_digest, cutoff) > 8:
        raise HTTPException(429, "登录尝试过多，请15分钟后再试")


async def prepare_image(upload: UploadFile) -> dict:
    declared = (upload.content_type or "").lower()
    if declared not in ALLOWED_IMAGE_MIME:
        raise HTTPException(422, "图片仅支持 JPG、PNG、WebP")
    raw = await upload.read(MAX_IMAGE_BYTES + 1)
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "单张图片不能超过5MB")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            image_format = str(probe.format or "").upper()
            width, height = probe.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise HTTPException(422, "图片尺寸过大")
            probe.verify()
        if image_format not in ALLOWED_IMAGE_FORMATS:
            raise HTTPException(422, "图片真实格式不受支持")
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            width, height = image.size
            if max(width, height) > MAX_IMAGE_EDGE:
                ratio = MAX_IMAGE_EDGE / max(width, height)
                image = image.resize((max(1, int(width * ratio)), max(1, int(height * ratio))), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=86, method=6)
            encoded = output.getvalue()
            width, height = image.size
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "图片文件损坏或格式伪造") from exc
    return {
        "bytes": encoded,
        "raw_size": len(raw),
        "original_name": Path((upload.filename or "image").replace("\\", "/")).name[:160],
        "mime_type": "image/webp",
        "width": width,
        "height": height,
    }


@app.get("/health")
def health():
    return {"ok": True, "service": "memo-feedback"}


@app.post("/api/feedback")
async def create_feedback(
    request: Request,
    category: str = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    contact: str = Form(""),
    memo_version: str = Form(""),
    os_name: str = Form(""),
    privacy_confirmed: str = Form(""),
    website: str = Form(""),
    images: list[UploadFile] = File(default=[]),
):
    if website.strip():
        raise HTTPException(400, "提交无效")
    if privacy_confirmed.lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(422, "请确认反馈中不包含密码或API Key")
    category = validate_choice(category, CATEGORIES, "反馈类型")
    os_name = validate_choice(os_name, OS_OPTIONS, "操作系统")
    title = clean_text(title, min_chars=MIN_TITLE_CHARS, max_chars=MAX_TITLE_CHARS, field="标题")
    content = clean_text(content, min_chars=MIN_CONTENT_CHARS, max_chars=MAX_CONTENT_CHARS, field="详细描述", multiline=True)
    contact = clean_text(contact, min_chars=0, max_chars=MAX_CONTACT_CHARS, field="联系方式")
    memo_version = clean_text(memo_version, min_chars=0, max_chars=MAX_VERSION_CHARS, field="Memo版本")
    if len(images) > MAX_IMAGES:
        raise HTTPException(413, "最多上传3张图片")
    ip_digest = hash_ip(client_ip(request))
    enforce_feedback_rate(ip_digest)

    prepared: list[dict] = []
    raw_total = 0
    for upload in images:
        item = await prepare_image(upload)
        raw_total += int(item["raw_size"])
        if raw_total > MAX_TOTAL_IMAGE_BYTES:
            raise HTTPException(413, "图片总大小不能超过10MB")
        prepared.append(item)

    feedback_id, feedback_no = insert_feedback(
        category=category,
        title=title,
        content=content,
        contact=contact,
        memo_version=memo_version,
        os_name=os_name,
        ip_hash=ip_digest,
        user_agent=request.headers.get("user-agent", "")[:500],
    )
    written: list[Path] = []
    try:
        for item in prepared:
            stored_name = f"{feedback_id}-{secrets.token_hex(16)}.webp"
            target = UPLOAD_DIR / stored_name
            target.write_bytes(item["bytes"])
            written.append(target)
            insert_image(
                feedback_id=feedback_id,
                stored_name=stored_name,
                original_name=item["original_name"],
                mime_type=item["mime_type"],
                file_size=len(item["bytes"]),
                width=item["width"],
                height=item["height"],
            )
    except Exception:
        for target in written:
            target.unlink(missing_ok=True)
        delete_images_for_feedback(feedback_id)
        raise HTTPException(500, "图片保存失败，反馈文字已记录，请勿重复提交")
    return {"ok": True, "feedbackNo": feedback_no}


@app.get("/admin/feedback")
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")


@app.post("/api/admin/login")
def admin_login(body: LoginBody, request: Request, response: Response):
    ip_digest = hash_ip(client_ip(request))
    enforce_login_rate(ip_digest)
    if not ADMIN_PASSWORD_HASH or body.username != ADMIN_USERNAME or not verify_password(body.password, ADMIN_PASSWORD_HASH):
        raise HTTPException(401, "用户名或密码错误")
    token, csrf = create_session(ADMIN_USERNAME)
    response.set_cookie("__Host-memo_feedback_admin", token, max_age=SESSION_SECONDS, httponly=True, secure=COOKIE_SECURE, samesite="strict", path="/")
    return {"ok": True, "username": ADMIN_USERNAME, "csrfToken": csrf}


@app.get("/api/admin/session")
def admin_session(request: Request):
    session = read_session(request)
    return {"ok": True, "username": session["sub"], "csrfToken": session["csrf"]}


@app.post("/api/admin/logout")
def admin_logout(request: Request, response: Response):
    session = read_session(request)
    require_csrf(request, session)
    revoke_session(request)
    response.delete_cookie("__Host-memo_feedback_admin", path="/")
    return {"ok": True}


@app.get("/api/admin/feedback")
def admin_feedback_list(request: Request, status: str = "", category: str = "", q: str = "", limit: int = 50, offset: int = 0):
    read_session(request)
    if status:
        status = validate_choice(status, STATUSES, "状态")
    if category:
        category = validate_choice(category, CATEGORIES, "类型")
    query = clean_text(q, min_chars=0, max_chars=100, field="搜索词")
    return list_feedback(status=status, category=category, query=query, limit=max(1, min(limit, 100)), offset=max(0, offset))


@app.get("/api/admin/feedback/{feedback_id}")
def admin_feedback_detail(feedback_id: int, request: Request):
    read_session(request)
    item = get_feedback(feedback_id)
    if not item:
        raise HTTPException(404, "反馈不存在")
    return item


@app.patch("/api/admin/feedback/{feedback_id}")
def admin_feedback_update(feedback_id: int, body: UpdateBody, request: Request):
    session = read_session(request)
    require_csrf(request, session)
    status = validate_choice(body.status, STATUSES, "状态")
    note = clean_text(body.admin_note, min_chars=0, max_chars=4000, field="管理员备注", multiline=True)
    if not update_feedback(feedback_id, status=status, admin_note=note, admin_username=session["sub"]):
        raise HTTPException(404, "反馈不存在")
    return {"ok": True}


@app.delete("/api/admin/feedback/{feedback_id}")
def admin_feedback_delete(feedback_id: int, request: Request):
    session = read_session(request)
    require_csrf(request, session)
    images = delete_feedback(feedback_id, admin_username=session["sub"])
    if images is None:
        raise HTTPException(404, "反馈不存在")
    for stored_name in images:
        (UPLOAD_DIR / stored_name).unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/admin/images/{image_id}")
def admin_image(image_id: int, request: Request):
    read_session(request)
    image = get_image(image_id)
    if not image:
        raise HTTPException(404, "图片不存在")
    target = UPLOAD_DIR / image["stored_name"]
    if not target.is_file():
        raise HTTPException(404, "图片文件不存在")
    return FileResponse(target, media_type=image["mime_type"], headers={"Cache-Control": "private, max-age=300"})


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse({"ok": False, "error": str(exc.detail)}, status_code=exc.status_code)
