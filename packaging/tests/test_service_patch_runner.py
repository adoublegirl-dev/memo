import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from installer import service_patch_runner
from installer.install_contract import install_paths


def make_patch(tmp_path: Path, version: str = "0.10.8-alpha"):
    files = {
        "start_all.bat": b"@echo off\n",
        "stop_all.bat": b"@echo off\n",
        "memo/__init__.py": b"",
        "memo/core/engine.py": b"VALUE = 'new'\n",
        "scripts/memo_dashboard.py": b"VALUE = 'new'\n",
    }
    manifest_files = [
        {"path": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        for name, content in sorted(files.items())
    ]
    inner = {
        "schemaVersion": 1,
        "serviceVersion": version,
        "sourceCommit": "abc123",
        "files": manifest_files,
    }
    archive = tmp_path / "Memo-Service.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, content in files.items():
            bundle.writestr(f"app/{name}", content)
        bundle.writestr("service-patch-manifest.json", json.dumps(inner))
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest()


def test_service_patch_replaces_only_app_and_can_rollback(tmp_path, monkeypatch):
    root = tmp_path / "MemoRoot"
    monkeypatch.setenv("MEMO_USER_ROOT", str(root))
    paths = install_paths()
    (paths.app_root / "memo").mkdir(parents=True)
    (paths.app_root / "old-marker.txt").write_text("old", encoding="utf-8")
    paths.data_root.mkdir(parents=True)
    paths.database.write_bytes(b"database-must-not-change")
    paths.config_root.mkdir(parents=True)
    paths.env_file.write_text("LLM_API_KEY=must-stay\n", encoding="utf-8")
    archive, digest = make_patch(tmp_path)

    result = service_patch_runner.apply_patch(archive, digest, "0.10.8-alpha")

    assert result["ok"] is True
    assert not (paths.app_root / "old-marker.txt").exists()
    assert (paths.app_root / "memo" / "core" / "engine.py").exists()
    install_manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    assert install_manifest["schemaVersion"] == 2
    assert install_manifest["installedFiles"]["memo/core/engine.py"]
    assert not list(paths.app_root.rglob("*.pyc"))
    assert paths.database.read_bytes() == b"database-must-not-change"
    assert paths.env_file.read_text(encoding="utf-8") == "LLM_API_KEY=must-stay\n"

    service_patch_runner.rollback(Path(result["backup"]))
    assert (paths.app_root / "old-marker.txt").read_text(encoding="utf-8") == "old"
    assert paths.database.read_bytes() == b"database-must-not-change"


def make_delta_patch(tmp_path: Path, old_files: dict[str, bytes], new_files: dict[str, bytes], version_from="1.0.0", version_to="1.1.0"):
    changed = []
    payload = {}
    for name, content in sorted(new_files.items()):
        if old_files.get(name) == content:
            continue
        payload[name] = content
        changed.append({
            "path": name,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "oldSha256": hashlib.sha256(old_files[name]).hexdigest() if name in old_files else None,
        })
    deletes = [
        {"path": name, "oldSha256": hashlib.sha256(content).hexdigest()}
        for name, content in sorted(old_files.items()) if name not in new_files
    ]
    target_files = {name: hashlib.sha256(content).hexdigest() for name, content in sorted(new_files.items())}
    manifest = {
        "schemaVersion": 2,
        "kind": "delta",
        "fromVersion": version_from,
        "toVersion": version_to,
        "fromCommit": "old-commit",
        "toCommit": "new-commit",
        "files": changed,
        "deletes": deletes,
        "targetFiles": target_files,
    }
    archive = tmp_path / f"delta-{version_from}-{version_to}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, content in payload.items():
            bundle.writestr(f"app/{name}", content)
        bundle.writestr("service-patch-manifest.json", json.dumps(manifest))
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest(), manifest


def install_old_app(paths, files: dict[str, bytes], version="1.0.0"):
    for name, content in files.items():
        path = paths.app_root / Path(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    paths.manifest.write_text(json.dumps({
        "schemaVersion": 2,
        "serviceVersion": version,
        "installedFiles": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
    }), encoding="utf-8")


def delta_fixture_files():
    old = {
        "start_all.bat": b"@echo old\n",
        "stop_all.bat": b"@echo off\n",
        "memo/__init__.py": b"",
        "memo/core/engine.py": b"VALUE = 'old'\n",
        "scripts/memo_dashboard.py": b"VALUE = 'dashboard'\n",
        "scripts/obsolete.py": b"obsolete\n",
    }
    new = {
        "start_all.bat": b"@echo old\n",
        "stop_all.bat": b"@echo off\n",
        "memo/__init__.py": b"",
        "memo/core/engine.py": b"VALUE = 'new'\n",
        "scripts/memo_dashboard.py": b"VALUE = 'dashboard'\n",
        "scripts/added.py": b"added\n",
    }
    return old, new


def test_delta_patch_changes_adds_and_exactly_deletes_then_rolls_back(tmp_path, monkeypatch):
    root = tmp_path / "MemoRoot"
    monkeypatch.setenv("MEMO_USER_ROOT", str(root))
    paths = install_paths()
    old, new = delta_fixture_files()
    install_old_app(paths, old)
    (paths.app_root / "local-note.txt").write_text("unmanaged", encoding="utf-8")
    paths.data_root.mkdir(parents=True)
    protected = {
        paths.database: b"database-unchanged",
        Path(f"{paths.database}-wal"): b"wal-unchanged",
        Path(f"{paths.database}-shm"): b"shm-unchanged",
        paths.env_file: b"LLM_API_KEY=secret\n",
    }
    for protected_path, content in protected.items():
        protected_path.parent.mkdir(parents=True, exist_ok=True)
        protected_path.write_bytes(content)
    before_hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    archive, digest, _ = make_delta_patch(tmp_path, old, new)

    result = service_patch_runner.apply_delta_patch(archive, digest, "1.0.0", "1.1.0")

    assert result["ok"] is True
    assert result["skippedDeletes"] == []
    assert (paths.app_root / "memo/core/engine.py").read_bytes() == new["memo/core/engine.py"]
    assert (paths.app_root / "scripts/added.py").read_bytes() == b"added\n"
    assert not (paths.app_root / "scripts/obsolete.py").exists()
    assert (paths.app_root / "local-note.txt").read_text(encoding="utf-8") == "unmanaged"
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected} == before_hashes
    local_manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    assert local_manifest["serviceVersion"] == "1.1.0"
    assert local_manifest["installedFiles"] == {name: hashlib.sha256(content).hexdigest() for name, content in sorted(new.items())}

    service_patch_runner.rollback(Path(result["backup"]))
    assert (paths.app_root / "scripts/obsolete.py").read_bytes() == b"obsolete\n"
    assert (paths.app_root / "memo/core/engine.py").read_bytes() == old["memo/core/engine.py"]


def test_multi_hop_delta_chain_can_roll_back_all_hops_in_reverse(tmp_path, monkeypatch):
    root = tmp_path / "MemoRoot"
    monkeypatch.setenv("MEMO_USER_ROOT", str(root))
    paths = install_paths()
    old, middle = delta_fixture_files()
    final = dict(middle)
    final["memo/core/engine.py"] = b"VALUE = 'final'\n"
    final["scripts/second-hop.py"] = b"second\n"
    install_old_app(paths, old, "1.0.0")
    paths.data_root.mkdir(parents=True)
    paths.database.write_bytes(b"chain-database")
    first_zip, first_digest, _ = make_delta_patch(tmp_path, old, middle, "1.0.0", "1.1.0")
    second_zip, second_digest, _ = make_delta_patch(tmp_path, middle, final, "1.1.0", "1.2.0")

    first = service_patch_runner.apply_delta_patch(first_zip, first_digest, "1.0.0", "1.1.0")
    service_patch_runner.finalize(Path(first["backup"]))
    second = service_patch_runner.apply_delta_patch(second_zip, second_digest, "1.1.0", "1.2.0")
    service_patch_runner.finalize(Path(second["backup"]))
    assert json.loads(paths.manifest.read_text(encoding="utf-8"))["serviceVersion"] == "1.2.0"

    service_patch_runner.rollback(Path(second["backup"]))
    service_patch_runner.rollback(Path(first["backup"]))

    assert json.loads(paths.manifest.read_text(encoding="utf-8"))["serviceVersion"] == "1.0.0"
    assert (paths.app_root / "memo/core/engine.py").read_bytes() == old["memo/core/engine.py"]
    assert paths.database.read_bytes() == b"chain-database"


def test_recover_restores_unverified_program_without_touching_user_data(tmp_path, monkeypatch):
    root = tmp_path / "MemoRoot"
    monkeypatch.setenv("MEMO_USER_ROOT", str(root))
    paths = install_paths()
    paths.app_root.mkdir(parents=True)
    (paths.app_root / "old.txt").write_text("old", encoding="utf-8")
    paths.data_root.mkdir(parents=True)
    paths.database.write_bytes(b"database")
    archive, digest = make_patch(tmp_path, "2.0.0")

    applied = service_patch_runner.apply_patch(archive, digest, "2.0.0")
    assert not (paths.app_root / "old.txt").exists()
    assert (paths.app_root.parent / service_patch_runner.TRANSACTION_NAME).exists()

    recovered = service_patch_runner.recover()

    assert recovered["recovered"] is True
    assert (paths.app_root / "old.txt").read_text(encoding="utf-8") == "old"
    assert paths.database.read_bytes() == b"database"
    assert not (paths.app_root.parent / service_patch_runner.TRANSACTION_NAME).exists()
    assert not Path(applied["backup"]).exists()


def test_delta_delete_preserves_locally_modified_file(tmp_path, monkeypatch):
    root = tmp_path / "MemoRoot"
    monkeypatch.setenv("MEMO_USER_ROOT", str(root))
    paths = install_paths()
    old, new = delta_fixture_files()
    install_old_app(paths, old)
    (paths.app_root / "scripts/obsolete.py").write_bytes(b"user-modified\n")
    archive, digest, _ = make_delta_patch(tmp_path, old, new)

    result = service_patch_runner.apply_delta_patch(archive, digest, "1.0.0", "1.1.0")

    assert (paths.app_root / "scripts/obsolete.py").read_bytes() == b"user-modified\n"
    assert result["skippedDeletes"] == [{"path": "scripts/obsolete.py", "reason": "local_file_changed"}]


def test_rollback_rejects_directory_outside_memo_program_root(tmp_path, monkeypatch):
    root = tmp_path / "MemoRoot"
    monkeypatch.setenv("MEMO_USER_ROOT", str(root))
    outside = tmp_path / "app.previous-attacker"
    outside.mkdir()
    (outside / "do-not-touch.txt").write_text("safe", encoding="utf-8")

    try:
        service_patch_runner.rollback(outside)
        assert False, "rollback must reject an external directory"
    except RuntimeError as exc:
        assert "Unsafe service update transaction path" in str(exc)
    assert (outside / "do-not-touch.txt").read_text(encoding="utf-8") == "safe"


def test_delta_refuses_changed_file_when_local_baseline_drifted(tmp_path, monkeypatch):
    root = tmp_path / "MemoRoot"
    monkeypatch.setenv("MEMO_USER_ROOT", str(root))
    paths = install_paths()
    old, new = delta_fixture_files()
    install_old_app(paths, old)
    (paths.app_root / "memo/core/engine.py").write_bytes(b"local-edit\n")
    archive, digest, _ = make_delta_patch(tmp_path, old, new)

    try:
        service_patch_runner.apply_delta_patch(archive, digest, "1.0.0", "1.1.0")
        assert False, "delta must refuse a locally modified changed file"
    except RuntimeError as exc:
        assert "refusing overwrite" in str(exc)
    assert (paths.app_root / "memo/core/engine.py").read_bytes() == b"local-edit\n"
    assert json.loads(paths.manifest.read_text(encoding="utf-8"))["serviceVersion"] == "1.0.0"


def test_service_patch_rejects_forbidden_database_file(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("app/data/memo_source_aware.db", b"bad")
        bundle.writestr("service-patch-manifest.json", json.dumps({"serviceVersion": "x", "files": []}))
    staging = tmp_path / "staging"
    staging.mkdir()
    try:
        service_patch_runner.extract_and_verify(archive, staging, "x")
        assert False, "database files must be rejected"
    except RuntimeError as exc:
        assert "Forbidden" in str(exc)
