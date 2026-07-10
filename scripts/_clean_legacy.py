"""清理标记为 __LEGACY_TEST__ 的测试数据。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memo.store.database import db
from memo.store.graph_store import graph_store
from memo.utils.logger import logger

db.init()

# 找到标记特征词
tag = db.fetchone("SELECT id FROM feature_tags WHERE name = '__LEGACY_TEST__'")
if not tag:
    print("未找到 __LEGACY_TEST__ 标记，无需清理。")
    exit(0)

# 找到所有被标记的记忆
rows = db.fetchall(
    "SELECT mu.id, mu.title FROM memory_units mu "
    "JOIN tag_mentions tm ON mu.id = tm.memory_unit_id "
    "WHERE tm.tag_id = ?",
    (tag["id"],)
)
print(f"找到 {len(rows)} 条待清理记忆")

# 删除
for row in rows:
    # 删除记忆单元
    db.execute("DELETE FROM memory_units WHERE id = ?", (row["id"],))
    # 删除向量（memory_fts）
    db.execute("DELETE FROM memory_fts_data WHERE rowid = (SELECT rowid FROM memory_units WHERE id = ?)", (row["id"],))
    # 删除关联
    db.execute("DELETE FROM tag_mentions WHERE memory_unit_id = ?", (row["id"],))
    print(f"  已删除: {row['title'][:50]}")

# 删除标记特征词本身
db.execute("DELETE FROM tag_mentions WHERE tag_id = ?", (tag["id"],))
db.execute("DELETE FROM feature_tags WHERE id = ?", (tag["id"],))
db.commit()

remaining = db.fetchone("SELECT COUNT(*) as c FROM memory_units")
print(f"\n清理完成！剩余记忆: {remaining['c']} 条")
