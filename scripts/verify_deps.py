"""验证全部依赖。"""
import sys
sys.path.insert(0, "E:/memo")

from memo.store.database import db
db.init()
print("✓ 数据库初始化成功")

from memo.utils.embedding import embedding_model
emb = embedding_model.encode("测试")
print(f"✓ 嵌入模型就绪, dim={len(emb)}")

print("\n全部依赖验证通过！")
