import sys; import os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from memo.store.database import db; db.init()

print("=== 搜索 '12348' ===")
for r in db.fetchall("SELECT title, summary, memory_type FROM memory_units WHERE raw_text LIKE ? OR summary LIKE ? OR title LIKE ? LIMIT 5",
                     ('%12348%', '%12348%', '%12348%')):
    print(f"[{r['memory_type']}] {r['title'][:60]}")
    if r['summary']:
        print(f"  {r['summary'][:200]}")

print()
print("=== 搜索 '爬虫' ===")
for r in db.fetchall("SELECT title, summary, memory_type FROM memory_units WHERE raw_text LIKE ? OR summary LIKE ? OR title LIKE ? LIMIT 5",
                     ('%爬虫%', '%爬虫%', '%爬虫%')):
    print(f"[{r['memory_type']}] {r['title'][:60]}")
    if r['summary']:
        print(f"  {r['summary'][:200]}")

print()
print("=== 最近 10 分钟写入的记忆 ===")
for r in db.fetchall("SELECT title, summary, created_at FROM memory_units ORDER BY created_at DESC LIMIT 5"):
    print(f"[{r['created_at'][:16]}] {r['title'][:60]}")
