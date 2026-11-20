import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from installer import installer_runner
from installer.install_contract import SERVICE_VERSION, detect_state, install_paths


@pytest.fixture(autouse=True)
def isolate_generated_offline_assets(tmp_path, monkeypatch):
    missing = tmp_path / "no-offline-assets"
    monkeypatch.setattr(installer_runner, "OFFLINE_ASSET_ARCHIVE", missing / "memo-offline-assets.zip")
    monkeypatch.setattr(installer_runner, "OFFLINE_ASSET_MANIFEST", missing / "memo-offline-assets.manifest.json")
    monkeypatch.setattr(installer_runner, "PAYLOAD_MODELS", missing / "models")


def make_payload(tmp_path: Path):
    app = tmp_path / "payload" / "app"
    runtime = tmp_path / "payload" / "runtime"
    (app / "memo").mkdir(parents=True)
    (app / "start_all.bat").write_text("", encoding="utf-8")
    runtime.mkdir(parents=True)
    (runtime / "python.exe").write_text("", encoding="utf-8")
    return app, runtime


def test_fresh_install_copies_payload_and_writes_manifest_without_developer_data(tmp_path, monkeypatch):
    app, runtime = make_payload(tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.setenv("MEMO_RUNTIME_ROOT", str(runtime))
    monkeypatch.setattr(installer_runner, "PAYLOAD_APP", app)
    monkeypatch.setattr(installer_runner, "PAYLOAD_RUNTIME", runtime)
    monkeypatch.setattr(installer_runner, "initialize_service", lambda paths: None)

    result = installer_runner.install(api_key="test-key", base_url="https://api.example/v1", model="demo-model")

    paths = install_paths()
    assert result["ok"] is True
    assert result["before"]["mode"] == "fresh"
    assert result["after"]["mode"] == "healthy_latest"
    assert result["config"]["hasApiKey"] is True
    assert paths.manifest.exists()
    install_manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    assert install_manifest["schemaVersion"] == 2
    assert install_manifest["installedFiles"]["start_all.bat"]
    assert all(not name.endswith((".db", ".pyc")) for name in install_manifest["installedFiles"])
    assert (paths.runtime_root / "python.exe").exists()
    assert result["runtime"]["copied"] is True
    assert paths.env_file.read_text(encoding="utf-8").find("test-key") > -1
    assert not (paths.app_root / ".env").exists()
    assert not (paths.app_root / "data").exists()


def make_offline_archive(tmp_path: Path):
    archive = tmp_path / "offline" / "memo-offline-assets.zip"
    archive.parent.mkdir(parents=True)
    runtime_fingerprint = "runtime-v1"
    model_fingerprint = "model-v1"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("runtime/python.exe", b"runtime")
        bundle.writestr("runtime/.memo-runtime-manifest.json", json.dumps({"fingerprint": runtime_fingerprint}))
        bundle.writestr("models/bge-small-zh-v1.5/model.safetensors", b"model")
        bundle.writestr("models/bge-small-zh-v1.5/model-manifest.json", json.dumps({"fingerprint": model_fingerprint}))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = archive.with_suffix(".manifest.json")
    manifest.write_text(json.dumps({
        "sha256": digest,
        "runtimeFingerprint": runtime_fingerprint,
        "modelFingerprint": model_fingerprint,
    }), encoding="utf-8")
    return archive, manifest


def test_full_offline_archive_installs_runtime_and_model_once(tmp_path, monkeypatch):
    app, _ = make_payload(tmp_path)
    archive, manifest = make_offline_archive(tmp_path)
    root = tmp_path / "MemoRoot"
    monkeypatch.setenv("MEMO_USER_ROOT", str(root))
    monkeypatch.setenv("MEMO_RUNTIME_ROOT", str(root / "Programs" / "Memo" / "runtime"))
    monkeypatch.setattr(installer_runner, "PAYLOAD_APP", app)
    monkeypatch.setattr(installer_runner, "OFFLINE_ASSET_ARCHIVE", archive)
    monkeypatch.setattr(installer_runner, "OFFLINE_ASSET_MANIFEST", manifest)
    monkeypatch.setattr(installer_runner, "initialize_service", lambda paths: None)

    first = installer_runner.install()
    paths = install_paths()
    assert first["runtime"]["copied"] is True
    assert first["model"]["copied"] is True
    assert (paths.runtime_root / "python.exe").read_bytes() == b"runtime"
    assert (paths.embedding_model_root / "model.safetensors").read_bytes() == b"model"
    assert "MEMO_EMBEDDING_MODEL=" in paths.env_file.read_text(encoding="utf-8")

    second = installer_runner.install(api_key="new-key")
    assert second["runtime"]["copied"] is False
    assert second["model"]["copied"] is False


def test_program_directory_swap_releases_locks_and_retries_permission_error(tmp_path, monkeypatch):
    source = tmp_path / "runtime.new"
    target = tmp_path / "runtime"
    source.mkdir()
    target.mkdir()
    (source / "python.exe").write_text("new", encoding="utf-8")
    (target / "python.exe").write_text("old", encoding="utf-8")
    original_replace = Path.replace
    attempts = {"target": 0, "release": 0}

    def flaky_replace(path, destination):
        if path == target and attempts["target"] < 2:
            attempts["target"] += 1
            raise PermissionError(5, "simulated runtime lock", str(path))
        return original_replace(path, destination)

    def release_locks():
        attempts["release"] += 1

    monkeypatch.setattr(Path, "replace", flaky_replace)
    result = installer_runner.swap_program_directory(source, target, release_locks=release_locks, retries=4)

    assert attempts["target"] == 2
    assert attempts["release"] == 3
    assert (target / "python.exe").read_text(encoding="utf-8") == "new"
    assert (result["previous"] / "python.exe").read_text(encoding="utf-8") == "old"


def test_full_upgrade_stops_runtime_again_immediately_before_swap(tmp_path, monkeypatch):
    app, _ = make_payload(tmp_path)
    archive, manifest = make_offline_archive(tmp_path)
    root = tmp_path / "MemoRoot"
    runtime = root / "Programs" / "Memo" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "python.exe").write_text("old", encoding="utf-8")
    (runtime / ".memo-runtime-manifest.json").write_text('{"fingerprint":"old"}', encoding="utf-8")
    monkeypatch.setenv("MEMO_USER_ROOT", str(root))
    monkeypatch.setenv("MEMO_RUNTIME_ROOT", str(runtime))
    monkeypatch.setattr(installer_runner, "PAYLOAD_APP", app)
    monkeypatch.setattr(installer_runner, "OFFLINE_ASSET_ARCHIVE", archive)
    monkeypatch.setattr(installer_runner, "OFFLINE_ASSET_MANIFEST", manifest)
    monkeypatch.setattr(installer_runner, "initialize_service", lambda paths: None)
    stop_calls = []
    monkeypatch.setattr(installer_runner, "stop_runtime_processes", lambda runtime_root: stop_calls.append(Path(runtime_root)) or [])

    result = installer_runner.install()

    assert result["runtime"]["copied"] is True
    assert len(stop_calls) >= 2  # initial stop plus the pre-swap stop
    assert stop_calls[-1] == runtime
    assert (runtime / "python.exe").read_text(encoding="utf-8") == "runtime"


