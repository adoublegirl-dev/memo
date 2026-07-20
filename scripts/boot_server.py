"""Instant Memo boot page on 9120, proxying to the dashboard after it is ready."""
from __future__ import annotations

import http.client
import json
import mimetypes
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BOOT_PORT = int(os.getenv("MEMO_BOOT_PORT", "9120"))
TARGET_HOST = os.getenv("MEMO_DASHBOARD_TARGET_HOST", "127.0.0.1")
TARGET_PORT = int(os.getenv("MEMO_DASHBOARD_TARGET_PORT", "9121"))
ASSET_DIR = Path(__file__).with_name("boot_assets")
STARTED_AT = time.time()


def dashboard_ready(timeout: float = 0.6) -> bool:
    try:
        conn = http.client.HTTPConnection(TARGET_HOST, TARGET_PORT, timeout=timeout)
        conn.request("GET", "/api/health")
        response = conn.getresponse()
        ready = 200 <= response.status < 300
        response.read()
        conn.close()
        return ready
    except Exception:
        return False


class BootHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        return

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/boot-health":
            self._json({"ready": dashboard_ready(), "elapsed": round(time.time() - STARTED_AT, 2)})
            return
        if path.startswith("/boot-assets/"):
            self._asset(path.removeprefix("/boot-assets/"))
            return
        if dashboard_ready():
            self._proxy()
            return
        self._asset("index.html")

    def do_POST(self):
        if dashboard_ready():
            self._proxy()
        else:
            self._json({"error": "dashboard is still starting"}, 503)

    def _asset(self, relative: str):
        target = (ASSET_DIR / relative).resolve()
        try:
            target.relative_to(ASSET_DIR.resolve())
            data = target.read_bytes()
        except (ValueError, OSError):
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith(("text/", "application/javascript")) else content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: dict, status: int = 200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _proxy(self):
        body = None
        if self.command in {"POST", "PUT", "PATCH"}:
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length) if length else None
        try:
            conn = http.client.HTTPConnection(TARGET_HOST, TARGET_PORT, timeout=12)
            headers = {key: value for key, value in self.headers.items() if key.lower() not in {"host", "connection", "content-length"}}
            conn.request(self.command, self.path, body=body, headers=headers)
            response = conn.getresponse()
            data = response.read()
            self.send_response(response.status, response.reason)
            skipped = {"transfer-encoding", "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "upgrade", "content-length"}
            for key, value in response.getheaders():
                if key.lower() not in skipped:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            conn.close()
        except Exception as exc:
            self._json({"error": f"proxy failed: {exc}"}, 502)


def main() -> int:
    server = ThreadingHTTPServer(("0.0.0.0", BOOT_PORT), BootHandler)
    print(f"Memo Boot Server -> http://localhost:{BOOT_PORT}; target {TARGET_HOST}:{TARGET_PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
