from pathlib import Path

from scripts.archive_current_db import PROJECT_ROOT, _db_path_from_env_file, build_plan, dry_run_report, execute_archive, sha256_file


def test_archive_reads_source_aware_path_from_install_env(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("# comment\nMEMO_DB_PATH=data/memo_source_aware.db\n", encoding="utf-8")

    assert _db_path_from_env_file(env) == PROJECT_ROOT / "data" / "memo_source_aware.db"


def test_archive_reads_absolute_path_from_install_env(tmp_path: Path):
    env = tmp_path / ".env"
    expected = tmp_path / "external" / "memo.db"
    env.write_text(f'MEMO_DB_PATH="{expected}"\n', encoding="utf-8")

    assert _db_path_from_env_file(env) == expected


def test_archive_current_db_dry_run_does_not_create_files(tmp_path: Path):
    db = tmp_path / "memo.db"
    env = tmp_path / ".env"
    backup_dir = tmp_path / "backups"
    db.write_bytes(b"memo-db-sample")
    env.write_text("LLM_API_KEY=test\n", encoding="utf-8")

    plan = build_plan(db, env, backup_dir, dry_run=True, label="test")
    report = dry_run_report(plan)

    assert report["plan"]["dry_run"] is True
    assert report["would_copy"]["db"]["exists"] is True
    assert not backup_dir.exists()


def test_archive_current_db_apply_copies_db_and_env(tmp_path: Path):
    db = tmp_path / "memo.db"
    env = tmp_path / ".env"
    backup_dir = tmp_path / "backups"
    db.write_bytes(b"memo-db-sample")
    env.write_text("LLM_API_KEY=test\n", encoding="utf-8")

    plan = build_plan(db, env, backup_dir, dry_run=False, label="test")
    result = execute_archive(plan)

    db_backup = Path(result["copied"]["db"]["path"])
    env_backup = Path(result["copied"]["env"]["path"])
    manifest = Path(result["manifest"]["path"])

    assert db.exists()
    assert env.exists()
    assert db_backup.exists()
    assert env_backup.exists()
    assert manifest.exists()
    assert sha256_file(db) == sha256_file(db_backup)
    assert sha256_file(env) == sha256_file(env_backup)


def test_archive_current_db_wal_shm_are_warn_only(tmp_path: Path):
    db = tmp_path / "memo.db"
    env = tmp_path / ".env"
    backup_dir = tmp_path / "backups"
    wal = tmp_path / "memo.db-wal"
    shm = tmp_path / "memo.db-shm"
    db.write_bytes(b"memo-db-sample")
    env.write_text("LLM_API_KEY=test\n", encoding="utf-8")
    wal.write_bytes(b"wal")
    shm.write_bytes(b"shm")

    plan = build_plan(db, env, backup_dir, dry_run=False, label="test")
    result = execute_archive(plan)

    assert result["wal_shm"]["copied"] is False
    assert result["wal_shm"]["deleted"] is False
    assert wal.exists()
    assert shm.exists()
    assert not (backup_dir / "memo.db-wal").exists()
    assert not (backup_dir / "memo.db-shm").exists()
