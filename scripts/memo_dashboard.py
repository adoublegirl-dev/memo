"""Memo 看板 —— 单文件 Web 应用，零额外依赖。

启动：python scripts/memo_dashboard.py
访问：http://localhost:9120
"""

import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, "E:/memo")
from memo.core.engine import engine
from memo.store.database import db

engine.init()

# ── HTML 页面 ──
PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Memo 记忆看板</title>
<style>
:root {
  --bg: #0d1117; --card: #161b22; --border: #30363d;
  --text: #c9d1d9; --muted: #8b949e; --accent: #58a6ff;
  --green: #3fb950; --orange: #d2991d; --red: #f85149;
  --purple: #a371f7; --cyan: #39d2c0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: var(--bg); color: var(--text);
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { max-width: 1200px; margin: 0 auto; padding: 24px; }
h1 { font-size: 24px; margin-bottom: 4px; }
h2 { font-size: 16px; color: var(--muted); font-weight: 400; margin-bottom: 24px; }
h3 { font-size: 14px; margin-bottom: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }

/* 统计卡片 */
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 24px; }
.stat-card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.stat-card .value { font-size: 28px; font-weight: 700; }
.stat-card .label { font-size: 12px; color: var(--muted); margin-top: 4px; }

/* 标签云 */
.tag-cloud { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin-bottom: 24px;
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center; min-height: 60px; }
.tag-item { padding: 4px 10px; border-radius: 12px; font-size: 13px; cursor: pointer; transition: transform .15s;
  white-space: nowrap; }
.tag-item:hover { transform: scale(1.08); }
.tag-item.muted { opacity: 0.3; }

/* 搜索 */
.search-bar { display: flex; gap: 8px; margin-bottom: 16px; }
.search-bar input { flex: 1; background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 14px; color: var(--text); font-size: 14px; outline: none; }
.search-bar input:focus { border-color: var(--accent); }
.search-bar button { background: var(--accent); color: #fff; border: none; border-radius: 8px;
  padding: 10px 20px; cursor: pointer; font-size: 14px; font-weight: 600; }
.search-bar button:hover { opacity: 0.9; }
.search-bar select { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 10px; color: var(--text); font-size: 14px; }

/* 记忆列表 */
.mem-list { display: flex; flex-direction: column; gap: 8px; }
.mem-item { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px;
  cursor: pointer; transition: border-color .15s; }
.mem-item:hover { border-color: var(--accent); }
.mem-item .title { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
.mem-item .meta { font-size: 12px; color: var(--muted); display: flex; gap: 12px; flex-wrap: wrap; }
.mem-item .tags { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 6px; }
.mem-item .tag { font-size: 11px; padding: 2px 8px; border-radius: 8px;
  background: rgba(88,166,255,0.12); color: var(--accent); }
.mem-item .summary { font-size: 13px; color: var(--muted); margin-top: 6px; line-height: 1.5; }

/* 详情弹窗 */
.modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  background: rgba(0,0,0,0.6); z-index: 100; justify-content: center; align-items: center; }
.modal.show { display: flex; }
.modal-content { background: var(--card); border: 1px solid var(--border); border-radius: 12px;
  max-width: 700px; width: 90%; max-height: 80vh; overflow-y: auto; padding: 24px; }
.modal-close { float: right; background: none; border: none; color: var(--muted); font-size: 20px;
  cursor: pointer; }
.modal h4 { font-size: 18px; margin-bottom: 12px; }
.modal .detail-text { font-size: 14px; line-height: 1.7; color: var(--text); white-space: pre-wrap;
  max-height: 300px; overflow-y: auto; background: var(--bg); padding: 12px; border-radius: 6px;
  margin-top: 12px; font-family: inherit; }
.modal .detail-meta { font-size: 12px; color: var(--muted); margin-top: 12px; }

.empty { text-align: center; color: var(--muted); padding: 40px; }
.refresh { font-size: 12px; color: var(--muted); text-align: right; margin-bottom: 8px; }
</style>
</head>
<body>
<h1>🧠 Memo 记忆看板</h1>
<h2>赫布学习 + 扩散激活 + 网状记忆图谱</h2>

