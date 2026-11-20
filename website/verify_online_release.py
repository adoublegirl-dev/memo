"""Verify the public Memo release after the atomic latest.json switch."""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://memo.zhaguzhagu.com/downloads"
LOCAL_MANIFEST = Path(__file__).resolve().parent / "downloads" / "latest.json"


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "MemoReleaseVerifier/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"GET {url} returned HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def head_size(url: str) -> int:
    request = urllib.request.Request(url, method="HEAD", headers={"Cache-Control": "no-cache", "User-Agent": "MemoReleaseVerifier/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"HEAD {url} returned HTTP {response.status}")
        return int(response.headers.get("Content-Length") or 0)


def main() -> int:
    local = json.loads(LOCAL_MANIFEST.read_text(encoding="utf-8"))
    online = fetch_json(f"{BASE}/latest.json?release_check={int(time.time())}")
    if online != local:
        raise RuntimeError("Public latest.json differs from the locally signed manifest")
    assets = [online["launcher"]["full"], online["launcher"]["lite"], online["service"]["full"]]
    assets.extend(online["service"].get("patches") or [])
    for item in assets:
        actual = head_size(item["url"])
        expected = int(item["size"])
        if actual != expected:
            raise RuntimeError(f"Public asset size mismatch: {item['name']} ({actual} != {expected})")
        print(f"PUBLIC_OK {item['name']} {actual}")
    for alias in ("Memo-Setup-latest.exe", "Memo-Lite-Setup-latest.exe"):
        if head_size(f"{BASE}/{alias}") <= 0:
            raise RuntimeError(f"Public alias is unavailable: {alias}")
        print(f"PUBLIC_OK {alias}")
    print(f"ONLINE_RELEASE_OK launcher={online['version']} service={online['serviceVersion']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ONLINE_RELEASE_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
