import json
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "installer" / "path_contract.cjs"


def run_node(script: str):
    completed = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(completed.stdout)


def test_codex_config_discovers_custom_d_drive_root():
    config = """
[mcp_servers.memo]
command = 'D:\\memo\\memory\\Programs\\Memo\\runtime\\python.exe'
[mcp_servers.memo.env]
MEMO_USER_ROOT = 'D:\\memo\\memory'
MEMO_DATA_ROOT = 'D:\\memo\\memory\\data'
MEMO_DB_PATH = 'D:\\memo\\memory\\data\\memo_source_aware.db'
MEMO_RUNTIME_ROOT = 'D:\\memo\\memory\\Programs\\Memo\\runtime'
PYTHON_EXE = 'D:\\memo\\memory\\Programs\\Memo\\runtime\\python.exe'
"""
    script = f"const m=require({json.dumps(str(MODULE))}); console.log(JSON.stringify(m.parseCodexMemoEnv({json.dumps(config)})))"
    result = run_node(script)
    assert result["MEMO_USER_ROOT"] == r"D:\memo\memory"
    assert result["MEMO_DB_PATH"] == r"D:\memo\memory\data\memo_source_aware.db"


def test_runtime_path_infers_custom_user_root():
    script = f"const m=require({json.dumps(str(MODULE))}); console.log(JSON.stringify(m.inferRootFromRuntime('D:\\\\memo\\\\memory\\\\Programs\\\\Memo\\\\runtime\\\\python.exe')))"
    assert run_node(script).lower() == r"d:\memo\memory"


def test_valid_legacy_full_setting_beats_invalid_shared_setting():
    script = f"const m=require({json.dumps(str(MODULE))}); const rows=[{{userRoot:'C:\\\\Users\\\\x\\\\AppData\\\\Local\\\\Memo'}},{{userRoot:'D:\\\\memo\\\\memory'}}]; console.log(JSON.stringify(m.selectSettings(rows,p=>p.startsWith('D:'))))"
    assert run_node(script)["userRoot"] == r"D:\memo\memory"


def make_memo_root(root: Path):
    database = root / "data" / "memo_source_aware.db"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE memory_units(id INTEGER PRIMARY KEY, content TEXT)")
    (root / "Programs" / "Memo" / "runtime").mkdir(parents=True)
    (root / "Programs" / "Memo" / "runtime" / "python.exe").write_bytes(b"runtime")
    return database


def test_manual_selection_accepts_parent_root_data_database_and_program_directory(tmp_path):
    root = tmp_path / "memo" / "memory"
    database = make_memo_root(root)
    candidates = [tmp_path / "memo", root, root / "data", database, root / "Programs" / "Memo", root / "Programs" / "Memo" / "runtime"]
    for candidate in candidates:
        script = f"const m=require({json.dumps(str(MODULE))}); console.log(JSON.stringify(m.findMemoRootsNear({json.dumps(str(candidate))},3,500)))"
        result = run_node(script)
        assert str(root).lower() in [item.lower() for item in result]


def test_all_users_install_checks_original_user_and_admin_profiles():
    homes = [r"C:\Users\Administrator", r"C:\Users\锅锅"]
    script = f"const m=require({json.dumps(str(MODULE))}); console.log(JSON.stringify(m.profileEvidencePaths({json.dumps(homes, ensure_ascii=False)})))"
    result = run_node(script)
    assert r"C:\Users\锅锅\AppData\Roaming\memo-full-installer\memo-installer-settings.json" in result["settings"]
    assert r"C:\Users\锅锅\.codex\config.toml" in result["codex"]
    assert r"C:\Users\Administrator\.codex\config.toml" in result["codex"]


def test_sqlite_header_required_for_detected_database(tmp_path):
    root = tmp_path / "fake-memo"
    database = root / "data" / "memo_source_aware.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"not-a-real-database")
    script = f"const m=require({json.dumps(str(MODULE))}); console.log(JSON.stringify(m.hasMemoDatabase({json.dumps(str(root))})))"
    assert run_node(script) is False
