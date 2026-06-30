"""在当前会话中使用 Memo 记忆系统——记录和调用。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from memo.core.engine import engine

engine.init()

# ── 开始会话 ──
session = engine.start_session(title="Memo项目改造讨论")
print(f"📂 会话: {session.id[:8]}...")

# ── 记录今天的核心内容 ──
r1 = engine.remember_conversation(
    session_id=session.id,
    conversation=(
        "User: 从GitHub clone了memo项目，代码是扁平结构但导入用包路径。\n"
        "Assistant: 需要重构目录结构，按memo/core/store/utils/models等包组织。"
        "同时发现models模块缺失，FeatureTag/MemoryUnit等类只有import没定义。"
        "根据architecture.md补全了六维存储模型。"
    ),
    context_rounds=3,
)
print(f"\n📝 第1条: {r1['title'][:50]}")
print(f"   特征词: {', '.join(r1['feature_tags'])}")
print(f"   ID: {r1['memory_id'][:8]}")

r2 = engine.remember_conversation(
    session_id=session.id,
    conversation=(
        "User: 需要改造remember功能，让LLM在提取时参考同会话前几轮对话原文。\n"
        "Assistant: 在extractor.py的prompt中增加上下文区域，engine.py中"
        "remember_conversation新增context_rounds参数（默认3），"
        "自动查询同session最近N条记忆的raw_text传给提取器。"
    ),
    context_rounds=3,
)
print(f"\n📝 第2条: {r2['title'][:50]}")
print(f"   特征词: {', '.join(r2['feature_tags'])}")
print(f"   上下文参考: {r2['context_rounds_used']} 轮")
print(f"   ID: {r2['memory_id'][:8]}")

# ── 检索验证 ──
print("\n" + "=" * 50)
print("🔍 检索: 「上下文感知提取怎么实现的」")
results = engine.recall("上下文感知提取怎么实现的", top_k=3)
for i, r in enumerate(results):
    print(f"  {i+1}. [{r['score']:.4f}] {r['title'][:60]}")

# ── 统计 ──
stats = engine.stats()
print(f"\n📊 统计: {stats['sessions']}会话 {stats['memories']}记忆 {stats['feature_tags']}特征词 {stats['relations']}关系")

engine.end_session(session.id)
print("\n✅ 记录 + 检索 都跑通了")
