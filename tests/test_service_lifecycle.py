import os
import subprocess
from pathlib import Path

import pytest

from scripts.wait_for_services import wait_ready


ROOT = Path(__file__).resolve().parent.parent


def run_bat(name: str, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["MEMO_ENV"] = "production"
    # start_all spawns long-lived child Python services. Do not capture its pipes:
    # inherited stdout/stderr handles would otherwise keep subprocess.run waiting.
    return subprocess.run(
        ["cmd.exe", "/c", str(ROOT / name), *args],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=45,
    )


@pytest.mark.skipif(os.getenv("MEMO_RUN_E2E") != "1", reason="requires exclusive local ports 9120/9121")
def test_service_stop_start_restart_lifecycle():
    stopped = run_bat("stop_all.bat")
    assert stopped.returncode == 0

    first_start = run_bat("start_all.bat", "--no-browser")
    assert first_start.returncode == 0
    first_ready = wait_ready(60)
    assert first_ready["ok"], first_ready

    stopped_again = run_bat("stop_all.bat")
    assert stopped_again.returncode == 0

    second_start = run_bat("start_all.bat", "--no-browser")
    assert second_start.returncode == 0
    second_ready = wait_ready(60)
    assert second_ready["ok"], second_ready
