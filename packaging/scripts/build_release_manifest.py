"""Generate the additive v2 release manifest without publishing it.

Legacy version/full/lite fields remain so old clients continue to work. New
clients compare launcher.version and service.version independently.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_manifest_bytes(manifest: dict) -> bytes:
    def validate(value) -> None:
        if isinstance(value, float):
            raise RuntimeError("Signed update manifests may not contain floating-point numbers")
        if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 9_007_199_254_740_991:
            raise RuntimeError("Signed update manifest integer exceeds JavaScript safe range")
        if isinstance(value, dict):
            for child in value.values():
                validate(child)
        elif isinstance(value, list):
            for child in value:
                validate(child)

    unsigned = {key: value for key, value in manifest.items() if key != "signature"}
    validate(unsigned)
    # ensure_ascii=False intentionally matches JSON.stringify: both emit UTF-8
    # characters directly. Cross-language tests include Chinese asset names.
    return json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(manifest: dict, private_key_path: Path, signed_at: str | None = None) -> dict:
    if not private_key_path.is_file():
        raise RuntimeError(f"Ed25519 signing key is missing: {private_key_path}")
    key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise RuntimeError("Release signing key is not an Ed25519 private key")
    raw_public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = f"memo-ed25519-{hashlib.sha256(raw_public).hexdigest()[:16]}"
    manifest["formatVersion"] = 3
    manifest["signatureVersion"] = 1
    manifest["signedAt"] = signed_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    signature = key.sign(canonical_manifest_bytes(manifest))
    manifest["signature"] = {
        "algorithm": "Ed25519",
        "keyId": key_id,
        "value": base64.b64encode(signature).decode("ascii"),
    }
    return manifest


def asset(path: Path, base_url: str) -> dict:
    return {
        "name": path.name,
        "url": f"{base_url.rstrip('/')}/{quote(path.name)}",
        "size": path.stat().st_size,
        "sha256": f"sha256:{sha256(path)}",
    }


def delta_asset(path: Path, base_url: str) -> dict:
    with zipfile.ZipFile(path) as bundle:
        inner = json.loads(bundle.read("service-patch-manifest.json").decode("utf-8"))
    if inner.get("kind") != "delta" or not inner.get("fromVersion") or not inner.get("toVersion"):
        raise RuntimeError(f"Not a valid delta service patch: {path}")
    return {
        "from": str(inner["fromVersion"]),
        "to": str(inner["toVersion"]),
        **asset(path, f"{base_url.rstrip('/')}/service"),
    }


def build(full: Path, lite: Path, service_zip: Path, launcher_version: str, service_version: str, base_url: str, output: Path, patches: list[Path] | None = None, signing_key: Path | None = None, signed_at: str | None = None) -> dict:
    full_asset = asset(full, base_url)
    lite_asset = asset(lite, base_url)
    service_asset = asset(service_zip, f"{base_url.rstrip('/')}/service")
    patch_assets = sorted((delta_asset(path, base_url) for path in (patches or [])), key=lambda row: (row["from"], row["to"]))
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
            # Flat asset fields keep the V1 Service Patch client compatible.
            **service_asset,
            "full": service_asset,
            "patches": patch_assets,
        },
        # Backward-compatible fields used by 0.10.7 and older launchers.
        "full": full_asset,
        "lite": lite_asset,
    }
    if signing_key is None:
        raise RuntimeError("Refusing to generate an unsigned release manifest; provide an Ed25519 signing key")
    sign_manifest(manifest, signing_key, signed_at=signed_at)
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
    parser.add_argument("--patch", action="append", default=[], help="Delta patch ZIP; may be repeated")
    parser.add_argument("--base-url", default="https://memo.zhaguzhagu.com/downloads")
    parser.add_argument("--signing-key", default=os.getenv("MEMO_UPDATE_SIGNING_KEY", ""))
    parser.add_argument("--output", default=str(ROOT / "artifacts" / "latest.v2.json"))
    args = parser.parse_args()
    if not args.signing_key:
        parser.error("--signing-key or MEMO_UPDATE_SIGNING_KEY is required; unsigned release manifests are forbidden")
    build(
        Path(args.full), Path(args.lite), Path(args.service),
        args.launcher_version, args.service_version, args.base_url, Path(args.output),
        patches=[Path(value) for value in args.patch],
        signing_key=Path(args.signing_key),
    )
    print(f"Release manifest ready: {args.output} (not published)")


if __name__ == "__main__":
    main()
