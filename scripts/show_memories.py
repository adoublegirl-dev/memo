import sys; import os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from memo.store.database import db; db.init()

print("=== Top 10 memories ===")
for r in db.fetchall('SELECT title, summary, memory_type, signal_level, created_at FROM memory_units ORDER BY created_at DESC LIMIT 10'):
    sl = ['auto','high','manual'][r['signal_level']] if r['signal_level'] in (0,1,2) else '?'
    print(f"[{r['memory_type']}][L{sl}] {r['title'][:60]}")

print("\n=== Top 10 tags ===")
for r in db.fetchall('SELECT name, storage_strength, retrieval_strength, total_activations FROM feature_tags ORDER BY (storage_strength*retrieval_strength) DESC LIMIT 10'):
    w = r['storage_strength'] * r['retrieval_strength']
    print(f"  {r['name']:20} w={w:.3f}  hit={r['total_activations']}")

print(f"\n=== Stats ===")
s = db.fetchone('SELECT COUNT(*) as c FROM sessions')
m = db.fetchone('SELECT COUNT(*) as c FROM memory_units')
t = db.fetchone('SELECT COUNT(*) as c FROM feature_tags')
r = db.fetchone('SELECT COUNT(*) as c FROM feature_relations')
print(f"Sessions:{s['c']} Memories:{m['c']} Tags:{t['c']} Relations:{r['c']}")
