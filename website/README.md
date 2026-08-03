# Memo website feedback MVP

This directory contains the public Memo website and a minimal feedback system.

## Routes

Static pages:

- `/` → `index.html`
- `/feedback` → `feedback.html`
- `/admin/feedback` → `admin-feedback.html`

API:

- `POST /api/feedback` — submit text + up to 3 base64 images
- `GET /api/feedback` — admin list, requires `X-Admin-Token`
- `GET /api/feedback/:id` — admin detail, requires `X-Admin-Token`
- `PATCH /api/feedback/:id` — update status / note, requires `X-Admin-Token`

## Run locally

```powershell
$env:MEMO_WEBSITE_HOST='127.0.0.1'
$env:MEMO_WEBSITE_PORT='9180'
$env:MEMO_FEEDBACK_ADMIN_TOKEN='<change-me>'
python scripts\website_feedback_server.py
```

Open:

- Website: `http://127.0.0.1:9180/`
- Feedback: `http://127.0.0.1:9180/feedback`
- Admin: `http://127.0.0.1:9180/admin/feedback`

## Production notes

Set a strong admin token before exposing the service:

```bash
export MEMO_FEEDBACK_ADMIN_TOKEN='replace-with-a-long-random-token'
export MEMO_WEBSITE_HOST='127.0.0.1'
export MEMO_WEBSITE_PORT='9180'
export MEMO_FEEDBACK_DATA_DIR='/data/memo-feedback'
python /path/to/memo/scripts/website_feedback_server.py
```

Put Nginx in front of the local service, for example:

```nginx
location / {
    proxy_pass http://127.0.0.1:9180;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Feedback data is stored outside the repository by default:

- SQLite DB: `data/website_feedback/feedback.db`
- Uploads: `data/website_feedback/uploads/`

Do not commit the feedback DB or uploads.
