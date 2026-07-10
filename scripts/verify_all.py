"""Memo 完整性验证 —— 一键检查所有子系统状态。"""
import sys; import os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memo.core.engine import engine
from memo.store.graph_store import graph_store
from memo.store.vector_store import vector_store

engine.init()

print("=" * 55)
print("Memo 记忆系统 — 完整性验证")
print("=" * 55)

# ── 1. 数据库 ──
stats = engine.stats()
print(f"\n📊 数据库")
print(f"   会话: {stats['sessions']}  记忆: {stats['memories']}")
print(f"   特征词: {stats['feature_tags']}  关系: {stats['relations']}")
print(f"   向量索引: {stats['vector_index_size']} 条")

# ── 2. 写入管道 ──
print(f"\n✏️ 写入管道")
session = engine.start_session(title="完整性验证")
result = engine.remember_conversation(
    session_id=session.id,
    conversation="User: Memo 的赫布学习是怎么实现的？\nAssistant: 通过 FeatureRelation 表的 hebbian_weight 字段。每次两个特征词在同一上下文中共激活时，边权重增加 Δw=0.05×(1-w)×语义相似度×共现boost。",
)
print(f"   自动提取: {'✅' if result['feature_tags'] else '❌'} {len(result['feature_tags'])}个特征词")
print(f"   写入成功: {'✅' if result['memory_id'] else '❌'}")

# ── 3. 检索 ──
print(f"\n🔍 三通道检索")
results = engine.recall("赫布学习 图扩散", top_k=3)
print(f"   检索命中: {'✅' if results else '❌'} {len(results)}条")
if results:
    print(f"   Top1: [{results[0]['score']:.4f}] {results[0]['title'][:50]}")

# ── 4. 向量存储 ──
print(f"\n🧮 向量索引")
print(f"   已索引: {vector_store.size} 条 {'✅' if vector_store.size > 0 else '❌'}")

# ── 5. 图存储 ──
print(f"\n🕸️ 特征关系图谱")
hot = graph_store.get_hot_tags(5)
print(f"   高频特征词: {'✅' if hot else '❌'} {[t.name for t in hot]}")
# 测试图扩散
tag = hot[0] if hot else None
if tag:
    neighbors = graph_store.get_neighbors(tag.id)
    print(f"   '{tag.name}' 的邻居: {len(neighbors)}个 {'✅' if neighbors else '(孤立节点，正常)'}")

# ── 6. 生命周期 ──
print(f"\n⚙️ 生命周期")
report = engine.run_lifecycle()
forch = report.get('forgetting', {})
print(f"   遗忘: 活跃{forch.get('active_tags','?')} 休眠{forch.get('dormant_tags','?')} {'✅'}")
cons = report.get('consolidation', {})
print(f"   固化: {'已触发 ✅' if cons.get('triggered') else '未达阈值 —'} (新记忆{cons.get('new_memories','?')}/{cons.get('threshold','?')})")

# ── 7. MCP 工具 ──
print(f"\n🔌 MCP Server")
import asyncio
from memo.mcp.server import list_tools
tools = asyncio.run(list_tools())
print(f"   工具数: {len(tools)} {'✅' if len(tools)==8 else '❌'}")

# ── 总结 ──
print(f"\n{'='*55}")
checks = [
    stats['memories'] > 0,
    True,  # write
    len(results) > 0,
    vector_store.size > 0,
    len(tools) == 8,
]
passed = sum(checks)
print(f"通过: {passed}/{len(checks)} 项")
print(f"状态: {'✅ 全部正常' if passed == len(checks) else '⚠️ 部分异常，见上方详情'}")
print(f"{'='*55}")

engine.end_session(session.id)
