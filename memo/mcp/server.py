"""Memo MCP Server —— 通过 stdio 暴露 Memo 记忆能力给任何 MCP 兼容 Agent。

启动方式：
    python -m memo.mcp.server
    或
    npx @hanako/memo-mcp  (待发布)

MCP 客户端配置 (Claude Desktop / Cursor / Claude Code):
    {
      "mcpServers": {
        "memo": {
          "command": "python",
          "args": ["-m", "memo.mcp.server"]
        }
      }
    }

Core Profile (18 tools):
    memo_remember      — 写入记忆
    memo_recall        — 三通道混合检索
    memo_start_session — 开始新会话
    memo_end_session   — 结束当前会话
    memo_stats         — 记忆统计
    memo_hot_tags      — 高频特征词
    memo_maintain      — 生命周期维护
    memo_snapshot      — 全局快照
    memo_export        — Bridge 导出
    persona_ask        — 人格路由问答
    persona_profile    — 人格画像
    todo_add           — 创建待办
    todo_search        — 搜索待办
    todo_list          — 列出待办
    todo_close         — 完成待办
    todo_reopen        — 重新开启
    todo_update        — 编辑待办
    todo_check_risk    — 风险检测
"""

import asyncio
import json
import sys
from pathlib import Path

# 确保项目路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from memo.core.engine import engine
from memo.utils.logger import logger


# ── 创建 MCP Server ──
server = Server("memo-mcp")

# 当前活跃会话/空间（MCP 连接的生命周期内）
_active_session_id: str | None = None
_active_space_id: str | None = None


