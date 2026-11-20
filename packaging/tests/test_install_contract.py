import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from installer.install_contract import SERVICE_VERSION, detect_state, install_paths, normalize_user_root, read_env, write_user_config


def test_first_install_uses_local_app_data_only(tmp_path: Path):
    paths = install_paths({"LOCALAPPDATA": str(tmp_path / "Local")})
    status = detect_state(paths)
    assert status["mode"] == "fresh"
    assert str(paths.user_root).startswith(str(tmp_path))
    assert paths.database.name == "memo_source_aware.db"


def test_key_is_written_to_user_config_and_existing_values_survive(tmp_path: Path):
    paths = install_paths({"LOCALAPPDATA": str(tmp_path)})
    paths.config_root.mkdir(parents=True)
    paths.env_file.write_text("CUSTOM_VALUE=keep\nLLM_API_KEY=old\n", encoding="utf-8")
    result = write_user_config(paths, api_key="new-key", base_url="https://api.example/v1", model="demo-model")
    values = read_env(paths.env_file)
    assert result["hasApiKey"] is True
    assert values["CUSTOM_VALUE"] == "keep"
    assert values["LLM_API_KEY"] == "new-key"
    assert values["MEMO_DB_PATH"] == str(paths.database)
    assert "MEMO_EMBEDDING_MODEL" not in values


def test_pinned_offline_model_path_is_written_only_after_model_exists(tmp_path: Path):
    paths = install_paths({"LOCALAPPDATA": str(tmp_path)})
    paths.embedding_model_root.mkdir(parents=True)
    (paths.embedding_model_root / "model-manifest.json").write_text('{"fingerprint":"model-v1"}', encoding="utf-8")
    write_user_config(paths)
    values = read_env(paths.env_file)
    assert values["MEMO_EMBEDDING_MODEL"] == str(paths.embedding_model_root)
    assert detect_state(paths)["modelPresent"] is True


def test_selected_data_folder_is_normalized_to_memo_root(tmp_path: Path):
    root = tmp_path / "MemoRoot"
    data = root / "data"
    data.mkdir(parents=True)
    (data / "memo_source_aware.db").write_bytes(b"sqlite-placeholder")
    assert normalize_user_root(data) == root
    assert normalize_user_root(root) == root


def test_latest_install_is_not_replaced(tmp_path: Path):
    paths = install_paths({"LOCALAPPDATA": str(tmp_path)})
    (paths.app_root / "memo").mkdir(parents=True)
    (paths.app_root / "start_all.bat").write_text("", encoding="utf-8")
    paths.runtime_root.mkdir(parents=True)
    (paths.runtime_root / "python.exe").write_text("", encoding="utf-8")
    paths.manifest.write_text('{"serviceVersion": "' + SERVICE_VERSION + '"}', encoding="utf-8")
    assert detect_state(paths)["mode"] == "healthy_latest"
