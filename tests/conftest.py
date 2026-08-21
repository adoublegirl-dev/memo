"""Pytest isolation configuration.

Tests must never share the project data directory or an installed Memo user
root. A unique OS-temp root is selected before test modules import Memo, so
module-level singletons also receive the isolated paths.
"""

import asyncio
import inspect
import os
import tempfile
import uuid
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSION_TEST_ROOT = Path(tempfile.gettempdir()) / f"memo-pytest-{uuid.uuid4().hex}"
SESSION_DATA_ROOT = SESSION_TEST_ROOT / "data"
SESSION_DB = SESSION_DATA_ROOT / "memo_test.db"

# Set these at conftest import time, before pytest imports test modules that may
# import memo.core.config or create database/vector-store singletons.
os.environ["MEMO_ENV"] = "test"
os.environ["MEMO_USER_ROOT"] = str(SESSION_TEST_ROOT)
os.environ["MEMO_DATA_ROOT"] = str(SESSION_DATA_ROOT)
os.environ["MEMO_DB_PATH"] = str(SESSION_DB)


@pytest.fixture(autouse=True)
def isolate_memo_db(monkeypatch):
    """Keep every test in the session's dedicated temporary Memo root."""
    monkeypatch.setenv("MEMO_ENV", "test")
    monkeypatch.setenv("MEMO_USER_ROOT", str(SESSION_TEST_ROOT))
    monkeypatch.setenv("MEMO_DATA_ROOT", str(SESSION_DATA_ROOT))
    monkeypatch.setenv("MEMO_DB_PATH", str(SESSION_DB))
    yield


@pytest.fixture(scope="session", autouse=True)
def close_test_database_after_session():
    """Close handles only; never delete DB/WAL/SHM as part of a test hook."""
    yield
    try:
        from memo.store.database import db
        db.close()
    except Exception:
        pass


def pytest_pyfunc_call(pyfuncitem):
    """Run async tests even when pytest-asyncio is not installed."""
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
