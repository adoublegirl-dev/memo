"""Memo 看板 —— 单文件 Web 应用，零额外依赖。

启动：python scripts/memo_dashboard.py
访问：http://localhost:9120
"""

import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
  --bg: #ffffff; --card: #f6f8fa; --border: #d0d7de;
  --text: #1f2328; --muted: #656d76; --accent: #0969da;
  --green: #1a7f37; --orange: #9a6700; --red: #cf222e;
  --purple: #8250df; --cyan: #1b7c83;
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
  background: rgba(0,0,0,0.3); z-index: 100; justify-content: center; align-items: center; }
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

/* 图谱视图 */
.view-toggle { display: flex; gap: 4px; margin-bottom: 12px; }
.toggle-btn { background: var(--card); border: 1px solid var(--border); color: var(--muted);
  padding: 6px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.toggle-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }
#graphView { margin-bottom: 24px; }
.graph-node { cursor: pointer; transition: opacity .2s; }
.graph-node.dimmed { opacity: 0.15; }
.graph-link { transition: opacity .2s; }
.graph-link.dimmed { opacity: 0.05; }
.graph-node-label { font-size: 10px; fill: var(--text); pointer-events: none; user-select: none; }
</style>
</head>
<body>
<h1>🧠 Memo 记忆看板</h1>
<h2>赫布学习 + 扩散激活 + 网状记忆图谱</h2>

<div class="stats" id="stats"></div>

<h3>🔥 特征词云 <span style="font-size:12px;color:var(--muted);margin-left:8px;">点击词 → 搜索</span></h3>
<div class="tag-cloud" id="tagCloud"></div>

<h3>🕸️ 特征词图谱 <span style="font-size:12px;color:var(--muted);margin-left:8px;">拖拽节点 | 滚轮缩放 | 点击高亮关联</span></h3>
<div class="view-toggle">
  <button class="toggle-btn active" onclick="switchView('graph')">图谱视图</button>
  <button class="toggle-btn" onclick="switchView('list')">列表视图</button>
</div>
<div id="graphView">
  <div id="graphContainer" style="background:var(--card);border:1px solid var(--border);border-radius:8px;overflow:hidden;height:500px;position:relative;">
    <svg id="graphSvg" width="100%" height="100%"></svg>
    <div id="graphTooltip" style="display:none;position:absolute;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px;pointer-events:none;z-index:10;max-width:300px;"></div>
    <div id="graphLegend" style="position:absolute;bottom:12px;left:12px;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:11px;color:var(--muted);">
      <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--accent);margin-right:4px;"></span>概念
      <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--green);margin:0 4px 0 12px;"></span>事件
      <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--purple);margin:0 4px 0 12px;"></span>组织/项目
      <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--orange);margin:0 4px 0 12px;"></span>其他
    </div>
  </div>
  <div id="graphDetail" style="margin-top:8px;font-size:13px;color:var(--muted);">点击节点查看关联记忆</div>
</div>

<h3>📝 记忆列表 <span style="font-size:12px;color:var(--muted);margin-left:8px;">点击查看详情</span></h3>
<div id="memListSection">
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
</div>

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

<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
let graphData = null;
let graphSimulation = null;

async function initGraph() {
  graphData = await fetch('/api/graph').then(r=>r.json());
  if(!graphData.nodes.length) return;
  renderGraph();
}

