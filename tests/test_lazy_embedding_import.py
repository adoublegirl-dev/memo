"""Torch / sentence-transformers must be imported only on first embedding use.

Every assertion runs in a subprocess with a temporary Memo data root. This is
both closer to real cold start behavior and avoids unloading/re-importing Torch
inside pytest, which is unsupported by Torch's global operator registry.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_isolated(code: str, tmp_path: Path) -> dict:
    data_root = tmp_path / "memo-data"
    env = {
        **os.environ,
        "MEMO_USER_ROOT": str(tmp_path / "memo-user"),
        "MEMO_DATA_ROOT": str(data_root),
        "MEMO_DB_PATH": str(data_root / "memo_source_aware.db"),
    }
    env.pop("MEMO_ENV", None)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_import_memo_core_engine_does_not_load_torch_or_sentence_transformers(tmp_path):
    result = run_isolated(
        "import json,sys; import memo.core.engine; "
        "print(json.dumps({'torch': 'torch' in sys.modules, 'st': 'sentence_transformers' in sys.modules}))",
        tmp_path,
    )
    assert result == {"torch": False, "st": False}


def test_first_encode_imports_and_calls_model(tmp_path):
    code = r'''
import json,sys,types
import numpy as np
calls = {"construct": 0, "encode": 0}
class FakeModel:
    def __init__(self, name):
        calls["construct"] += 1
        calls["name"] = name
    def get_embedding_dimension(self): return 512
    def encode(self, text, **kwargs):
        calls["encode"] += 1
        return np.zeros((1, 512), dtype=np.float32)
fake = types.ModuleType("sentence_transformers")
fake.SentenceTransformer = FakeModel
sys.modules["sentence_transformers"] = fake
from memo.utils.embedding import EmbeddingModel
emb = object.__new__(EmbeddingModel)
emb._model = None
vector = emb.encode("hello memo")
print(json.dumps({**calls, "shape": list(vector.shape)}))
'''
    result = run_isolated(code, tmp_path)
    assert result["construct"] == 1
    assert result["encode"] == 1
    assert result["shape"] == [1, 512]


def test_encode_batch_uses_lazily_loaded_model(tmp_path):
    code = r'''
import json,sys,types
import numpy as np
calls = {"construct": 0, "encode": 0}
class FakeModel:
    def __init__(self, name): calls["construct"] += 1
    def get_embedding_dimension(self): return 512
    def encode(self, texts, **kwargs):
        calls["encode"] += 1
        calls["batch_size"] = kwargs.get("batch_size")
        return np.zeros((len(texts), 512), dtype=np.float32)
fake = types.ModuleType("sentence_transformers")
fake.SentenceTransformer = FakeModel
sys.modules["sentence_transformers"] = fake
from memo.utils.embedding import EmbeddingModel
emb = object.__new__(EmbeddingModel)
emb._model = None
vectors = emb.encode_batch(["a", "b"], batch_size=2)
print(json.dumps({**calls, "shape": list(vectors.shape)}))
'''
    result = run_isolated(code, tmp_path)
    assert result["construct"] == 1
    assert result["encode"] == 1
    assert result["batch_size"] == 2
    assert result["shape"] == [2, 512]
