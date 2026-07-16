"""Context Space 自动识别。

Detector 只给候选，不替调用方做最终切换决策。
"""

from __future__ import annotations

from memo.space.manager import space_manager
from memo.store.database import blob_decode, db
from memo.utils.embedding import embedding_model


class SpaceDetector:
    """基于名称、别名和 Space centroid 的轻量识别器。"""

    def detect(self, text: str, top_k: int = 3) -> list[dict]:
        query = (text or "").strip()
        if not query:
            return []

        spaces = space_manager.list(include_archived=False)
        if not spaces:
            return []

        query_emb = embedding_model.encode(query)
        candidates: list[dict] = []

        for space in spaces:
            score = 0.0
            reasons: list[str] = []
            name = space.get("name", "")
            if name and name.lower() in query.lower():
                score += 0.45
                reasons.append(f"命中名称 {name}")

            aliases = db.fetchall("SELECT alias FROM space_aliases WHERE space_id = ?", (space["id"],))
            matched_aliases = [a["alias"] for a in aliases if a["alias"] and a["alias"].lower() in query.lower()]
            if matched_aliases:
                score += 0.35
                reasons.append("命中别名 " + ", ".join(matched_aliases[:3]))

            row = db.fetchone("SELECT centroid_embedding FROM spaces WHERE id = ?", (space["id"],))
            if row and row["centroid_embedding"]:
                centroid = blob_decode(row["centroid_embedding"])
                sim = float(query_emb.dot(centroid))
                # 将 cosine 近似映射到 0~0.35 的贡献区间
                score += max(0.0, min(0.35, (sim - 0.35) * 0.7))
                if sim > 0.45:
                    reasons.append(f"语义相似度 {sim:.2f}")

            if score > 0:
                candidates.append({
                    "space_id": space["id"],
                    "name": name,
                    "type": space.get("type", "general"),
                    "confidence": round(min(score, 1.0), 3),
                    "reason": "；".join(reasons) or "语义候选",
                })

        candidates.sort(key=lambda x: x["confidence"], reverse=True)
        return candidates[:top_k]

    def suggest_new(self, text: str) -> dict | None:
        """给出新 Space 建议。第一版只返回空，避免自动造空间污染。"""
        return None


space_detector = SpaceDetector()