<div class="stats" id="stats"></div>

<h3>🔥 特征词云</h3>
<div class="tag-cloud" id="tagCloud"></div>

<h3>📝 记忆列表 <span style="font-size:12px;color:var(--muted);margin-left:8px;">点击查看详情</span></h3>
<div class="search-bar">
  <input id="searchInput" placeholder="搜索记忆..." oninput="loadMemories()">
  <select id="typeFilter" onchange="loadMemories()">
    <option value="">全部类型</option>
    <option value="FACT">事实</option>
    <option value="DECISION">决策</option>
    <option value="PREFERENCE">偏好</option>
    <option value="EVENT">事件</option>
    <option value="REASONING">推理</option>
  </select>
  <button onclick="loadMemories()">搜索</button>
</div>
<div class="mem-list" id="memList"></div>

<div class="modal" id="modal" onclick="if(event.target===this)closeModal()">
  <div class="modal-content" id="modalContent"></div>
</div>

<script>
let allMemories = [];
let allTags = [];

async function load() {
  const [stats, tags, mems] = await Promise.all([
    fetch('/api/stats').then(r=>r.json()),
    fetch('/api/tags').then(r=>r.json()),
    fetch('/api/memories').then(r=>r.json()),
  ]);
  allTags = tags; allMemories = mems;
  renderStats(stats);
  renderTags(tags);
  renderMemories(mems);
}

function renderStats(s) {
  document.getElementById('stats').innerHTML = `
    <div class="stat-card"><div class="value" style="color:var(--accent)">${s.sessions}</div><div class="label">会话</div></div>
    <div class="stat-card"><div class="value" style="color:var(--green)">${s.memories}</div><div class="label">记忆</div></div>
    <div class="stat-card"><div class="value" style="color:var(--purple)">${s.feature_tags}</div><div class="label">特征词</div></div>
    <div class="stat-card"><div class="value" style="color:var(--orange)">${s.relations}</div><div class="label">关系</div></div>
    <div class="stat-card"><div class="value" style="color:var(--cyan)">${s.vector_index_size}</div><div class="label">向量索引</div></div>
  `;
}

function weightColor(w) {
  if(w>0.2) return `hsl(${200+w*200},80%,${50+w*30}%)`;
  return `hsl(210,30%,${40+w*100}%)`;
}

function renderTags(tags) {
  const cloud = document.getElementById('tagCloud');
  if(!tags.length) { cloud.innerHTML='<span class="empty">暂无特征词</span>'; return; }
  const maxW = tags[0]?.effective_weight || 1;
  cloud.innerHTML = tags.map(t=>{
    const size = 12 + (t.effective_weight/maxW)*10;
    const color = weightColor(t.effective_weight);
    return `<span class="tag-item" style="font-size:${size}px;color:${color};background:${color}15"
      onclick="searchTag('${t.name.replace(/'/g,"\\'")}')" title="${t.name} | 权重:${t.effective_weight.toFixed(3)} | 激活:${t.total_activations}次 | ${t.category}">
      ${t.name}</span>`;
  }).join('');
}

function searchTag(name) {
  document.getElementById('searchInput').value = name;
  loadMemories();
}

function loadMemories() {
  const q = document.getElementById('searchInput').value.toLowerCase();
  const type = document.getElementById('typeFilter').value;
  let mems = allMemories;
  if(q) mems = mems.filter(m=>m.title.toLowerCase().includes(q)||m.summary.toLowerCase().includes(q)||m.feature_tags.some(t=>t.toLowerCase().includes(q)));
  if(type) mems = mems.filter(m=>m.memory_type===type);
  renderMemories(mems);
}

function renderMemories(mems) {
  const list = document.getElementById('memList');
  if(!mems.length) { list.innerHTML='<div class="empty">没有匹配的记忆</div>'; return; }
  list.innerHTML = mems.map(m=>`
    <div class="mem-item" onclick="showDetail('${m.id}')">
      <div class="title">${esc(m.title)}</div>
      <div class="meta">
        <span style="color:var(--accent)">${m.memory_type}</span>
        <span>置信度 ${(m.confidence*100).toFixed(0)}%</span>
        <span>${m.session_id?.slice(0,8)||'?'}</span>
        <span>${m.valid_from?.slice(0,10)||'?'}</span>
      </div>
      <div class="tags">${(m.feature_tags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>
      <div class="summary">${esc(m.summary?.slice(0,150)||'')}${(m.summary||'').length>150?'...':''}</div>
    </div>
  `).join('');
}

