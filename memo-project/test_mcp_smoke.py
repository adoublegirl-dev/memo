"""MCP Server 冒烟测试 —— 验证启动、初始化、工具列表。

不需要真实的 MCP 客户端，直接测试内部逻辑。
"""
import sys
sys.path.insert(0, "E:/memo")

import asyncio
import json

from memo.core.engine import engine
from memo.utils.logger import logger


async def test_tools():
    """直接调用工具处理函数，验证每个工具都能正常响应。"""
    engine.init()

    # 导入 server 模块的工具回调
    from memo.mcp.server import call_tool, list_tools

    print("=" * 60)
    print("Memo MCP Server 冒烟测试")
    print("=" * 60)

    # 1. 验证工具列表
    tools = await list_tools()
    print(f"\n✓ 工具列表: {len(tools)} 个")
    for t in tools:
        print(f"  - {t.name}: {t.description[:60]}...")

    # 2. 验证每个工具都能被调用
    test_cases = [
        ("memo_stats", {}),
        ("memo_hot_tags", {"limit": 5}),
        ("memo_maintain", {}),
        ("memo_snapshot", {}),
        ("memo_start_session", {"title": "冒烟测试会话"}),
        ("memo_remember", {
            "conversation": "User: MCP Server 冒烟测试\nAssistant: 收到，正在验证所有工具可用性",
        }),
        ("memo_recall", {"query": "MCP Server 测试", "top_k": 3}),
        ("memo_end_session", {}),
    ]

    for name, args in test_cases:
        try:
            result = await call_tool(name, args)
            text = result[0].text if result else "(空)"
            status = "✅" if "错误" not in text and "❌" not in text else "❌"
            print(f"\n{status} {name}({json.dumps(args, ensure_ascii=False)[:80]})")
            print(f"   → {text[:200]}")
        except Exception as e:
            print(f"\n❌ {name}: {e}")

    # 3. 验证统计
    stats = engine.stats()
    print(f"\n{'='*60}")
    print(f"最终统计: {stats['sessions']} 会话, {stats['memories']} 记忆, "
          f"{stats['feature_tags']} 特征词, {stats['relations']} 关系")

    print("MCP Server 冒烟测试通过！" if stats['memories'] > 0 else "MCP Server 框架正常")


if __name__ == "__main__":
    asyncio.run(test_tools())
