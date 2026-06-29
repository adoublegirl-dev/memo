"""批量导入 HanaAgent 历史会话到 Memo。
"""

import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import json
import sys
from pathlib import Path

sys.path.insert(0, "E:/memo")
from memo.core.engine import engine
from memo.utils.logger import logger

SESSIONS_DIR = Path.home() / ".hanako" / "agents" / "hanako" / "sessions"
MIN_TURN_LENGTH = 30  # 跳过太短的对话轮次


def extract_turns(messages: list[dict]) -> list[str]:
    """从消息列表提取 user+assistant 对话轮次。跳过 tool/toolResult/thinking。"""
    turns = []
    current_turn = []

    for msg in messages:
        role = msg.get("message", {}).get("role", "")
        content = msg.get("message", {}).get("content", "")

        # 处理 content 可能是列表的情况
        if isinstance(content, list):
            texts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    texts.append(part.get("text", ""))
            content = " ".join(texts)

        content = content.strip()
        if not content or len(content) < MIN_TURN_LENGTH:
            continue

        if role == "user":
            # 遇到新 user 消息，保存之前的轮次
            if current_turn:
                turns.append("\n".join(current_turn))
            current_turn = [f"User: {content}"]

        elif role == "assistant":
            if current_turn:
                current_turn.append(f"Assistant: {content}")

    # 最后一轮
    if current_turn:
        turns.append("\n".join(current_turn))

    return turns


def read_session(filepath: Path) -> list[dict]:
    """读取 JSONL 会话文件。"""
    messages = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if msg.get("type") == "message":
                    # 跳过 MCP 工具调用的原始输出
                    role = msg.get("message", {}).get("role", "")
                    if role not in ("user", "assistant"):
                        continue
                    messages.append(msg)
            except json.JSONDecodeError:
                continue
    return messages


def main():
    engine.init()

    files = sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda f: f.stat().st_size, reverse=True)
    logger.info(f"找到 {len(files)} 个会话文件")

    total_turns = 0
    written_count = 0
    skipped_count = 0

    for i, filepath in enumerate(files):
        size_mb = filepath.stat().st_size / (1024 * 1024)
        logger.info(f"[{i+1}/{len(files)}] {filepath.name} ({size_mb:.1f} MB)")

        try:
            messages = read_session(filepath)
            turns = extract_turns(messages)
            total_turns += len(turns)

            if not turns:
                logger.info(f"  → 无有效对话轮次，跳过")
                skipped_count += 1
                continue

            # 为每个会话创建独立 session
            session = engine.start_session(title=filepath.stem[:50])

            for j, turn in enumerate(turns):
                # 跳过太长的单轮（可能是代码块或日志）
                if len(turn) > 5000:
                    turn = turn[:5000]

                try:
                    result = engine.remember_conversation(
                        session_id=session.id,
                        conversation=turn,
                        context_rounds=2,  # 回顾前 2 轮
                        auto_extract=True,
                    )
                    written_count += 1
                    logger.info(
                        f"  [{j+1}/{len(turns)}] {result['title'][:40]} "
                        f"({len(result['feature_tags'])} tags)"
                    )
                except Exception as e:
                    logger.warning(f"  写入失败 [{j+1}]: {e}")
                    skipped_count += 1

            engine.end_session(session.id)

        except Exception as e:
            logger.error(f"  处理失败: {e}")
            skipped_count += 1

    logger.info(f"完成: {total_turns} 轮对话, 写入 {written_count} 条, 跳过 {skipped_count}")
    print(f"\n{'='*50}")
    print(f"导入完成: {written_count} 条记忆")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
