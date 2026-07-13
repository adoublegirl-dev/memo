"""统一会话导入服务 — 支持 HanaAgent / WorkBuddy / 自动检测。

设计原则：
- 单一入口，多数据源适配
- 通过 MCP 工具暴露，Agent 可直接调用
- 后台执行，不阻塞 Agent 响应
- 复用现有 MVG 门控、CAS 变更检测、断点续传逻辑
"""

import json
import os
import threading
from pathlib import Path
from datetime import datetime
from typing import Callable

from memo.core.config import config
from memo.core.engine import engine
from memo.utils.logger import logger

# ── 数据源适配器接口 ──

class SessionSource:
    """会话数据源抽象。每个 Agent 实现自己的子类。"""
    name: str = "unknown"
    sessions_dir: Path | None = None
    agent_id: str = "unknown"

    def list_sessions(self) -> list[Path]:
        """返回所有会话文件路径。"""
        raise NotImplementedError

    def read_messages(self, filepath: Path) -> list[dict]:
        """读取会话文件，返回标准化消息列表。"""
        raise NotImplementedError

    def extract_turns(self, messages: list[dict]) -> list[str]:
        """从消息列表提取 user+assistant 对话轮次。"""
        raise NotImplementedError

    def get_session_title(self, filepath: Path) -> str:
        """生成 Memo 会话标题。"""
        return f"[{self.name}] {filepath.stem[:40]}"


# ── HanaAgent 适配器 ──

