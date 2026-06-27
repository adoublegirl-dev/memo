"""去重模块 —— 检测并合并重复记忆。"""

from memo.store.database import db
from memo.store.vector_store import vector_store
from memo.utils.logger import logger


def find_duplicates(memory_id: str, threshold: float = 0.92) -> list[str]:
    """查找与指定记忆高度相似的其他记忆。

    Returns:
        重复记忆 ID 列表（相似度 > threshold）
    """
    # 获取目标记忆的嵌入
    row = db.fetchone(
        "SELECT embedding, title FROM memory_units WHERE id = ?", (memory_id,)
    )
    if not row or not row["embedding"]:
        return []

    # 用向量检索找相似记忆
    query_text = row["title"]
    results = vector_store.search(query_text, top_k=10)

    duplicates = []
    for mem_id, score in results:
        if mem_id != memory_id and score > threshold:
            duplicates.append(mem_id)

    if duplicates:
        logger.info(f"发现重复记忆: {memory_id[:8]} 与 {[d[:8] for d in duplicates]}")

    return duplicates