async function showDetail(id) {
  const r = await fetch('/api/memory/'+id); const m = await r.json();
  document.getElementById('modalContent').innerHTML = `
    <button class="modal-close" onclick="closeModal()">✕</button>
    <h4>${esc(m.title)}</h4>
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px">
      <span style="color:var(--accent);font-size:13px">${m.memory_type}</span>
      <span style="color:var(--muted);font-size:13px">置信度 ${(m.confidence*100).toFixed(0)}%</span>
      ${m.is_superseded?'<span style="color:var(--red);font-size:13px">已替代</span>':''}
    </div>
    <div class="tags" style="margin-bottom:12px">${(m.feature_tags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>
    <div style="font-size:14px;line-height:1.6;color:var(--muted)">${esc(m.summary_detail||m.summary)}</div>
    <div class="detail-text">${esc(m.raw_text||'')}</div>
    <div class="detail-meta">ID: ${m.id} | 会话: ${m.session_id?.slice(0,8)} | 生效: ${m.valid_from?.slice(0,16)||'?'}</div>`;
  document.getElementById('modal').classList.add('show');
}

function closeModal() { document.getElementById('modal').classList.remove('show'); }
function esc(s) { const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML; }

document.addEventListener('keydown',e=>{ if(e.key==='Escape') closeModal(); });
load();
</script>
</body>
</html>"""


# ── HTTP Server ──
class MemoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            self._html(PAGE)
        elif path == "/api/stats":
            self._json(engine.stats())
        elif path == "/api/tags":
            from memo.store.graph_store import graph_store
            tags = graph_store.get_hot_tags(50)
            self._json([{
                "id": t.id, "name": t.name, "category": str(t.category),
                "effective_weight": round(t.effective_weight, 4),
                "total_activations": t.total_activations,
            } for t in tags])
        elif path == "/api/memories":
            rows = db.fetchall(
                "SELECT * FROM memory_units WHERE is_superseded=0 ORDER BY created_at DESC LIMIT 100"
            )
            from memo.store.graph_store import graph_store as gs
            mems = []
            for r in rows:
                tags = gs.get_memory_tags(r["id"])
                mems.append({
                    "id": r["id"], "session_id": r["session_id"],
                    "title": r["title"], "summary": r["summary"],
                    "memory_type": r["memory_type"], "confidence": r["confidence"],
                    "valid_from": r["valid_from"],
                    "feature_tags": [t.name for t in tags],
                })
            self._json(mems)
        elif path.startswith("/api/memory/"):
            mem_id = path.split("/")[-1]
            from memo.store.memory_store import memory_store
            from memo.store.graph_store import graph_store as gs
            mem = memory_store.get_memory(mem_id)
            if not mem:
                self._json({"error": "not found"}, 404); return
            tags = gs.get_memory_tags(mem_id)
            self._json({
                "id": mem.id, "session_id": mem.session_id,
                "title": mem.title, "summary": mem.summary,
                "summary_detail": mem.summary_detail, "raw_text": mem.raw_text,
                "memory_type": str(mem.memory_type), "confidence": mem.confidence,
                "valid_from": mem.valid_from, "is_superseded": mem.is_superseded,
                "feature_tags": [t.name for t in tags],
            })
        else:
            self._json({"error": "not found"}, 404)

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(code); self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Content-Length",len(body))
        self.end_headers(); self.wfile.write(body)

    def _html(self, html):
        body = html.encode()
        self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length",len(body)); self.end_headers(); self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # 安静模式


def main():
    port = 9120
    server = HTTPServer(("127.0.0.1", port), MemoHandler)
    print(f"\n  Memo 看板已启动 → http://localhost:{port}\n  按 Ctrl+C 停止\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  看板已停止")


if __name__ == "__main__":
    main()
