"""Build an explicitly non-publishable Memo release draft for offline signing.

The output intentionally contains no signature. It must be signed by the
repository-external Ed25519 signer before deploy_memo_site.py will accept it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_release_manifest import asset, delta_asset


def build_draft(
    full: Path,
    lite: Path,
    service_zip: Path,
    launcher_version: str,
    service_version: str,
    base_url: str,
    output: Path,
    patches: list[Path] | None = None,
) -> dict:
    if "DO_NOT_PUBLISH" not in output.name:
        raise RuntimeError("Unsigned draft filename must contain DO_NOT_PUBLISH")
    full_asset = asset(full, base_url)
    lite_asset = asset(lite, base_url)
    service_asset = asset(service_zip, f"{base_url.rstrip('/')}/service")
    patch_assets = sorted(
        (delta_asset(path, base_url) for path in (patches or [])),
        key=lambda row: (row["from"], row["to"]),
    )
    manifest = {
        "formatVersion": 2,
        "version": launcher_version,
        "serviceVersion": service_version,
        "launcher": {
            "version": launcher_version,
            "full": full_asset,
            "lite": lite_asset,
        },
        "service": {
            "version": service_version,
            "runtimeChanged": False,
            **service_asset,
            "full": service_asset,
            "patches": patch_assets,
        },
        "full": full_asset,
        "lite": lite_asset,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", required=True)
    parser.add_argument("--lite", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--launcher-version", required=True)
    parser.add_argument("--service-version", required=True)
    parser.add_argument("--patch", action="append", default=[])
    parser.add_argument("--base-url", default="https://memo.zhaguzhagu.com/downloads")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    build_draft(
        Path(args.full),
        Path(args.lite),
        Path(args.service),
        args.launcher_version,
        args.service_version,
        args.base_url,
        Path(args.output),
        patches=[Path(value) for value in args.patch],
    )
    print(f"Unsigned release draft ready: {args.output} (DO NOT PUBLISH)")


if __name__ == "__main__":
    main()
