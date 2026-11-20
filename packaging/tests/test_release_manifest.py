import base64
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_release_manifest import build, canonical_manifest_bytes


def make_signing_key(tmp_path: Path) -> Path:
    path = tmp_path / "release-signing-key.pem"
    key = Ed25519PrivateKey.generate()
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    return path


def assert_valid_signature(manifest: dict, key_path: Path) -> None:
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    key.public_key().verify(base64.b64decode(manifest["signature"]["value"]), canonical_manifest_bytes(manifest))


def test_release_builder_refuses_unsigned_manifest(tmp_path):
    files = [tmp_path / name for name in ("Full.exe", "Lite.exe", "Service.zip")]
    for path in files:
        path.write_bytes(path.name.encode())
    with pytest.raises(RuntimeError, match="unsigned release manifest"):
        build(*files, "1.0.0", "1.0.0", "https://example.invalid/downloads", tmp_path / "latest.json")


def test_python_signed_unicode_manifest_is_accepted_by_node_client(tmp_path):
    full = tmp_path / "Memo 完整安装包.exe"
    lite = tmp_path / "Memo 轻量安装包.exe"
    service = tmp_path / "Memo 服务包.zip"
    for path in (full, lite, service):
        path.write_bytes(path.name.encode("utf-8"))
    key_path = make_signing_key(tmp_path)
    manifest_path = tmp_path / "latest.json"
    manifest = build(
        full, lite, service, "1.0.0", "1.0.0", "https://example.invalid/下载",
        manifest_path, signing_key=key_path, signed_at="2026-08-24T00:00:00Z",
    )
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    public_path = tmp_path / "public.pem"
    public_path.write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    module_path = ROOT / "desktop" / "update-signature.cjs"
    script = (
        "const fs=require('fs');"
        "const mod=require(process.argv[1]);"
        "const manifest=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
        "const pub=fs.readFileSync(process.argv[3],'utf8');"
        "const result=mod.verifyReleaseManifest(manifest,{[manifest.signature.keyId]:pub});"
        "if(!result.ok){throw new Error(result.error)}"
    )
    run = subprocess.run(
        ["node", "-e", script, str(module_path), str(manifest_path), str(public_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert run.returncode == 0, run.stderr or run.stdout
    assert "Memo 完整安装包.exe" in manifest["launcher"]["full"]["name"]


def test_v2_manifest_keeps_legacy_assets_and_splits_versions(tmp_path):
    full = tmp_path / "Memo Setup.exe"
    lite = tmp_path / "Memo Lite Setup.exe"
    service = tmp_path / "Memo-Service.zip"
    full.write_bytes(b"full")
    lite.write_bytes(b"lite")
    service.write_bytes(b"service")
    output = tmp_path / "latest.json"

    signing_key = make_signing_key(tmp_path)
    manifest = build(
        full, lite, service, "1.2.0", "1.2.3", "https://example.invalid/downloads", output,
        signing_key=signing_key, signed_at="2026-08-24T00:00:00Z",
    )

    assert manifest["formatVersion"] == 3
    assert manifest["version"] == manifest["launcher"]["version"] == "1.2.0"
    assert manifest["service"]["version"] == "1.2.3"
    assert manifest["full"] == manifest["launcher"]["full"]
    assert manifest["lite"] == manifest["launcher"]["lite"]
    assert manifest["service"]["url"].endswith("/service/Memo-Service.zip")
    assert manifest["service"]["full"]["sha256"] == manifest["service"]["sha256"]
    assert manifest["service"]["patches"] == []
    assert manifest["signature"]["algorithm"] == "Ed25519"
    assert_valid_signature(manifest, signing_key)
    assert output.exists()


def test_v2_manifest_publishes_delta_edges(tmp_path):
    full = tmp_path / "Full.exe"
    lite = tmp_path / "Lite.exe"
    service = tmp_path / "Service.zip"
    patch = tmp_path / "Delta.zip"
    for path in (full, lite, service):
        path.write_bytes(path.name.encode())
    with zipfile.ZipFile(patch, "w") as bundle:
        bundle.writestr("service-patch-manifest.json", json.dumps({
            "schemaVersion": 2, "kind": "delta", "fromVersion": "1.0.0", "toVersion": "1.1.0",
        }))

    signing_key = make_signing_key(tmp_path)
    manifest = build(
        full, lite, service, "1.1.0", "1.1.0", "https://example.invalid/downloads",
        tmp_path / "latest.json", patches=[patch], signing_key=signing_key,
        signed_at="2026-08-24T00:00:00Z",
    )

    edge = manifest["service"]["patches"][0]
    assert edge["from"] == "1.0.0"
    assert edge["to"] == "1.1.0"
    assert edge["url"].endswith("/service/Delta.zip")
    assert edge["sha256"].startswith("sha256:")
