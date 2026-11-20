"""Run an isolated real-artifact delta apply + rollback redline check."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "installer"))

import service_patch_runner


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install_full_snapshot(archive: Path, user_root: Path) -> dict:
    app_root = user_root / "Programs" / "Memo" / "app"
    app_root.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read("service-patch-manifest.json").decode("utf-8"))
        rows = {str(row["path"]): str(row["sha256"]) for row in manifest.get("files") or []}
        for name in bundle.namelist():
            if not name.startswith("app/") or name.endswith("/"):
                continue
            relative = PurePosixPath(name).relative_to("app")
            destination = app_root.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(bundle.read(name))
    (app_root / "memo-install-manifest.json").write_text(json.dumps({
        "schemaVersion": 2,
        "serviceVersion": manifest["serviceVersion"],
        "sourceCommit": manifest.get("sourceCommit", ""),
        "installedFiles": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify(old_package: Path, delta_package: Path, expected_from: str, expected_to: str) -> None:
    with tempfile.TemporaryDirectory(prefix="memo-v2-e2e-") as temporary:
        user_root = Path(temporary) / "Memo"
        old_manifest = install_full_snapshot(old_package, user_root)
        if old_manifest.get("serviceVersion") != expected_from:
            raise RuntimeError("Old snapshot version mismatch")
        os.environ["MEMO_USER_ROOT"] = str(user_root)
        paths = service_patch_runner.patch_paths()
        protected = {
            paths.user_root / "data" / "memo_source_aware.db": b"database-redline",
            paths.user_root / "data" / "memo_source_aware.db-wal": b"wal-redline",
            paths.user_root / "data" / "memo_source_aware.db-shm": b"shm-redline",
            paths.user_root / "config" / ".env": b"LLM_API_KEY=redline-secret\n",
        }
        for path, content in protected.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        before = {path: sha(path) for path in protected}
        applied = service_patch_runner.apply_delta_patch(
            delta_package, service_patch_runner.sha256_file(delta_package), expected_from, expected_to,
        )
        current = json.loads(paths.manifest.read_text(encoding="utf-8"))
        if current.get("serviceVersion") != expected_to:
            raise RuntimeError("Delta did not reach target version")
        if {path: sha(path) for path in protected} != before:
            raise RuntimeError("Protected database/WAL/SHM/.env redline changed during apply")
        service_patch_runner.rollback(Path(applied["backup"]))
        restored = json.loads(paths.manifest.read_text(encoding="utf-8"))
        if restored.get("serviceVersion") != expected_from:
            raise RuntimeError("Reverse rollback did not restore the starting version")
        if {path: sha(path) for path in protected} != before:
            raise RuntimeError("Protected database/WAL/SHM/.env redline changed during rollback")
    print(f"E2E_OK {expected_from} -> {expected_to} -> {expected_from}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-package", required=True)
    parser.add_argument("--delta-package", required=True)
    parser.add_argument("--from-version", required=True)
    parser.add_argument("--to-version", required=True)
    args = parser.parse_args()
    verify(Path(args.old_package), Path(args.delta_package), args.from_version, args.to_version)


if __name__ == "__main__":
    main()
