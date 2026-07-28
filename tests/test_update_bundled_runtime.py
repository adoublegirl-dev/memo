from pathlib import Path

from scripts.update_bundled_runtime import overlay_runtime


def test_overlay_runtime_updates_code_and_preserves_local_data(tmp_path: Path):
    source = tmp_path / "source"
    target = tmp_path / "target"

    for root in (source, target):
        (root / "memo").mkdir(parents=True)
        (root / "scripts").mkdir(parents=True)
        (root / "dashboard" / "dist").mkdir(parents=True)

    (source / "memo" / "service.py").write_text("new-service", encoding="utf-8")
    (source / "scripts" / "worker.py").write_text("new-worker", encoding="utf-8")
    (source / "dashboard" / "dist" / "index.html").write_text("new-dashboard", encoding="utf-8")
    (source / "start_all.bat").write_text("new-start", encoding="utf-8")

    (target / "memo" / "service.py").write_text("old-service", encoding="utf-8")
    (target / "data").mkdir()
    (target / "data" / "memo_source_aware.db").write_text("user-db", encoding="utf-8")
    (target / "data" / "memo_source_aware.db-wal").write_text("user-wal", encoding="utf-8")
    (target / ".env").write_text("SECRET=keep", encoding="utf-8")
    (target / "desktop").mkdir()
    (target / "desktop" / "main.cjs").write_text("installed-shell", encoding="utf-8")

    result = overlay_runtime(source, target)

    assert result["copied_count"] == 4
    assert (target / "memo" / "service.py").read_text(encoding="utf-8") == "new-service"
    assert (target / "scripts" / "worker.py").read_text(encoding="utf-8") == "new-worker"
    assert (target / "dashboard" / "dist" / "index.html").read_text(encoding="utf-8") == "new-dashboard"
    assert (target / "start_all.bat").read_text(encoding="utf-8") == "new-start"
    assert (target / "data" / "memo_source_aware.db").read_text(encoding="utf-8") == "user-db"
    assert (target / "data" / "memo_source_aware.db-wal").read_text(encoding="utf-8") == "user-wal"
    assert (target / ".env").read_text(encoding="utf-8") == "SECRET=keep"
    assert (target / "desktop" / "main.cjs").read_text(encoding="utf-8") == "installed-shell"