# ── 工具定义 ──

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="memo_remember",
            description="写入一条记忆。如果提供 conversation 则自动提取特征词和摘要；"
                        "也可手动指定 title/summary/feature_tags。"
                        "支持标记 is_update_of 来更新旧事实。",
            inputSchema={
                "type": "object",
                "properties": {
                    "conversation": {
                        "type": "string",
                        "description": "对话文本（可选，提供后自动提取特征词/摘要/关系）"
                    },
                    "title": {
                        "type": "string",
                        "description": "记忆标题（手动模式）"
                    },
                    "summary": {
                        "type": "string",
                        "description": "一级摘要（手动模式）"
                    },
                    "summary_detail": {
                        "type": "string",
                        "description": "二级摘要（手动模式）"
                    },
                    "feature_tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "特征词列表"
                    },
                    "tag_relations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from": {"type": "string"},
                                "to": {"type": "string"},
                                "type": {"type": "string", "enum": ["CO_OCCUR", "CAUSAL", "TEMPORAL", "DERIVED"]}
                            }
                        },
                        "description": "特征词间关系"
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["FACT", "DECISION", "PREFERENCE", "EVENT", "REASONING"],
                        "default": "FACT"
                    },
                    "is_update_of": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "如果此记忆更新/推翻旧事实，列出旧事实的关键词"
                    },
                    "agent_name": {
                        "type": "string",
                        "description": "来源 Agent 名称（WorkBuddy / HanaAgent / Qoder 等），用于跨 Agent 来源追溯"
                    },
                    "space_id": {
                        "type": "string",
                        "description": "上下文空间 ID/名称（可选，不传则使用当前激活 Space）"
                    },
                }
            }
        ),
        Tool(
            name="memo_recall",
            description="三通道混合检索：向量语义 + 全文关键词 + 图扩散激活。"
                        "自动融合结果，返回最相关的记忆。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "查询文本"
                    },
                    "top_k": {
                        "type": "integer",
                        "default": 5,
                        "description": "返回数量（默认 5）"
                    },
                    "space_id": {
                        "type": "string",
                        "description": "上下文空间 ID/名称（可选，不传则使用当前激活 Space）"
                    },
                    "space_mode": {
                        "type": "string",
                        "enum": ["boost", "within"],
                        "default": "boost",
                        "description": "boost=空间内结果加权；within=仅返回空间内结果"
                    },
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="memo_start_session",
            description="开始一个新的记忆会话。后续 memo_remember 会关联到此会话。",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "会话标题"
                    },
                    "space_id": {
                        "type": "string",
                        "description": "上下文空间 ID/名称（可选，不传则使用当前激活 Space）"
                    },
                }
            }
        ),
        Tool(
            name="memo_end_session",
            description="结束当前记忆会话。",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="memo_stats",
            description="获取记忆系统统计：会话数、记忆数、特征词数、关系数、高频词等。",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="memo_hot_tags",
            description="获取当前权重最高的特征词（热记忆体）。用于了解 Agent 当前活跃的知识域。",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "返回数量"
                    },
                }
            }
        ),
        Tool(
            name="memo_maintain",
            description="手动触发记忆生命周期维护：遗忘衰减 + 固化检查 + 快照。"
                        "通常不需手动调用，系统会自动维护。",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="memo_snapshot",
            description="获取最新的全局记忆快照，包含 Agent 对用户的全局认知。",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="memo_export",
            description="导出当前对话到 Memo inbox 目录。Agent 对话结束时调用此工具，"
                        "将对话内容写入 ~/.memo/inbox/，Memo watcher 会自动导入。"
                        "这是跨 Agent Bridge 的核心工具——任何支持 MCP 的 Agent 安装后，"
                        "对话记录都会汇入同一个 Memo 记忆库。",
            inputSchema={
                "type": "object",
                "properties": {
                    "conversation": {
                        "type": "string",
                        "description": "完整的对话文本（User + Assistant 交替）"
                    },
                    "agent_name": {
                        "type": "string",
                        "description": "来源 Agent 名称（如 WorkBuddy / Qoder / Claude）"
                    },
                    "metadata": {
                        "type": "object",
                        "description": "额外元数据（可选）"
                    },
                },
                "required": ["conversation"]
            }
        ),
        Tool(
            name="persona_ask",
            description="人格路由问答。基于用户的人格画像，对问题给出带人格立场的回复。"
                        "自动判断走人格通道/混合通道/经验通道。",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "用户的问题"
                    },
                },
                "required": ["question"]
            }
        ),
        Tool(
            name="persona_profile",
            description="获取用户人格画像。按维度展示所有活跃断言。",
            inputSchema={
                "type": "object",
                "properties": {
                    "dimension": {
                        "type": "string",
                        "description": "限定维度（可选，如 value/decision/preference），不传返回全部"
                    },
                }
            }
        ),
        Tool(
            name="memo_import_sessions",
            description="导入历史会话到 Memo。支持 hanaagent / workbuddy / auto（自动检测）。后台执行，通过 memo_import_status 查看进度。",
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "enum": ["hanaagent", "workbuddy", "auto"],
                        "default": "auto",
                        "description": "数据源：hanaagent / workbuddy / auto"
                    },
                    "skip_cas": {
                        "type": "boolean",
                        "default": True,
                        "description": "跳过 CAS 变更检测（导入后统一跑 run_lifecycle 更高效）"
                    },
                    "restart": {
                        "type": "boolean",
                        "default": False,
                        "description": "强制从头开始（忽略断点续传进度）"
                    },
                }
            }
        ),
        Tool(
            name="memo_import_status",
            description="查询当前导入任务的进度。",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="space_create",
            description="创建一个 Context Space（上下文空间），用于组织个人事项、管理项目、产品项目、客户事务等长期上下文。",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "空间名称"},
                    "type": {"type": "string", "description": "空间类型，如 management/product/personal/dev_project"},
                    "description": {"type": "string", "description": "空间描述"},
                    "goal": {"type": "string", "description": "目标"},
                    "aliases": {"type": "array", "items": {"type": "string"}, "description": "别名列表"},
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="space_list",
            description="列出 Context Space，含类型、状态、记忆数、待办数。",
            inputSchema={
                "type": "object",
                "properties": {
                    "include_archived": {"type": "boolean", "default": False},
                    "type": {"type": "string", "description": "按空间类型过滤"},
                }
            }
        ),
        Tool(
            name="space_activate",
            description="激活一个 Space。后续 memo_remember/memo_recall/todo_add 默认关联该 Space。",
            inputSchema={
                "type": "object",
                "properties": {"space_id": {"type": "string", "description": "Space ID、名称或别名"}},
                "required": ["space_id"]
            }
        ),
        Tool(
            name="space_deactivate",
            description="退出当前激活 Space，回到全局上下文。",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="space_profile",
            description="获取某个 Space 的简报：基础状态、最近记忆、关键决策、待办和特征词。",
            inputSchema={
                "type": "object",
                "properties": {"space_id": {"type": "string", "description": "Space ID、名称或别名；不传则使用当前激活 Space"}}
            }
        ),
        Tool(
            name="space_recall",
            description="在某个 Space 语境下检索记忆。支持 boost 或 within 模式。",
            inputSchema={
                "type": "object",
                "properties": {
                    "space_id": {"type": "string", "description": "Space ID、名称或别名；不传则使用当前激活 Space"},
                    "query": {"type": "string", "description": "查询文本"},
                    "top_k": {"type": "integer", "default": 5},
                    "mode": {"type": "string", "enum": ["boost", "within"], "default": "boost"},
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="space_detect",
            description="分析文本可能属于哪些 Space，只返回候选，不自动切换。",
            inputSchema={
                "type": "object",
                "properties": {
                    "conversation": {"type": "string", "description": "待分析文本"},
                    "top_k": {"type": "integer", "default": 3},
                },
                "required": ["conversation"]
            }
        ),
        Tool(
            name="todo_add",
            description="创建待办。返回预览信息，用户确认后正式入库。",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "待办标题"},
                    "description": {"type": "string", "description": "详细描述"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "优先级"},
                    "due_date": {"type": "string", "description": "截止日期，如 2026-07-18"},
                    "memory_id": {"type": "string", "description": "关联记忆 ID"},
                    "agent_name": {"type": "string", "description": "来源 Agent"},
                },
                "required": ["title"]
            }
        ),
        Tool(
            name="todo_search",
            description="搜索待办。返回匹配的待办列表，支持模糊搜索。",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词"},
                    "status": {"type": "string", "description": "状态过滤，如 todo+doing"},
                    "include_done": {"type": "boolean", "description": "是否包含已完成"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["keyword"]
            }
        ),
        Tool(
            name="todo_list",
            description="列出待办。支持按状态和优先级过滤。",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "状态过滤，多个用+连接"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "limit": {"type": "integer", "default": 20},
                }
            }
        ),
        Tool(
            name="todo_close",
            description="完成待办。支持批量关闭，传入 ID 列表。完成后自动写入记忆。",
            inputSchema={
                "type": "object",
                "properties": {
                    "ids": {"type": "array", "items": {"type": "string"}, "description": "待办 ID 列表"},
                    "note": {"type": "string", "description": "完成备注"},
                    "agent_name": {"type": "string", "description": "来源 Agent"},
                },
                "required": ["ids"]
            }
        ),
        Tool(
            name="todo_reopen",
            description="重新开启已完成的待办。",
            inputSchema={
                "type": "object",
                "properties": {
                    "ids": {"type": "array", "items": {"type": "string"}, "description": "待办 ID 列表"},
                    "agent_name": {"type": "string", "description": "来源 Agent"},
                },
                "required": ["ids"]
            }
        ),
        Tool(
            name="todo_update",
            description="编辑待办。可修改标题、优先级、截止日期等。",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "待办 ID"},
                    "title": {"type": "string"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "status": {"type": "string"},
                    "due_date": {"type": "string"},
                    "description": {"type": "string"},
                    "agent_name": {"type": "string"},
                },
                "required": ["id"]
            }
        ),
        Tool(
            name="todo_check_risk",
            description="检测待办风险。返回逾期、紧急、预警待办。每天 10 点自动提醒。",
            inputSchema={"type": "object", "properties": {}}
        ),
    ]