def test_legacy_migration_copies_database_sidecars_and_env_without_deleting_source(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    target = install_paths()
    source = install_paths({"MEMO_USER_ROOT": str(tmp_path / "legacy-memo")})
    source.data_root.mkdir(parents=True)
    source.database.write_bytes(b"legacy-database")
    Path(f"{source.database}-wal").write_bytes(b"legacy-wal")
    Path(f"{source.database}-shm").write_bytes(b"legacy-shm")
    (source.user_root / ".env").write_text("LLM_API_KEY=legacy-key\n", encoding="utf-8")

    result = installer_runner.migrate_legacy_user_state(str(source.user_root), target)

    assert target.database.read_bytes() == b"legacy-database"
    assert Path(f"{target.database}-wal").read_bytes() == b"legacy-wal"
    assert Path(f"{target.database}-shm").read_bytes() == b"legacy-shm"
    assert target.env_file.read_text(encoding="utf-8") == "LLM_API_KEY=legacy-key\n"
    assert source.database.read_bytes() == b"legacy-database"
    assert Path(result["backup"]).is_dir()
    assert (Path(result["backup"]) / source.database.name).read_bytes() == b"legacy-database"


def test_legacy_migration_refuses_to_overwrite_formal_database(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    target = install_paths()
    source = install_paths({"MEMO_USER_ROOT": str(tmp_path / "legacy-memo")})
    source.data_root.mkdir(parents=True)
    target.data_root.mkdir(parents=True)
    source.database.write_bytes(b"legacy")
    target.database.write_bytes(b"formal")

    try:
        installer_runner.migrate_legacy_user_state(str(source.user_root), target)
        assert False, "migration should refuse an occupied formal target"
    except RuntimeError as exc:
        assert "不能自动覆盖或合并" in str(exc)
    assert target.database.read_bytes() == b"formal"
    assert source.database.read_bytes() == b"legacy"


def test_lite_move_reuses_runtime_only_with_explicit_data_migration(tmp_path, monkeypatch):
    app, _ = make_payload(tmp_path)
    source_root = tmp_path / "old-root"
    source_runtime = source_root / "Programs" / "Memo" / "runtime"
    source_runtime.mkdir(parents=True)
    (source_runtime / "python.exe").write_text("runtime", encoding="utf-8")
    (source_root / "data").mkdir(parents=True)
    (source_root / "data" / "memo_source_aware.db").write_bytes(b"existing-data")
    target_root = tmp_path / "new-root"
    missing_payload_runtime = tmp_path / "lite-has-no-runtime"
    monkeypatch.setenv("MEMO_USER_ROOT", str(target_root))
    monkeypatch.setenv("MEMO_RUNTIME_ROOT", str(source_runtime))
    monkeypatch.setattr(installer_runner, "PAYLOAD_APP", app)
    monkeypatch.setattr(installer_runner, "PAYLOAD_RUNTIME", missing_payload_runtime)
    monkeypatch.setattr(installer_runner, "DEFAULT_RUNTIME_PYTHON", missing_payload_runtime / "python.exe")
    monkeypatch.setattr(installer_runner, "initialize_service", lambda paths: None)

    result = installer_runner.install(migrate_from=str(source_root))
    paths = install_paths()

    assert result["ok"] is True
    assert result["runtime"]["copied"] is True
    assert (paths.runtime_root / "python.exe").read_text(encoding="utf-8") == "runtime"
    assert paths.database.read_bytes() == b"existing-data"


def test_detect_is_read_only_and_does_not_create_guessed_root(tmp_path):
    guessed = tmp_path / "guessed-empty-root"
    completed = subprocess.run(
        [sys.executable, str(Path(installer_runner.__file__)), "--detect", "--user-root", str(guessed)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    assert json.loads(completed.stdout)["mode"] == "fresh"
    assert not guessed.exists()


def test_lite_refuses_to_create_second_root_when_runtime_belongs_elsewhere(tmp_path, monkeypatch):
    app, _ = make_payload(tmp_path)
    source_runtime = tmp_path / "old-root" / "Programs" / "Memo" / "runtime"
    source_runtime.mkdir(parents=True)
    (source_runtime / "python.exe").write_text("runtime", encoding="utf-8")
    target_root = tmp_path / "wrong-new-root"
    missing_payload_runtime = tmp_path / "lite-has-no-runtime"
    monkeypatch.setenv("MEMO_USER_ROOT", str(target_root))
    monkeypatch.setenv("MEMO_RUNTIME_ROOT", str(source_runtime))
    monkeypatch.setattr(installer_runner, "PAYLOAD_APP", app)
    monkeypatch.setattr(installer_runner, "PAYLOAD_RUNTIME", missing_payload_runtime)
    monkeypatch.setattr(installer_runner, "DEFAULT_RUNTIME_PYTHON", missing_payload_runtime / "python.exe")
    monkeypatch.setattr(installer_runner, "initialize_service", lambda paths: None)

    try:
        installer_runner.install()
        assert False, "Lite should refuse an unconfirmed second root"
    except RuntimeError as exc:
        assert "选择已有 Memo 数据目录" in str(exc)
    assert not (target_root / "Programs" / "Memo" / "runtime" / "python.exe").exists()


def test_latest_install_without_new_config_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    paths = install_paths()
    (paths.app_root / "memo").mkdir(parents=True)
    (paths.app_root / "start_all.bat").write_text("old", encoding="utf-8")
    paths.runtime_root.mkdir(parents=True)
    (paths.runtime_root / "python.exe").write_text("old", encoding="utf-8")
    paths.manifest.write_text('{"serviceVersion": "' + SERVICE_VERSION + '"}', encoding="utf-8")

    result = installer_runner.install()

    assert result["ok"] is True
    assert result["skipped"] is True
    assert detect_state(paths)["mode"] == "healthy_latest"
    assert (paths.app_root / "start_all.bat").read_text(encoding="utf-8") == "old"
