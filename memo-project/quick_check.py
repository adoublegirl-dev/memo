"""快速自检 —— 不依赖 LLM 和嵌入模型。"""
import sys
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memo.store.database import db

print("初始化数据库...")
db.init()

print("\n创建的表:")
for row in db.fetchall("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
    print(f"  ✓ {row['name']}")

print(f"\n数据库路径: {db._conn}")
print("Phase 0 基础设施验证通过！")
