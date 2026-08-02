import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_uses_external_user_env_and_data_root(tmp_path: Path):
    data_root = tmp_path / "Memo" / "data"
    env_file = tmp_path / "Memo" / "config" / ".env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("LLM_API_KEY=test-key\n", encoding="utf-8")
    env = os.environ.copy()
    env.update({"MEMO_ENV": "production", "MEMO_DATA_ROOT": str(data_root), "MEMO_ENV_FILE": str(env_file)})
    script = "from memo.core.config import config; print(config.db_path); print(config.llm_api_key); config.ensure_dirs()"
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    lines = result.stdout.strip().splitlines()
    assert lines[0] == str(data_root / "memo_source_aware.db")
    assert lines[1] == "test-key"
    assert (data_root / "logs").is_dir()
    assert (data_root / "pids").is_dir()
    assert (data_root / "backups").is_dir()
