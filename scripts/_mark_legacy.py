"""标记所有现有记忆为测试数据，关联 __LEGACY_TEST__ 特征词。
以后执行 scripts/_clean_legacy.py 即可删除。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from memo.core.engine import engine
from memo.store.database import db
from memo.store.graph_store import graph_store
from memo.utils.embedding import embedding_model

engine.init()

# 获取所有现有记忆
rows = db.fetchall("SELECT id, title FROM memory_units WHERE is_superseded = 0")
print(f"现有记忆: {len(rows)} 条")

# 创建标记特征词
tag_name = "__LEGACY_TEST__"
emb = embedding_model.encode(tag_name)
tag = graph_store.get_or_create_tag(name=tag_name, category="CONCEPT", embedding=emb)
print(f"标记特征词: {tag.id[:8]}")

# 关联到所有现有记忆
count = 0
for row in rows:
    existing = db.fetchone(
        "SELECT 1 FROM tag_mentions WHERE tag_id = ? AND memory_unit_id = ?",
        (tag.id, row["id"])
    )
    if not existing:
        graph_store.create_mention(
            tag_id=tag.id,
            memory_unit_id=row["id"],
            mention_type="DIRECT",
            relevance_score=1.0,
        )
        count += 1

print(f"已标记: {count} 条记忆")
print("\n以后执行 python scripts/_clean_legacy.py 即可清理这些测试数据")
