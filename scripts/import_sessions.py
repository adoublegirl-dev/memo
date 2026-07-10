"""批量导入 HanaAgent 历史会话到 Memo。
"""

import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import json
import sys
from pathlib import Path

import os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
    import argparse
    parser = argparse.ArgumentParser(description="导入 HanaAgent 历史会话到 Memo")
    parser.add_argument("--skip-cas", action="store_true", help="跳过 CAS 变更检测")
    parser.add_argument("--restart", action="store_true", help="强制从头开始（忽略进度文件）")
    args = parser.parse_args()

    # ── 进度管理：自动检测断点 ──
    progress_file = Path("data/import_progress.json")
    progress = {"completed_sessions": [], "last_session_file": "", "last_turn_index": -1, "total_written": 0}

    if args.restart and progress_file.exists():
        progress_file.unlink()
        logger.info("已重置进度文件，从头开始")
    elif progress_file.exists():
        progress = json.loads(progress_file.read_text(encoding="utf-8"))
        if progress.get("total_written", 0) > 0:
            logger.info(
                f"检测到上次进度: {progress['total_written']} 条已写入, "
                f"{len(progress.get('completed_sessions', []))} 个会话已完成。自动续传。"
                f"（用 --restart 可强制重跑）"
            )
            args.resume = True  # 自动续传
        else:
            args.resume = False
    else:
        args.resume = False

    def save_progress(filepath: Path, turn_idx: int):
        progress["last_session_file"] = filepath.name
        progress["last_turn_index"] = turn_idx
        tmp = progress_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(progress_file)  # 原子操作

    engine.init()

    files = sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda f: f.stat().st_size, reverse=True)
    logger.info(f"找到 {len(files)} 个会话文件")

    total_turns = 0
    written_count = 0
    skipped_count = 0

    for i, filepath in enumerate(files):
        size_mb = filepath.stat().st_size / (1024 * 1024)

        # 跳过已完成的会话
        if args.resume and filepath.name in progress.get("completed_sessions", []):
            logger.info(f"[{i+1}/{len(files)}] {filepath.name} ({size_mb:.1f} MB) — 已完成，跳过")
            skipped_count += 1
            continue

        logger.info(f"[{i+1}/{len(files)}] {filepath.name} ({size_mb:.1f} MB)")

        try:
            messages = read_session(filepath)
            turns = extract_turns(messages)
            total_turns += len(turns)

            if not turns:
                logger.info(f"  → 无有效对话轮次，跳过")
                skipped_count += 1
                continue

            # 提取原始会话 ID（文件名中的 UUID 部分）
            # 格式: 2026-05-15T12-43-49-201Z_019e2baa-1c51-7021-b54c-fc8e898ad903.jsonl
            original_session_id = filepath.stem.split("_")[-1] if "_" in filepath.stem else filepath.stem
            session_title = f"[HanaAgent] {original_session_id[:8]}..."

            # 创建 Memo 会话，标题包含原始会话 ID
            session = engine.start_session(title=session_title)

            for j, turn in enumerate(turns):
                # 续传：跳过已完成的轮次
                if args.resume and filepath.name == progress.get("last_session_file", ""):
                    if j <= progress.get("last_turn_index", -1):
                        continue

                # 跳过太长的单轮（可能是代码块或日志）
                if len(turn) > 5000:
                    turn = turn[:5000]

                try:
                    result = engine.remember_conversation(
                        session_id=session.id,
                        conversation=turn,
                        context_rounds=2,  # 回顾前 2 轮
                        auto_extract=True,
                        skip_gating=False,  # 默认开启门控，过滤无价值内容
                        skip_cas=args.skip_cas,
                    )
                    written_count += 1
                    progress["total_written"] = written_count
                    save_progress(filepath, j)
                    logger.info(
                        f"  [{j+1}/{len(turns)}] {result['title'][:40]} "
                        f"({len(result['feature_tags'])} tags)"
                    )
                except Exception as e:
                    logger.warning(f"  写入失败 [{j+1}]: {e}")
                    skipped_count += 1

            engine.end_session(session.id)

            # 标记会话完成
            if filepath.name not in progress.get("completed_sessions", []):
                progress.setdefault("completed_sessions", []).append(filepath.name)
            progress["last_turn_index"] = -1  # 重置轮次索引
            save_progress(filepath, -1)

        except Exception as e:
            logger.error(f"  处理失败: {e}")
            skipped_count += 1

    logger.info(f"完成: {total_turns} 轮对话, 写入 {written_count} 条, 跳过 {skipped_count}")
    # 完成：删除进度文件
    if progress_file.exists():
        progress_file.unlink()
    print(f"\n{'='*50}")
    print(f"导入完成: {written_count} 条记忆")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
