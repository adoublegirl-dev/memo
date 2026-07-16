"""Memo 数据库初始化 / 升级脚本。

默认只执行 engine.init()：完成 schema 检查、必要 migration、生产库迁移前自动备份。
不会写入测试记忆。需要端到端写入自检时显式传 --self-test，且建议在 MEMO_ENV=test 下运行。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from memo.core.config import config  # noqa: E402
from memo.core.engine import engine  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true", help="执行写入/检索自检，会写入当前 MEMO_ENV 对应数据库")
    args = parser.parse_args()

    print("=" * 50)
    print("Memo 数据库初始化 / 升级")
    print("=" * 50)
    print(f"MEMO_ENV: {config.memo_env}")
    print(f"DB: {config.db_path}")

    try:
        engine.init()
        print("✓ 数据库初始化 / migration 完成")
    except Exception as e:
        print(f"✗ 数据库初始化失败: {e}")
        return 1

    if not args.self_test:
        print("未执行写入自检。如需自检：set MEMO_ENV=test && python scripts/init_db.py --self-test")
        return 0

    if config.memo_env == "production":
        confirm = os.getenv("MEMO_ALLOW_PRODUCTION_SELF_TEST", "").lower() == "true"
        if not confirm:
            print("✗ 当前是 production，默认禁止写入自检。请改用 MEMO_ENV=test。")
            return 2

    print("\n--- 自检：写入测试记忆 ---")
    session = engine.start_session(title="自检会话")
    memory_id = engine.remember(
        session_id=session.id,
        raw_text="Memo 自检：验证数据库写入、向量编码、特征词和检索链路。",
        title="Memo 自检",
        summary="验证 Memo 数据库写入和检索链路。",
        summary_detail="通过测试记忆确认初始化后的数据库、向量、图谱、检索基础链路可用。",
        feature_tags=["Memo", "自检", "数据库"],
    )
    print(f"✓ 写入记忆: {memory_id[:8]}...")

    results = engine.recall("Memo 自检", top_k=3)
    print(f"✓ 检索到 {len(results)} 条结果")
    engine.end_session(session.id)
    print("自检完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
