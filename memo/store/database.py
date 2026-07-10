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
        """执行全部迁移。启动时自动修复 WAL 文件。"""
        # ── WAL 健康检查（安全：仅 checkpoint，绝不删除数据） ──
        self._repair_wal()

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

    def _repair_wal(self) -> None:
        """WAL 健康检查：安全 checkpoint，绝不删除数据。

        SQLite WAL 文件可能因进程被强制终止而残留。
        此方法执行 checkpoint 将 WAL 内容写入主库并截断 WAL，
        这是安全操作，不会丢失任何数据。
        如果 checkpoint 失败（WAL 损坏），记录错误但不删除文件，
        要求用户手动处理，以保护数据完整性。
        """
        import sqlite3 as _sqlite3
        wal_path = Path(config.db_path + "-wal")
        shm_path = Path(config.db_path + "-shm")

        if not wal_path.exists() and not shm_path.exists():
            return  # 无 WAL 残留，无需处理

        try:
            # TRUNCATE: checkpoint 成功后截断 WAL 文件
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.info("WAL checkpoint 完成")
        except _sqlite3.Error as e:
            # WAL 文件损坏——绝不删除，要求手动处理
            msg = (
                f"WAL checkpoint 失败: {e}\n"
                f"WAL 文件可能损坏，但数据库主文件完好。\n"
                f"请手动处理: {wal_path}\n"
                f"建议: 用 sqlite3 命令行工具执行 '.recover' 恢复数据。"
            )
            logger.error(msg)
            raise RuntimeError(msg) from e

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
