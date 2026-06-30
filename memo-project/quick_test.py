import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from memo.core.engine import engine
engine.init()

s = engine.start_session(title="MCP测试")
r = engine.remember_conversation(
    session_id=s.id,
    conversation="User: 这是个memo的mcp测试",
    context_rounds=0,
)
print(f"SAVED|{r['memory_id'][:8]}|{r['title']}")

res = engine.recall("memo mcp测试", top_k=3)
for rr in res:
    print(f"RECALL|{rr['score']:.4f}|{rr['title'][:60]}")