class HanaAgentSource(SessionSource):
    name = "HanaAgent"
    agent_id = "ASH"

    @property
    def sessions_dir(self):
        return Path.home() / ".hanako" / "agents" / "hanako" / "sessions"

    def list_sessions(self) -> list[Path]:
        if not self.sessions_dir or not self.sessions_dir.exists():
            return []
        return sorted(self.sessions_dir.glob("*.jsonl"), key=lambda f: f.stat().st_size, reverse=True)

    def read_messages(self, filepath: Path) -> list[dict]:
        messages = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    if msg.get("type") != "message":
                        continue
                    role = msg.get("message", {}).get("role", "")
                    if role not in ("user", "assistant"):
                        continue
                    content = msg.get("message", {}).get("content", "")
                    if isinstance(content, list):
                        content = " ".join(
                            p.get("text", "") for p in content
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    messages.append({"role": role, "content": content.strip()})
                except json.JSONDecodeError:
                    continue
        return messages

    def extract_turns(self, messages: list[dict]) -> list[str]:
        MIN_LEN = 30
        turns = []
        current = []
        for m in messages:
            content = m["content"]
            if not content or len(content) < MIN_LEN:
                continue
            if m["role"] == "user":
                if current:
                    turns.append("\n".join(current))
                current = [f"User: {content}"]
            elif m["role"] == "assistant":
                if current:
                    current.append(f"Assistant: {content}")
        if current:
            turns.append("\n".join(current))
        return turns

    def get_session_title(self, filepath: Path) -> str:
        sid = filepath.stem.split("_")[-1] if "_" in filepath.stem else filepath.stem
        return f"[{self.name}] {sid[:8]}..."


# ── WorkBuddy 适配器 ──

class WorkBuddySource(SessionSource):
    name = "WorkBuddy"
    agent_id = "WorkBuddy"

    @property
    def sessions_dir(self):
        return Path.home() / ".workbuddy" / "projects"

    def list_sessions(self) -> list[Path]:
        if not self.sessions_dir or not self.sessions_dir.exists():
            return []
        files = []
        for project_dir in self.sessions_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl in project_dir.glob("*.jsonl"):
                files.append(jsonl)
        return sorted(files, key=lambda f: f.stat().st_size, reverse=True)

    def read_messages(self, filepath: Path) -> list[dict]:
        messages = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    msg_type = msg.get("type", "")
                    # 跳过工具调用和推理过程
                    if msg_type in ("function_call", "function_call_result", "reasoning",
                                     "file-history-snapshot", "custom-title", "ai-title"):
                        continue
                    if msg_type != "message":
                        continue
                    role = msg.get("role", "")
                    if role not in ("user", "assistant"):
                        continue
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(
                            p.get("text", "") for p in content
                            if isinstance(p, dict) and p.get("type", "input_text")
                        )
                    messages.append({"role": role, "content": content.strip()})
                except json.JSONDecodeError:
                    continue
        return messages

    def extract_turns(self, messages: list[dict]) -> list[str]:
        MIN_LEN = 30
        turns = []
        current = []
        for m in messages:
            content = m["content"]
            if not content or len(content) < MIN_LEN:
                continue
            if m["role"] == "user":
                if current:
                    turns.append("\n".join(current))
                current = [f"User: {content}"]
            elif m["role"] == "assistant":
                if current:
                    current.append(f"Assistant: {content}")
        if current:
            turns.append("\n".join(current))
        return turns

    def get_session_title(self, filepath: Path) -> str:
        # 从 SQLite 元数据库读取会话标题
        title = filepath.stem[:40]
        try:
            import sqlite3
            db_path = Path.home() / ".workbuddy" / "workbuddy.db"
            if db_path.exists():
                conn = sqlite3.connect(str(db_path))
                row = conn.execute(
                    "SELECT custom_title, title FROM sessions WHERE id=?",
                    (filepath.stem,)
                ).fetchone()
                conn.close()
                if row:
                    title = row[0] or row[1] or filepath.stem[:40]
        except Exception:
            pass
        return f"[{self.name}] {title[:50]}"


# ── 数据源注册表 ──

SOURCES: dict[str, type[SessionSource]] = {
    "hanaagent": HanaAgentSource,
    "workbuddy": WorkBuddySource,
}


def detect_source() -> str:
    """自动检测可用的数据源。"""
    for name, cls in SOURCES.items():
        src = cls()
        if src.sessions_dir and src.sessions_dir.exists():
            files = src.list_sessions()
            if files:
                return name
    return "hanaagent"  # 默认


# ── 导入执行器 ──

class ImportTask:
    """后台导入任务。"""

    def __init__(self, source_name: str):
        self.source_name = source_name
        self.source = SOURCES[source_name]()
        self.status = "pending"
        self.progress = {"completed": 0, "total": 0, "written": 0, "skipped": 0}
        self.error = None

    def run(self, skip_cas: bool = False, restart: bool = False):
        """执行导入。在后台线程中运行。"""
        try:
            self._run(skip_cas, restart)
        except Exception as e:
            self.status = "failed"
            self.error = str(e)
            logger.error(f"[{self.source.name}] 导入异常: {e}", exc_info=True)

    def _run(self, skip_cas: bool, restart: bool):
        self.status = "running"
        engine.init()

        files = self.source.list_sessions()
        self.progress["total"] = len(files)
        logger.info(f"[{self.source.name}] 找到 {len(files)} 个会话文件")

        # 断点续传
        progress_file = Path(config.db_path).parent / f"import_progress_{self.source.name}.json"
        completed = set()
        if not restart and progress_file.exists():
            data = json.loads(progress_file.read_text(encoding="utf-8"))
            completed = set(data.get("completed_sessions", []))
            self.progress["completed"] = data.get("total_written", 0)
            logger.info(f"[{self.source.name}] 断点续传: {len(completed)} 个已完成")

        for i, filepath in enumerate(files):
            if filepath.name in completed:
                self.progress["skipped"] += 1
                continue

            size_mb = filepath.stat().st_size / (1024 * 1024)
            logger.info(f"[{self.source.name}] [{i+1}/{len(files)}] {filepath.name} ({size_mb:.1f} MB)")

            try:
                messages = self.source.read_messages(filepath)
                turns = self.source.extract_turns(messages)

                if not turns:
                    self.progress["skipped"] += 1
                    continue

                session = engine.start_session(
                    title=self.source.get_session_title(filepath),
                    agent_id=self.source.agent_id,
                )

                for j, turn in enumerate(turns):
                    if len(turn) > 5000:
                        turn = turn[:5000]
                    try:
                        result = engine.remember_conversation(
                            session_id=session.id,
                            conversation=turn,
                            context_rounds=2,
                            auto_extract=True,
                            skip_cas=skip_cas,
                        )
                        self.progress["written"] += 1
                    except Exception as e:
                        logger.warning(f"写入失败 [{j+1}]: {e}")
                        self.progress["skipped"] += 1

                engine.end_session(session.id)
                completed.add(filepath.name)
                self.progress["completed"] = self.progress["written"]

                # 保存进度
                progress_file.parent.mkdir(exist_ok=True)
                tmp = progress_file.with_suffix(".tmp")
                tmp.write_text(json.dumps({
                    "completed_sessions": list(completed),
                    "total_written": self.progress["written"],
                    "last_updated": datetime.now().isoformat(),
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp.replace(progress_file)

            except Exception as e:
                logger.error(f"会话处理失败: {e}")
                self.progress["skipped"] += 1

        # 完成：删除进度文件
        if progress_file.exists():
            progress_file.unlink()

        self.status = "completed"
        logger.info(f"[{self.source.name}] 导入完成: {self.progress['written']} 条记忆")


# ── 全局任务管理 ──

_current_task: ImportTask | None = None


def start_import(source: str, skip_cas: bool = False, restart: bool = False) -> dict:
    """启动后台导入任务。"""
    global _current_task

    if source == "auto":
        source = detect_source()

    if source not in SOURCES:
        return {"status": "error", "message": f"未知数据源: {source}。可选: {list(SOURCES.keys())}"}

    if _current_task and _current_task.status == "running":
        return {
            "status": "busy",
            "message": f"已有导入任务在运行 ({_current_task.source_name})",
            "progress": _current_task.progress,
        }

    _current_task = ImportTask(source)
    thread = threading.Thread(target=_current_task.run, args=(skip_cas, restart), daemon=True)
    thread.start()

    return {
        "status": "started",
        "source": source,
        "message": "导入任务已启动，通过 memo_import_status 查看进度",
        "progress": _current_task.progress,
    }


def get_import_status() -> dict:
    """查询当前导入任务状态。"""
    if not _current_task:
        return {"status": "idle", "message": "无正在运行的导入任务"}
    return {
        "status": _current_task.status,
        "source": _current_task.source_name,
        "progress": _current_task.progress,
        "error": _current_task.error,
    }
