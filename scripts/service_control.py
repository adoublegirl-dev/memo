"""Small, bounded process controller for Memo local services on Windows.

Avoids WMI/CIM queries, which can hang on some desktops. It only stops processes
recorded by Memo PID files or currently listening on Memo's two local ports.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.getenv("MEMO_DATA_ROOT") or (PROJECT_ROOT / "data"))
PID_DIR = Path(os.getenv("MEMO_PID_DIR") or (DATA_ROOT / "pids"))
PORTS = (9120, 9121)
SERVICE_NAMES = ("boot", "dashboard", "watcher")


def listener_pids(netstat_text: str, ports: tuple[int, ...] = PORTS) -> set[int]:
    result: set[int] = set()
    for line in netstat_text.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0].upper() != "TCP" or fields[3].upper() != "LISTENING":
            continue
        local = fields[1]
        if not any(local.endswith(f":{port}") for port in ports):
            continue
        try:
            result.add(int(fields[-1]))
        except ValueError:
            pass
    return result


def live_listener_pids() -> set[int]:
    run = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=12)
    return listener_pids(run.stdout)


def recorded_pids(pid_dir: Path = PID_DIR) -> set[int]:
    found: set[int] = set()
    for name in SERVICE_NAMES:
        file = pid_dir / f"{name}.pid"
        try:
            raw = file.read_text(encoding="ascii", errors="ignore").strip()
            if raw.isdigit():
                found.add(int(raw))
        except OSError:
            pass
    return found


def kill_pid(pid: int) -> bool:
    """Terminate only the recorded/listening process without shelling out to taskkill.

    Windows taskkill /T can block when a process tree contains a stalled child;
    os.kill maps to TerminateProcess here and returns immediately.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 9)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def stop_services(pid_dir: Path = PID_DIR) -> dict:
    targets = recorded_pids(pid_dir) | live_listener_pids()
    stopped = [pid for pid in sorted(targets) if kill_pid(pid)]
    deadline = time.monotonic() + 12
    remaining = live_listener_pids()
    while remaining and time.monotonic() < deadline:
        time.sleep(0.4)
        remaining = live_listener_pids()
    for name in SERVICE_NAMES:
        try:
            (pid_dir / f"{name}.pid").unlink(missing_ok=True)
        except OSError:
            pass
    return {"ok": not remaining, "targets": sorted(targets), "stopped": stopped, "remaining_listener_pids": sorted(remaining)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    if not args.stop:
        parser.error("pass --stop")
    try:
        result = stop_services()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
