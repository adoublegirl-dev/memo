from pathlib import Path

from scripts.prepare_source_aware_runtime import apply_prepare, build_plan, read_env_db_path


def paths(tmp_path: Path):
    root = tmp_path / "install"
    data = root / "data"
    return root, data / ".env", data / "memo_source_aware.db", data / "memo.db", data / "backups"


def test_old_database_is_backed_up_and_new_source_aware_db_becomes_runtime(tmp_path: Path):
    root, _unused, target, legacy, backups = paths(tmp_path)
    env = root / ".env"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy-user-data")
    env.write_text("MEMO_DB_PATH=data/memo.db\nLLM_API_KEY=keep\n", encoding="utf-8")

    plan = build_plan(root, env, target, legacy)
    assert plan["target_exists"] is False
    assert plan["legacy_configured"] is True

    result = apply_prepare(plan, root, env, target, backups)

    assert result["ok"] is True
    assert result["created_new_source_aware_db"] is True
    assert result["old_memo_db_is_runtime"] is False
    assert target.exists()
    assert legacy.read_bytes() == b"legacy-user-data"
    assert read_env_db_path(env, root) == target
    assert Path(result["backups"]["legacy_db"]["backup"]).read_bytes() == b"legacy-user-data"


def test_existing_source_aware_db_is_preserved_and_old_config_is_corrected(tmp_path: Path):
    root, _unused, target, legacy, backups = paths(tmp_path)
    env = root / ".env"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy-user-data")

    # First preparation creates a valid schema. Then add a sentinel user value.
    env.write_text("MEMO_DB_PATH=data/memo.db\n", encoding="utf-8")
    first = apply_prepare(build_plan(root, env, target, legacy), root, env, target, backups)
    assert first["created_new_source_aware_db"] is True
    before = target.read_bytes()

    env.write_text("MEMO_DB_PATH=data/memo.db\n", encoding="utf-8")
    second = apply_prepare(build_plan(root, env, target, legacy), root, env, target, backups)

    assert second["preserved_existing_source_aware_db"] is True
    assert second["created_new_source_aware_db"] is False
    assert target.read_bytes() == before
    assert read_env_db_path(env, root) == target
    assert legacy.exists()


def test_missing_databases_creates_source_aware_database_and_env(tmp_path: Path):
    root, _unused, target, legacy, backups = paths(tmp_path)
    env = root / ".env"

    result = apply_prepare(build_plan(root, env, target, legacy), root, env, target, backups)

    assert result["created_new_source_aware_db"] is True
    assert target.exists()
    assert not legacy.exists()
    assert read_env_db_path(env, root) == target