# ── 工具实现 ──

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    global _active_session_id, _active_space_id

    try:
        if name == "memo_start_session":
            title = arguments.get("title", "")
            space_id = arguments.get("space_id") or _active_space_id
            session = engine.start_session(title=title, space_id=space_id)
            _active_session_id = session.id
            return [TextContent(
                type="text",
                text=f"会话已开始: {session.id[:8]}... (标题: {title or '未命名'})"
            )]

        elif name == "memo_end_session":
            if _active_session_id:
                engine.end_session(_active_session_id)
                sid = _active_session_id
                _active_session_id = None
                return [TextContent(type="text", text=f"会话已结束: {sid[:8]}...")]
            return [TextContent(type="text", text="无活跃会话需要结束")]

        elif name == "memo_remember":
            conversation = arguments.get("conversation", "")
            title = arguments.get("title", "")
            summary = arguments.get("summary", "")
            summary_detail = arguments.get("summary_detail", "")
            feature_tags = arguments.get("feature_tags", [])
            tag_relations = arguments.get("tag_relations", [])
            memory_type = arguments.get("memory_type", "FACT")
            is_update_of = arguments.get("is_update_of")

            space_id = arguments.get("space_id") or _active_space_id
            session_id = _active_session_id
            if not session_id:
                agent_name = arguments.get("agent_name", "unknown")
                session = engine.start_session(title="自动会话", agent_id=agent_name, space_id=space_id)
                _active_session_id = session.id
                session_id = session.id

            if conversation:
                # 自动提取模式
                result = engine.remember_conversation(
                    session_id=session_id,
                    conversation=conversation,
                    auto_extract=True,
                    space_id=space_id,
                )
                if result.get("memory_id") is None:
                    reason = (result.get("gating_result") or {}).get("reason", "门控判定长期价值不足")
                    return [TextContent(
                        type="text",
                        text=f"⏭️ 已跳过写入记忆：{reason}\n"
                             f"   提取方式: {result.get('extraction_method', 'skipped')}"
                    )]
                return [TextContent(
                    type="text",
                    text=f"✅ 已提取并写入记忆\n"
                         f"   ID: {result['memory_id'][:8]}...\n"
                         f"   标题: {result['title'][:60]}\n"
                         f"   特征词: {', '.join(result['feature_tags'])}\n"
                         f"   提取方式: {result['extraction_method']}\n"
                         f"   冲突: {len(result['conflicts_found'])} 条"
                )]
            else:
                # 手动模式
                memory_id = engine.remember(
                    session_id=session_id,
                    raw_text=title or summary or "(手动记忆)",
                    title=title,
                    summary=summary,
                    summary_detail=summary_detail,
                    feature_tags=feature_tags,
                    tag_relations=tag_relations,
                    memory_type=memory_type,
                    space_id=space_id,
                )
                return [TextContent(
                    type="text",
                    text=f"✅ 已写入记忆\n"
                         f"   ID: {memory_id[:8]}...\n"
                         f"   标题: {title[:60] if title else '(无标题)'}\n"
                         f"   特征词: {', '.join(feature_tags)}"
                )]

        elif name == "memo_recall":
            query = arguments["query"]
            top_k = arguments.get("top_k", 5)
            space_id = arguments.get("space_id") or _active_space_id
            results = engine.recall(
                query,
                top_k=top_k,
                space_id=space_id,
                space_mode=arguments.get("space_mode", "boost"),
            )

            if not results:
                return [TextContent(type="text", text="未找到相关记忆。")]

            output = f"找到 {len(results)} 条相关记忆:\n\n"
            for i, r in enumerate(results):
                output += (
                    f"{i+1}. [{r['score']:.4f}] {r['title'][:80]}\n"
                    f"   类型: {r['memory_type']} | 特征词: {', '.join(r['feature_tags'][:5])}\n"
                    f"   {r['summary'][:200]}\n\n"
                )
            return [TextContent(type="text", text=output.strip())]

        elif name == "memo_stats":
            stats = engine.stats()
            output = (
                f"📊 Memo 记忆统计\n"
                f"   会话: {stats['sessions']}\n"
                f"   记忆: {stats['memories']}\n"
                f"   特征词: {stats['feature_tags']}\n"
                f"   关系: {stats['relations']}\n"
                f"   向量索引: {stats['vector_index_size']} 条\n"
                f"   TOP 特征词: {', '.join(stats['top_tags'][:10])}"
            )
            return [TextContent(type="text", text=output)]

        elif name == "memo_hot_tags":
            limit = arguments.get("limit", 20)
            from memo.store.graph_store import graph_store
            tags = graph_store.get_hot_tags(limit=limit)
            output = "🔥 高频特征词:\n"
            for i, tag in enumerate(tags):
                output += (
                    f"   {i+1}. {tag.name} "
                    f"(权重={tag.effective_weight:.3f}, "
                    f"激活={tag.total_activations}次, "
                    f"分类={tag.category if isinstance(tag.category, str) else tag.category.value})\n"
                )
            return [TextContent(type="text", text=output.strip())]

        elif name == "memo_maintain":
            report = engine.run_lifecycle()
            output = "⚙️ 生命周期维护完成:\n"
            for stage, detail in report.items():
                output += f"   {stage}: {detail}\n"
            return [TextContent(type="text", text=output.strip())]

        elif name == "memo_snapshot":
            from memo.store.database import db
            row = db.fetchone(
                "SELECT * FROM global_snapshots ORDER BY snapshot_at DESC LIMIT 1"
            )
            if not row:
                return [TextContent(type="text", text="尚无全局快照。多积累一些记忆后会自动生成。")]

            output = (
                f"📸 全局记忆快照 ({row['snapshot_at'][:19]})\n"
                f"   会话: {row['total_sessions']} | 记忆: {row['total_memory_units']}\n"
                f"   特征词: {row['total_feature_tags']} | 关系: {row['total_relations']}\n"
            )
            if row["agent_profile"]:
                output += f"   用户画像: {row['agent_profile'][:200]}\n"
            if row["active_projects"]:
                projects = json.loads(row["active_projects"])
                output += f"   活跃项目: {', '.join(projects)}\n"
            return [TextContent(type="text", text=output.strip())]

        elif name == "memo_export":
            conversation = arguments["conversation"]
            agent_name = arguments.get("agent_name", "unknown")
            metadata = arguments.get("metadata", {})
            result = _export_to_inbox(conversation, agent_name, metadata)
            return [TextContent(type="text", text=result)]

        elif name == "space_create":
            result = engine.space_create(
                name=arguments["name"],
                type=arguments.get("type", "general"),
                description=arguments.get("description", ""),
                goal=arguments.get("goal", ""),
                aliases=arguments.get("aliases", []),
                created_by="mcp",
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "space_list":
            result = engine.space_list(
                include_archived=arguments.get("include_archived", False),
                type=arguments.get("type", ""),
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "space_activate":
            space = engine.space_get(arguments["space_id"])
            if not space:
                return [TextContent(type="text", text="❌ 未找到 Space")]
            _active_space_id = space["id"]
            return [TextContent(type="text", text=f"✅ 已激活 Space: {space['name']} ({space['id'][:8]}...)")]

        elif name == "space_deactivate":
            _active_space_id = None
            return [TextContent(type="text", text="已退出当前 Space，回到全局上下文")]

        elif name == "space_profile":
            sid = arguments.get("space_id") or _active_space_id
            if not sid:
                return [TextContent(type="text", text="请提供 space_id，或先调用 space_activate 激活一个 Space。")]
            result = engine.space_profile(sid)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "space_recall":
            sid = arguments.get("space_id") or _active_space_id
            if not sid:
                return [TextContent(type="text", text="请提供 space_id，或先调用 space_activate 激活一个 Space。")]
            result = engine.space_recall(
                space_id=sid,
                query=arguments["query"],
                top_k=arguments.get("top_k", 5),
                mode=arguments.get("mode", "boost"),
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "space_detect":
            result = engine.space_detect(
                conversation=arguments["conversation"],
                top_k=arguments.get("top_k", 3),
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "persona_ask":
            question = arguments["question"]
            result = engine.persona_ask(question)
            output = (
                f"🧬 人格路由: {result['channel']}\n"
                f"   置信度: {result['confidence']}\n\n"
                f"{result['reply']}"
            )
            if result.get("citations"):
                output += "\n\n📎 引用:\n"
                for c in result["citations"][:3]:
                    output += f"   [{c['confidence']:.2f}] {c['assertion'][:80]}\n"
            return [TextContent(type="text", text=output)]

        elif name == "persona_profile":
            dimension = arguments.get("dimension")
            assertions = engine.persona_profile(dimension)
            if not assertions:
                return [TextContent(type="text", text="暂无活跃的人格断言。请先运行 build_persona_baseline() 建基线。")]
            by_dim = {}
            for a in assertions:
                d = a["dimension"]
                by_dim.setdefault(d, []).append(a)
            output = f"🧬 人格画像 ({len(assertions)} 条断言, {len(by_dim)} 维)\n\n"
            dim_labels = {
                "value": "💎 价值观", "decision": "🎯 决策", "identity": "🏷️ 身份",
                "preference": "❤️ 偏好", "sensitivity": "⚠️ 敏感", "relationship": "🔗 关系",
                "knowledge": "📚 知识边界", "communication": "💬 沟通",
                "mental_model": "🧩 思维模型", "emotion": "🌊 情绪"
            }
            for dim, items in by_dim.items():
                label = dim_labels.get(dim, dim)
                output += f"{label}:\n"
                for a in items[:2]:
                    output += f"   [{a['confidence']:.2f}] {a['assertion'][:100]}\n"
                output += "\n"
            return [TextContent(type="text", text=output.strip())]

        elif name == "memo_import_sessions":
            source = arguments.get("source", "auto")
            skip_cas = arguments.get("skip_cas", True)
            restart = arguments.get("restart", False)
            from memo.services import start_import
            result = start_import(source, skip_cas=skip_cas, restart=restart)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "memo_import_status":
            from memo.services import get_import_status
            result = get_import_status()
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "todo_add":
            title = arguments["title"]
            result = engine.todo_add(
                title=title,
                description=arguments.get("description", ""),
                priority=arguments.get("priority", "medium"),
                due_date=arguments.get("due_date", ""),
                memory_id=arguments.get("memory_id", ""),
                source_agent=arguments.get("agent_name", ""),
                space_id=arguments.get("space_id") or _active_space_id or "",
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "todo_search":
            result = engine.todo_search(
                keyword=arguments.get("keyword", ""),
                status=arguments.get("status", "todo+doing"),
                include_done=arguments.get("include_done", False),
                limit=arguments.get("limit", 10),
                space_id=arguments.get("space_id") or _active_space_id or "",
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "todo_list":
            result = engine.todo_list(
                status=arguments.get("status", "todo+doing"),
                priority=arguments.get("priority", ""),
                limit=arguments.get("limit", 20),
                space_id=arguments.get("space_id") or _active_space_id or "",
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "todo_close":
            ids = arguments["ids"]
            result = engine.todo_close(
                ids=ids,
                note=arguments.get("note", ""),
                agent=arguments.get("agent_name", ""),
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "todo_reopen":
            ids = arguments["ids"]
            result = engine.todo_reopen(
                ids=ids,
                agent=arguments.get("agent_name", ""),
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "todo_update":
            result = engine.todo_update(
                todo_id=arguments["id"],
                title=arguments.get("title", ""),
                priority=arguments.get("priority", ""),
                status=arguments.get("status", ""),
                due_date=arguments.get("due_date", ""),
                description=arguments.get("description", ""),
                agent=arguments.get("agent_name", ""),
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "todo_check_risk":
            result = engine.todo_check_risk()
            output = f"⚠️ 风险: {result['summary']}\n"
            for item in result.get("overdue", []):
                output += f"  🔴 逾期{item['days_overdue']}天: {item['title']}\n"
            for item in result.get("urgent", []):
                output += f"  🔴 {item['hours_left']}h后到期: {item['title']}\n"
            for item in result.get("warning", []):
                output += f"  🟡 {item.get('due','')} {item['title']}\n"
            return [TextContent(type="text", text=output.strip())]

        else:
            return [TextContent(type="text", text=f"未知工具: {name}")]

    except Exception as e:
        logger.error(f"工具 {name} 执行失败: {e}", exc_info=True)
        return [TextContent(type="text", text=f"❌ 错误: {e}")]


# ── Bridge 导出 ──

def _export_to_inbox(conversation: str, agent_name: str, metadata: dict) -> str:
    """导出对话到 Memo inbox 目录。

    Watcher 会监控此目录并自动导入新文件。
    """
    import json
    from datetime import datetime

    inbox_dir = Path.home() / ".memo" / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{agent_name}.jsonl"
    filepath = inbox_dir / filename

    record = {
        "exported_at": datetime.now().isoformat(),
        "agent": agent_name,
        "conversation": conversation,
        "metadata": metadata,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info(f"对话已导出: {filepath}")
    return (
        f"✅ 对话已导出到 Memo inbox\n"
        f"   文件: {filename}\n"
        f"   来源: {agent_name}\n"
        f"   长度: {len(conversation)} 字符\n"
        f"   Memo watcher 将在下次轮询时自动导入"
    )


# ── 入口 ──

def main():
    """启动 Memo MCP Server（stdio 模式）。

    MCP 协议要求 stdout 只走 JSON-RPC，任何额外输出都会破坏通信。
    因此初始化阶段的日志全部走 stderr，进度条压制。
    """
    import os
    from contextlib import redirect_stdout

    # 压制所有 stdout 噪音（sentence-transformers 进度条等）
    with open(os.devnull, 'w', encoding='utf-8') as devnull:
        with redirect_stdout(devnull):
            logger.info("Memo MCP Server 启动中...")
            engine.init()

    logger.info("Memo MCP Server 就绪，等待 MCP 客户端连接...")

    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    asyncio.run(run())


if __name__ == "__main__":
    main()
