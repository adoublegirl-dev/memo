"""Memo 自动同步守护进程 —— 监控 HanaAgent 会话文件，自动写入 Memo。

原理：
  1. 找到最新的会话 JSONL 文件
  2. tail 监听新写入的消息行
  3. 当检测到一轮完整的 user → assistant 对话完成时
  4. 自动调用 Memo 的 remember_conversation 写入

启动方式：
  python scripts/memo_watcher.py

停止：Ctrl+C
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "E:/memo")

from memo.core.engine import engine
from memo.utils.logger import logger

# ── 配置 ──
SESSIONS_DIR = Path(os.path.expanduser("~/.hanako/agents/hanako/sessions"))
POLL_INTERVAL = 2  # 每 2 秒检查一次
MIN_MESSAGE_LENGTH = 30  # 跳过太短的消息（闲聊、嗯、好的等）


def find_latest_session() -> Path | None:
    """找到最新的会话文件。"""
    files = sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    return files[0] if files else None


def read_messages(filepath: Path) -> list[dict]:
    """读取会话文件中的所有消息。"""
    messages = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    if msg.get("type") == "message":
                        messages.append(msg)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.warning(f"读取会话文件失败: {e}")
    return messages


def extract_user_text(msgs: list[dict]) -> list[str]:
    """提取 user 消息的纯文本。"""
    texts = []
    for m in msgs:
        if m["message"]["role"] != "user":
            continue
        content = m["message"].get("content", "")
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
            )
        content = content.strip()
        if len(content) >= MIN_MESSAGE_LENGTH:
            texts.append(f"User: {content}")
    return texts


def extract_assistant_text(msgs: list[dict]) -> list[str]:
    """提取 assistant 消息的纯文本（跳过 thinking）。"""
    texts = []
    for m in msgs:
        if m["message"]["role"] != "assistant":
            continue
        content = m["message"].get("content", "")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    # 跳过 type=thinking
            content = " ".join(parts)
        content = content.strip()
        if len(content) >= MIN_MESSAGE_LENGTH:
            texts.append(f"Assistant: {content}")
    return texts


def format_turns(user_texts: list[str], assistant_texts: list[str]) -> list[str]:
    """将 user 和 assistant 的消息配对成对话轮次。"""
    turns = []
    max_len = max(len(user_texts), len(assistant_texts))
    for i in range(max_len):
        turn = ""
        if i < len(user_texts):
            turn += user_texts[i]
        if i < len(assistant_texts):
            if turn:
                turn += "\n"
            turn += assistant_texts[i]
        if turn.strip():
            turns.append(turn)
    return turns


def main():
    print("=" * 50)
    print("Memo 自动同步守护进程")
    print(f"监控目录: {SESSIONS_DIR}")
    print(f"轮询间隔: {POLL_INTERVAL} 秒")
    print("按 Ctrl+C 停止")
    print("=" * 50)

    engine.init()
    last_processed_count = 0
    current_file = None
    auto_session_id = engine.start_session("自动同步会话").id  # 复用同一个会话

    try:
        while True:
            latest = find_latest_session()
            if not latest:
                logger.debug("未找到会话文件")
                time.sleep(POLL_INTERVAL)
                continue

            # 切换会话文件时重置计数器
            if current_file != latest:
                current_file = latest
                last_processed_count = 0
                logger.info(f"监控新会话: {latest.name}")

            messages = read_messages(latest)
            total_msgs = len(messages)

            if total_msgs <= last_processed_count:
                time.sleep(POLL_INTERVAL)
                continue

            # 有新消息，提取新增的部分
            new_msgs = messages[last_processed_count:]
            user_texts = extract_user_text(new_msgs)
            assistant_texts = extract_assistant_text(new_msgs)

            # 当 assistant 回复后（一轮对话结束），写入 Memo
            if assistant_texts:
                # 取最近一轮对话的上下文
                recent_msgs = messages[max(0, total_msgs - 10):]  # 最近 10 条消息
                recent_users = extract_user_text(recent_msgs)
                recent_assistants = extract_assistant_text(recent_msgs)
                turns = format_turns(recent_users, recent_assistants)

                if turns:
                    conversation = "\n".join(turns[-2:])  # 最近 2 轮
                    try:
                        result = engine.remember_conversation(
                            session_id=auto_session_id,
                            conversation=conversation,
                            auto_extract=True,
                        )
                        logger.info(
                            f"✅ 自动同步: {result['title'][:40]} "
                            f"({len(result['feature_tags'])} 特征词)"
                        )
                    except Exception as e:
                        logger.warning(f"同步失败: {e}")

            last_processed_count = total_msgs
            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n守护进程已停止")


if __name__ == "__main__":
    main()
