"""Wait for Memo boot page and dashboard health endpoints with bounded retries."""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "data" / "logs"


def fetch_json(url: str, timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def log_tail(name: str, lines: int = 18) -> str:
    try:
        content = (LOG_DIR / name).read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(content[-lines:])
    except OSError:
        return ""


def wait_ready(timeout: int) -> dict:
    deadline = time.monotonic() + timeout
    last_boot = None
    last_dashboard = None
    while time.monotonic() < deadline:
        last_boot = fetch_json("http://127.0.0.1:9120/boot-health")
        last_dashboard = fetch_json("http://127.0.0.1:9121/api/health")
        # Boot page availability proves the user will see the loading page instead of
        # a browser connection error; dashboard health proves the real application is ready.
        if last_boot is not None and last_dashboard and last_dashboard.get("ok"):
            return {"ok": True, "boot": last_boot, "dashboard": last_dashboard}
        time.sleep(0.5)
    return {
        "ok": False,
        "message": "Memo 服务未在限定时间内就绪。",
        "boot": last_boot,
        "dashboard": last_dashboard,
        "logs": {
            "boot_error_tail": log_tail("boot.err.log"),
            "dashboard_error_tail": log_tail("dashboard.err.log"),
            "dashboard_output_tail": log_tail("dashboard.out.log"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()
    result = wait_ready(max(5, args.timeout))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
