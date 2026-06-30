import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from memo.integration import MemoClient
c = MemoClient()

r = c.remember("V0.2.0升级完成：新增MemoClient直接集成、memo_watcher自动同步守护进程、Web看板、一键启停脚本")
print(f"SAVED: {r['title']}")

res = c.recall("V0.2.0新增了什么", top_k=3)
for rr in res:
    print(f"[{rr['score']:.4f}] {rr['title'][:60]}")

s = c.stats()
print(f"STATS: {s['sessions']}会话 {s['memories']}记忆")
