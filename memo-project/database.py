"""数据库初始化 + 连接管理。

使用原生 sqlite3（零依赖），配合 FTS5 全文搜索。
迁移文件按编号顺序执行，用 schema_version 表跟踪。
"""

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from memo.core.config import config
from memo.utils.logger import logger


class Database:
    """SQLite 数据库管理器。"""

    _instance: "Database | None" = None
    _conn: sqlite3.Connection | None = None

    def __new__(cls) -> "Database":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            config.ensure_dirs()
            self._conn = sqlite3.connect(
                config.db_path,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            logger.info(f"数据库已连接: {config.db_path}")
        return self._conn

    def init(self) -> None:
        """执行全部迁移。"""
        self._ensure_schema_version_table()
        migrations_dir = Path(__file__).parent / "migrations"
        files = sorted(migrations_dir.glob("*.sql"))

        current = self._current_version()
        for f in files:
            version = f.stem.split("_")[0]  # "001"
            if int(version) > current:
                logger.info(f"执行迁移: {f.name}")
                self.conn.executescript(f.read_text(encoding="utf-8"))
                self._set_version(int(version))

        logger.info(f"数据库就绪，当前版本: {self._current_version()}")

    def _current_version(self) -> int:
        row = self.conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return row["version"] if row else 0

    def _set_version(self, version: int) -> None:
        self.conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (version,)
        )
        self.conn.commit()

    def _ensure_schema_version_table(self) -> None:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
        )
        self.conn.commit()

    def execute(self, sql: str, params: tuple | dict | None = None) -> sqlite3.Cursor:
        return self.conn.execute(sql, params or ())

    def execute_returning(self, sql: str, params: tuple | dict | None = None) -> sqlite3.Row | None:
        """执行 INSERT/UPDATE RETURNING id，返回结果。"""
        cur = self.conn.execute(sql, params or ())
        return cur.fetchone()

    def fetchone(self, sql: str, params: tuple | dict | None = None) -> sqlite3.Row | None:
        return self.conn.execute(sql, params or ()).fetchone()

    def fetchall(self, sql: str, params: tuple | dict | None = None) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params or ()).fetchall()

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


# 辅助函数
def new_id() -> str:
    """生成 UUID。"""
    return str(uuid.uuid4())


def blob_encode(array: Any) -> bytes:
    """将 numpy 数组编码为 BLOB。"""
    import numpy as np
    return np.asarray(array, dtype=np.float32).tobytes()


def blob_decode(data: bytes, dim: int = 512) -> Any:
    """将 BLOB 解码为 numpy 数组。"""
    import numpy as np
    arr = np.frombuffer(data, dtype=np.float32)
    return arr


def json_encode(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def json_decode(text: str) -> Any:
    return json.loads(text) if text else []


# 全局单例
db = Database()
