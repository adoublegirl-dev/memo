"""Memo 初始化 + 自检脚本。

首次运行前执行此脚本，或首次 import Engine 时自动执行。
"""

import sys
from pathlib import Path

# 确保项目路径在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from memo.core.engine import engine


def main():
    """初始化数据库 + 运行自检。"""
    print("=" * 50)
    print("Memo 记忆系统初始化")
    print("=" * 50)

    try:
        engine.init()
        print("✓ 数据库初始化成功")
    except Exception as e:
        print(f"✗ 数据库初始化失败: {e}")
        return 1

    # 自检：写入一条测试记忆
    print("\n--- 自检：写入测试记忆 ---")
    session = engine.start_session(title="自检会话")
    print(f"✓ 创建会话: {session.id[:8]}...")

    memory_id = engine.remember(
        session_id=session.id,
        raw_text="今天开始开发 Memo 记忆系统，目标是实现赫布学习 + 扩散激活的网状记忆图谱。",
        title="Memo 项目启动",
        summary="开始开发基于赫布学习和扩散激活的 Agent 记忆系统 Memo。",
        summary_detail="Memo 是一个活的、会进化的 Agent 记忆系统，采用三层架构（L0 热记忆体 + L1 特征关系图谱 + L2 冷存储），通过六维存储模型和赫布扩散激活实现跨会话的网状记忆关联。",
        feature_tags=["Memo", "记忆系统", "赫布学习", "扩散激活", "Agent"],
        tag_relations=[
            {"from": "赫布学习", "to": "扩散激活", "type": "CO_OCCUR"},
            {"from": "Memo", "to": "记忆系统", "type": "DERIVED"},
        ],
    )
    print(f"✓ 写入记忆: {memory_id[:8]}...")

    # 自检：检索
    print("\n--- 自检：检索 ---")
    results = engine.recall("赫布学习怎么用？", top_k=5)
    print(f"✓ 检索到 {len(results)} 条结果")
    for i, r in enumerate(results):
        print(f"  {i+1}. [{r['score']:.4f}] {r['title'][:50]}")

    # 统计
    print("\n--- 统计 ---")
    stats = engine.stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    engine.end_session(session.id)
    print("\n" + "=" * 50)
    print("自检通过！Memo 系统就绪。")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
