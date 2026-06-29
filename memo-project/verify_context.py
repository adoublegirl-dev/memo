"""验证上下文感知提取 —— 同会话连续写入，检查第三条是否融合前文信息。"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from memo.core.engine import engine

engine.init()

# 新建会话
session = engine.start_session(title="上下文感知验证")
print(f"会话: {session.id[:8]}...")

# ── 第一轮：讨论技术选型 ──
def get_mem(id):
    """从数据库读取记忆详情。"""
    from memo.store.database import db
    row = db.fetchone(
        "SELECT title, summary, summary_detail, raw_text FROM memory_units WHERE id = ?",
        (id,)
    )
    return row

r1 = engine.remember_conversation(
    session_id=session.id,
    conversation="User: 我们在考虑用 PostgreSQL 还是 MySQL 做用户数据存储\n"
                 "Assistant: PostgreSQL 对 JSON 查询支持更好，而且有更强大的全文搜索",
    context_rounds=3,
)
m1 = get_mem(r1['memory_id'])
print(f"\n[第1条] 标题: {r1['title']}")
print(f"  摘要: {m1['summary'][:100] if m1 else 'N/A'}")
print(f"  特征词: {', '.join(r1['feature_tags'])}")
print(f"  上下文参考: {r1['context_rounds_used']} 轮（应为 0，还没历史）")

# ── 第二轮：决定用 PG，讨论细节 ──
r2 = engine.remember_conversation(
    session_id=session.id,
    conversation="User: 那就用 PostgreSQL 吧，我们还要给用户表加一个 last_login_ip 字段\n"
                 "Assistant: 好的，可以用 inet 类型存储 IP，PostgreSQL 原生支持",
    context_rounds=3,
)
m2 = get_mem(r2['memory_id'])
print(f"\n[第2条] 标题: {r2['title']}")
print(f"  摘要: {m2['summary'][:100] if m2 else 'N/A'}")
print(f"  特征词: {', '.join(r2['feature_tags'])}")
print(f"  上下文参考: {r2['context_rounds_used']} 轮（应为 1，第1条作为上下文）")

# ── 第三轮：追问索引策略（期望 LLM 利用上下文补全决策背景） ──
r3 = engine.remember_conversation(
    session_id=session.id,
    conversation="User: 那这个 IP 字段需要建索引吗？查询量不大\n"
                 "Assistant: 如果查询量不大可以先不建。但用户登录时需要按邮箱+IP 做防刷检查，"
                 "建议在建用户表时就加上 email + last_login_ip 的联合索引",
    context_rounds=3,
)
m3 = get_mem(r3['memory_id'])
print(f"\n[第3条] 标题: {r3['title']}")
print(f"  摘要: {m3['summary'][:150] if m3 else 'N/A'}")
print(f"  二级摘要: {m3['summary_detail'][:200] if m3 else 'N/A'}")
print(f"  特征词: {', '.join(r3['feature_tags'])}")
print(f"  上下文参考: {r3['context_rounds_used']} 轮（应为 2，前2条作为上下文）")

# ── 验证结论 ──
print("\n" + "=" * 60)
print("验证结论：")
summary_text = ((m3['summary'] if m3 else '') + (m3['summary_detail'] if m3 else '')).lower()

# 检查第三条摘要是否体现了前文的上下文
checks = []
if "postgresql" in summary_text or "pg" in summary_text or "选型" in summary_text:
    checks.append("✅ 摘要包含了前文技术选型上下文（PostgreSQL）")
else:
    checks.append("❌ 摘要未引用前文技术选型信息")

if "用户表" in summary_text or "登录" in summary_text:
    checks.append("✅ 摘要包含了本轮的索引讨论内容")
else:
    checks.append("❌ 摘要缺失本轮核心内容")

print(f"  上下文轮数: {r3['context_rounds_used']} / 期望 2")
for c in checks:
    print(f"  {c}")

print("\n所有记忆 raw_text 预览：")
for i, r in enumerate([r1, r2, r3]):
    mem_id = r['memory_id']
    # 直接从数据库查 raw_text
    from memo.store.database import db
    row = db.fetchone("SELECT raw_text FROM memory_units WHERE id = ?", (mem_id,))
    raw = row['raw_text'][:80] if row else 'N/A'
    print(f"  记忆{i+1}: {raw}...")

engine.end_session(session.id)
print("\n验证完成！")