function renderGraph() {
  const container = document.getElementById('graphContainer');
  const width = container.clientWidth;
  const height = 500;
  const svg = d3.select('#graphSvg').attr('viewBox', [0,0,width,height]);
  svg.selectAll('*').remove();

  const g = svg.append('g');
  const zoom = d3.zoom().scaleExtent([0.3,4]).on('zoom', e=>g.attr('transform', e.transform));
  svg.call(zoom);

  const nodes = graphData.nodes.map(n=>({...n}));
  const edges = graphData.edges.map(e=>({...e}));
  const tagMemories = graphData.tag_memories||{};

  const catColor = {
    CONCEPT: 'var(--accent)', EVENT: 'var(--green)', ORGANIZATION: 'var(--purple)',
    PERSON: 'var(--cyan)', OBJECT: 'var(--orange)', LOCATION: 'var(--red)'
  };
  const defaultColor = 'var(--orange)';

  const link = g.append('g').selectAll('line').data(edges).join('line')
    .attr('class','graph-link')
    .attr('stroke','var(--border)')
    .attr('stroke-width', d=>Math.max(0.5, d.weight*5))
    .attr('stroke-opacity', d=>Math.max(0.1, d.weight));

  const node = g.append('g').selectAll('g').data(nodes).join('g')
    .attr('class','graph-node')
    .call(d3.drag().on('start',(e,d)=>{if(!e.active)simulation.alphaTarget(0.3).restart();d.fx=d.x;d.fy=d.y})
      .on('drag',(e,d)=>{d.fx=e.x;d.fy=e.y})
      .on('end',(e,d)=>{if(!e.active)simulation.alphaTarget(0);d.fx=null;d.fy=null}));

  node.append('circle')
    .attr('r', d=>Math.max(4, 8+d.weight*25))
    .attr('fill', d=>`var(--${{
      CONCEPT:'accent',EVENT:'green',ORGANIZATION:'purple',PERSON:'cyan',OBJECT:'orange',LOCATION:'red'
    }[d.category]||'orange'})`)
    .attr('stroke','var(--bg)').attr('stroke-width',1.5);

  node.append('text').attr('class','graph-node-label').attr('dy', d=>-(8+d.weight*25+6))
    .attr('text-anchor','middle').text(d=>d.name.length>8?d.name.slice(0,8)+'…':d.name);

  const tooltip = document.getElementById('graphTooltip');
  const detailDiv = document.getElementById('graphDetail');

  node.on('click', function(ev,d) {
    ev.stopPropagation();
    const connected = new Set();
    edges.forEach(e=>{ if(e.source.id===d.id||e.source===d.id)connected.add(e.target.id||e.target);
                        if(e.target.id===d.id||e.target===d.id)connected.add(e.source.id||e.source); });
    connected.add(d.id);
    node.classed('dimmed', n=>!connected.has(n.id));
    link.classed('dimmed', e=>(e.source.id||e.source)!==d.id&&(e.target.id||e.target)!==d.id);
    const mems = tagMemories[d.id]||[];
    detailDiv.innerHTML = `<strong style="color:var(--accent)">${d.name}</strong> | `
      + `权重 ${d.weight.toFixed(3)} | 激活 ${d.activations}次 | ${d.category}<br>`
      + (mems.length ? `关联记忆: ${mems.map(m=>`<span style="cursor:pointer;color:var(--accent)" onclick="showDetail('${m.id}')">${m.id}</span>`).join(', ')}` : '暂无关联记忆');
  });

  node.on('mouseenter', function(ev,d) {
    tooltip.style.display='block';
    tooltip.innerHTML=`<strong>${d.name}</strong><br>权重 ${d.weight.toFixed(3)} | ${d.activations}次 | ${d.category}`;
  }).on('mousemove', function(ev,d) {
    tooltip.style.left=(ev.offsetX+15)+'px'; tooltip.style.top=(ev.offsetY-30)+'px';
  }).on('mouseleave', function(){ tooltip.style.display='none'; });

  svg.on('click', function(ev) {
    if(ev.target===this||ev.target.tagName==='svg'||ev.target.tagName==='SVG') {
      node.classed('dimmed',false); link.classed('dimmed',false);
      detailDiv.innerHTML='点击节点查看关联记忆';
    }
  });

  const simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(edges).id(d=>d.id).distance(80).strength(0.3))
    .force('charge', d3.forceManyBody().strength(-200))
    .force('center', d3.forceCenter(width/2, height/2))
    .force('collide', d3.forceCollide().radius(d=>12+d.weight*25))
    .on('tick', ()=>{
      link.attr('x1',d=>d.source.x).attr('y1',d=>d.source.y)
        .attr('x2',d=>d.target.x).attr('y2',d=>d.target.y);
      node.attr('transform', d=>`translate(${d.x},${d.y})`);
    });
  graphSimulation = simulation;
}

function switchView(view) {
  document.querySelectorAll('.toggle-btn').forEach(b=>b.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('graphView').style.display = view==='graph'?'block':'none';
  document.getElementById('memListSection').style.display = view==='list'?'block':'none';
  if(view==='graph'&&!graphData) initGraph();
}

window.addEventListener('resize', ()=>{
  if(graphSimulation) renderGraph();
});

initGraph();
</script>
</body>
</html>"""


# ── Graph Data ──
def _get_graph_data():
    """获取图谱数据：节点（特征词）+ 边（关系）+ 记忆关联。"""
    from memo.store.graph_store import graph_store

    # 从关系表构建图谱，不预先过滤
    rel_rows = db.fetchall(
        """SELECT DISTINCT fr.source_tag_id, fr.target_tag_id,
                  fr.hebbian_weight, fr.relation_type, fr.co_activation_count,
                  st.name as src_name, tt.name as tgt_name,
                  st.id as st_id, tt.id as tt_id
           FROM feature_relations fr
           JOIN feature_tags st ON fr.source_tag_id = st.id
           JOIN feature_tags tt ON fr.target_tag_id = tt.id
           WHERE fr.hebbian_weight >= 0.005
           ORDER BY fr.hebbian_weight DESC
           LIMIT 200"""
    )

    # 收集所有涉及的标签
    tag_map = {}
    edges = []
    seen_edges = set()

    for r in rel_rows:
        sid, tid = r["source_tag_id"], r["target_tag_id"]
        key = tuple(sorted([sid, tid]))
        if key in seen_edges:
            continue
        seen_edges.add(key)

        # 记录标签
        if sid not in tag_map:
            tag_map[sid] = {"id": sid, "name": r["src_name"]}
        if tid not in tag_map:
            tag_map[tid] = {"id": tid, "name": r["tgt_name"]}

        edges.append({
            "source": sid,
            "target": tid,
            "weight": round(r["hebbian_weight"], 4),
            "type": str(r["relation_type"]),
            "count": r["co_activation_count"],
        })

    # 补充标签的完整信息
    nodes = []
    for tid, tinfo in tag_map.items():
        tag = graph_store.get_tag(tid)
        if tag:
            nodes.append({
                "id": tag.id,
                "name": tag.name,
                "weight": round(tag.effective_weight, 4),
                "category": str(tag.category) if hasattr(tag.category, 'value') else str(tag.category),
                "activations": tag.total_activations,
                "dormant": tag.is_dormant,
            })
        else:
            nodes.append({
                "id": tid,
                "name": tinfo["name"],
                "weight": 0.1,
                "category": "CONCEPT",
                "activations": 0,
                "dormant": False,
            })

    # 记忆-标签关联
    tag_memories = {}
    for n in nodes[:30]:
        mentions = graph_store.get_tag_mentions(n["id"])
        tag_memories[n["id"]] = [
            {"id": m.memory_unit_id[:8], "score": round(m.relevance_score, 2)}
            for m in mentions[:5]
        ]

    return {"nodes": nodes, "edges": edges, "tag_memories": tag_memories}


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
        elif path == "/api/graph":
            self._json(_get_graph_data())
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
