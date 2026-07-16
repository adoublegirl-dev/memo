"""Pytest 隔离配置。

所有测试强制使用 data/memo_test.db，避免污染真实的 data/memo.db。
"""

import inspect
import os
import sys
import asyncio
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
TEST_DB = PROJECT_ROOT / "data" / "memo_test.db"


@pytest.fixture(autouse=True)
def isolate_memo_db():
    """每个测试都运行在独立测试库上。"""
    os.environ["MEMO_ENV"] = "test"
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db_after_session():
    """测试会话结束后清理测试数据库及 WAL/SHM。"""
    os.environ["MEMO_ENV"] = "test"
    yield
    try:
        from memo.store.database import db
        db.close()
    except Exception:
        pass
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(TEST_DB) + suffix)
        if path.exists():
            path.unlink()


def pytest_pyfunc_call(pyfuncitem):
    """在未安装 pytest-asyncio 时也能运行 async 测试函数。"""
    testfunction = pyfuncitem.obj
    if inspect.iscoroutinefunction(testfunction):
        kwargs = {
            name: pyfuncitem.funcargs[name]
            for name in pyfuncitem._fixtureinfo.argnames
            if name in pyfuncitem.funcargs
        }
        asyncio.run(testfunction(**kwargs))
        return True
    return None
