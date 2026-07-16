"""Memo 看板 —— 单文件 Web 应用，零额外依赖。

启动：python scripts/memo_dashboard.py
访问：http://localhost:9120
"""

import json
import mimetypes
import sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIST = PROJECT_ROOT / "dashboard" / "dist"
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
#graphContainer.fullscreen { display: none; }

/* 主导航 */
.nav-tabs { display: flex; gap: 0; margin-bottom: 16px; border-bottom: 2px solid var(--border); }
.nav-tab { padding: 8px 24px; cursor: pointer; font-size: 16px; font-weight: 600; color: var(--muted); border-bottom: 2px solid transparent; margin-bottom: -2px; transition: .15s; }
.nav-tab:hover { color: var(--text); }
.nav-tab.active { color: var(--accent); border-bottom-color: var(--accent); }

/* 人格画像 */
.persona-layout { display: grid; grid-template-columns: 180px 1fr; gap: 16px; min-height: 400px; }
.dim-nav { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 8px 0; }
.dim-nav-item { padding: 8px 16px; cursor: pointer; font-size: 13px; color: var(--muted); transition: .15s; border-left: 3px solid transparent; }
.dim-nav-item:hover { background: var(--bg); color: var(--text); }
.dim-nav-item.active { color: var(--accent); border-left-color: var(--accent); background: var(--bg); font-weight: 600; }
.dim-nav-item .count { font-size: 11px; color: var(--muted); float: right; }
.assertion-card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; margin-bottom: 10px; position: relative; }
.assertion-card.locked { border-color: var(--orange); }
.assertion-card .conf-bar { height: 4px; background: var(--border); border-radius: 2px; margin: 8px 0; }
.assertion-card .conf-fill { height: 100%; border-radius: 2px; background: var(--green); transition: width .3s; }
.assertion-card .conf-fill.low { background: var(--orange); }
.assertion-card .conf-fill.mid { background: var(--accent); }
.assertion-card .meta { font-size: 11px; color: var(--muted); display: flex; gap: 12px; margin-top: 6px; }
.assertion-card .actions { position: absolute; top: 10px; right: 12px; display: flex; gap: 6px; }
.assertion-card .actions button { background: none; border: 1px solid var(--border); border-radius: 4px; cursor: pointer; font-size: 12px; padding: 2px 8px; color: var(--muted); }
.assertion-card .actions button:hover { background: var(--bg); color: var(--text); }
.assertion-card .actions button.danger:hover { background: var(--red); color: #fff; border-color: var(--red); }
.persona-toolbar { display: flex; gap: 8px; margin-bottom: 12px; align-items: center; }
.persona-toolbar button { padding: 6px 14px; border: 1px solid var(--border); border-radius: 6px; background: var(--card); cursor: pointer; font-size: 13px; color: var(--text); }
.persona-toolbar button:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
.persona-toolbar select { padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; background: var(--card); color: var(--text); }
</style>
</head>
<body>
<div class="nav-tabs">
  <div class="nav-tab active" onclick="switchTab('memo')">🧠 Memo 记忆看板</div>
  <div class="nav-tab" onclick="switchTab('todos')">📋 待办</div>
</div>
<h2>赫布学习 + 扩散激活 + 网状记忆图谱</h2>

<div id="memoContent">
<div class="stats" id="stats"></div>

<div id="sharedContent">
<h3>🔥 特征词云 <span style="font-size:12px;color:var(--muted);margin-left:8px;">点击词 → 搜索</span></h3>
<div class="tag-cloud" id="tagCloud"></div>

<h3>🕸️ 特征词图谱 <span style="font-size:12px;color:var(--muted);margin-left:8px;">拖拽节点 | 滚轮缩放 | 点击高亮关联</span></h3>
<div class="view-toggle">
  <button class="toggle-btn active" onclick="switchView('graph')">图谱视图</button>
  <button class="toggle-btn" onclick="switchView('list')">列表视图</button>
  <button class="toggle-btn" onclick="switchView('persona')">🧬 人格画像</button>
</div>
<div id="graphView">
  <div id="graphContainer" style="background:var(--card);border:1px solid var(--border);border-radius:8px;overflow:hidden;height:500px;position:relative;">
    <button id="fsBtn" onclick="toggleFullscreen()" style="position:absolute;top:8px;right:8px;z-index:5;background:var(--accent);border:none;border-radius:6px;padding:5px 12px;cursor:pointer;color:#fff;font-size:13px;font-weight:600;" title="全屏查看">🔍 全屏</button>
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

<!-- 图谱全屏弹窗 -->
<div id="graphOverlay" style="display:none;position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:300;background:rgba(0,0,0,0.7);justify-content:center;align-items:center;">
  <div style="background:var(--bg);border-radius:12px;width:94vw;height:90vh;position:relative;padding:8px;">
    <button onclick="toggleFullscreen()" style="position:absolute;top:12px;right:16px;z-index:5;background:var(--red);border:none;border-radius:6px;padding:6px 14px;cursor:pointer;color:#fff;font-size:13px;font-weight:600;">✕ 关闭</button>
    <div id="graphTooltipFull" style="display:none;position:absolute;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px;pointer-events:none;z-index:10;max-width:300px;color:var(--text);"></div>
    <svg id="graphSvgFull" width="100%" height="100%"></svg>
  </div>
</div>

<h3>📝 记忆列表</h3>
<div id="memListSection" style="display:none;">
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
  <select id="agentFilter" onchange="loadMemories()">
    <option value="">全部来源</option>
    <option value="Hanako">Hanako</option>
    <option value="WorkBuddy">WorkBuddy</option>
  </select>
  <button onclick="loadMemories()">搜索</button>
</div>
<div class="mem-list" id="memList"></div>
<div id="loadMore" style="text-align:center;padding:16px;"><button onclick="loadMore()" style="padding:8px 24px;border:1px solid var(--border);border-radius:8px;background:var(--card);cursor:pointer;color:var(--text)">加载更多</button></div>
</div>

<!-- 人格画像 -->
<div id="personaView" style="display:none;">
<div class="persona-toolbar">
  <button onclick="refreshPersona()">🔄 增量提炼</button>
  <select id="sensitivitySelect" onchange="setSensitivity(this.value)">
    <option value="1">灵敏度 1 (几乎全人格)</option>
    <option value="2" selected>灵敏度 2 (默认)</option>
    <option value="3">灵敏度 3 (中等)</option>
    <option value="4">灵敏度 4 (少量人格)</option>
    <option value="5">灵敏度 5 (几乎不依赖)</option>
  </select>
  <span style="font-size:12px;color:var(--muted);margin-left:auto" id="personaStats"></span>
</div>
<div class="persona-layout">
  <div class="dim-nav" id="dimNav"></div>
  <div id="assertionList"></div>
</div>
</div>

</div>
</div>
</div>

<!-- 待办管理（独立页） -->
<div id="todoView" style="display:none;">
<div class="persona-toolbar">
  <div id="todoRisk" style="flex:1"></div>
  <div style="display:flex;gap:8px">
    <button onclick="refreshTodos()">🔄 刷新</button>
  </div>
</div>
<div class="todo-filters" style="display:flex;gap:6px;margin-bottom:12px">
  <button class="toggle-btn active" data-key="all" onclick="filterTodos('all')">全部</button>
  <button class="toggle-btn" data-key="high" onclick="filterTodos('high')">高优</button>
  <button class="toggle-btn" data-key="doing" onclick="filterTodos('doing')">进行中</button>
  <button class="toggle-btn" data-key="done" onclick="filterTodos('done')">已完成</button>
</div>
<div id="todoList" style="max-height:500px;overflow-y:auto"></div>
</div>

<div class="modal" id="modal" onclick="if(event.target===this)closeModal()">
  <div class="modal-content" id="modalContent"></div>
</div>

<script>
let allMemories = [];
let allTags = [];

async function load() {
  const [stats, tags] = await Promise.all([
    fetch('/api/stats').then(r=>r.json()),
    fetch('/api/tags').then(r=>r.json()),
  ]);
  allTags = tags;
  renderStats(stats);
  renderTags(tags);
  loadMemories(true);
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
  loadMemories(true);
}

let memOffset = 0;
const MEM_LIMIT = 200;

async function loadMemories(reset = true) {
  if (reset) memOffset = 0;
  const q = document.getElementById('searchInput').value.trim();
  const type = document.getElementById('typeFilter').value;
  const agent = document.getElementById('agentFilter').value;
  let url = `/api/memories?limit=${MEM_LIMIT}&offset=${memOffset}`;
  if (q) url += `&q=${encodeURIComponent(q)}`;
  if (agent) url += `&agent=${encodeURIComponent(agent)}`;
  const mems = await fetch(url).then(r=>r.json());
  // 客户端再按 type 过滤（API 暂不支持 type 参数）
  const filtered = type ? mems.filter(m=>m.memory_type===type) : mems;
  if (reset) {
    allMemories = filtered;
  } else {
    allMemories = allMemories.concat(filtered);
  }
  renderMemories(allMemories);
  document.getElementById('loadMore').style.display = mems.length < MEM_LIMIT ? 'none' : '';
}

function loadMore() {
  memOffset += MEM_LIMIT;
  loadMemories(false);
}

function renderMemories(mems) {
  const list = document.getElementById('memList');
  if(!mems.length) { list.innerHTML='<div class="empty">没有匹配的记忆</div>'; return; }
  list.innerHTML = `<div style="font-size:12px;color:var(--muted);margin-bottom:8px">共 ${mems.length} 条</div>` + mems.map(m=>`
    <div class="mem-item" onclick="showDetail('${m.id}')">
      <div class="title">${esc(m.title)}</div>
      <div class="meta">
        <span style="color:var(--accent)">${m.memory_type}</span>
        <span>${m.source_agent||'?'}</span>
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
  renderGraph('main');
}

function renderGraph(mode) {
  mode = mode || 'main';
  const isFull = mode === 'full';
  const svgId = isFull ? '#graphSvgFull' : '#graphSvg';
  const container = isFull
    ? document.querySelector('#graphOverlay > div')
    : document.getElementById('graphContainer');
  const width = container.clientWidth - (isFull ? 16 : 0);
  const height = isFull ? window.innerHeight * 0.88 : 500;
  const svg = d3.select(svgId).attr('viewBox', [0,0,width,height]);
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
    .attr('stroke','#2da44e')
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

  const tooltip = document.getElementById(isFull ? 'graphTooltipFull' : 'graphTooltip');
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

  // 力导向参数：主屏紧凑，全屏适中
  const simParams = isFull
    ? { linkDist: 60, linkStrength: 0.4, charge: -15, collideBase: 7 }
    : { linkDist: 25, linkStrength: 0.7, charge: -15, collideBase: 5 };

  const simulation = d3.forceSimulation(nodes)
    .alphaDecay(0.02)  // 模拟逐渐稳定
    .force('link', d3.forceLink(edges).id(d=>d.id).distance(simParams.linkDist).strength(simParams.linkStrength))
    .force('charge', d3.forceManyBody().strength(simParams.charge))
    .force('center', d3.forceCenter(width/2, height/2))
    .force('collide', d3.forceCollide().radius(d=>simParams.collideBase+d.weight*20))
    .on('tick', ()=>{
      link.attr('x1',d=>d.source.x).attr('y1',d=>d.source.y)
        .attr('x2',d=>d.target.x).attr('y2',d=>d.target.y);
      node.attr('transform', d=>`translate(${d.x},${d.y})`);
    });
  graphSimulation = simulation;
}

function toggleFullscreen() {
  const overlay = document.getElementById('graphOverlay');
  const btn = document.getElementById('fsBtn');
  if (overlay.style.display === 'flex') {
    overlay.style.display = 'none';
    btn.textContent = '🔍 全屏';
    btn.style.background = 'var(--accent)';
  } else {
    overlay.style.display = 'flex';
    btn.textContent = '✕ 退出';
    btn.style.background = 'var(--red)';
    setTimeout(() => renderGraph('full'), 100);
  }
}
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    const overlay = document.getElementById('graphOverlay');
    if (overlay.style.display === 'flex') toggleFullscreen();
  }
});

function switchTab(tab) {
  document.querySelectorAll('.nav-tab').forEach(t=>t.classList.remove('active'));
  [...document.querySelectorAll('.nav-tab')].find(t=>t.textContent.includes(tab==='memo'?'Memo':'待办'))?.classList.add('active');
  const isTodo = tab==='todos';
  document.getElementById('memoContent').style.display = isTodo?'none':'';
  document.getElementById('todoView').style.display = isTodo?'block':'none';
  document.querySelector('h2').style.display = isTodo?'none':'';
  if(isTodo && !todoData) loadTodos();
}

function switchView(view) {
  document.querySelectorAll('.toggle-btn').forEach(b=>b.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('graphView').style.display = view==='graph'?'block':'none';
  document.getElementById('memListSection').style.display = view==='list'?'block':'none';
  document.getElementById('personaView').style.display = view==='persona'?'block':'none';
  if(view==='graph'&&!graphData) initGraph();
  if(view==='persona'&&!personaData) loadPersona();
}

window.addEventListener('resize', ()=>{
  if(graphSimulation) renderGraph();
});

// ── 人格画像 ──
let personaData = null;
let currentDim = null;

async function loadPersona() {
  const r = await fetch('/api/persona');
  personaData = await r.json();
  const dims = Object.keys(personaData.assertions);
  const total = Object.values(personaData.assertions).flat().length;
  document.getElementById('personaStats').textContent = total + ' 条断言 · 上次: ' + (personaData.settings.last_baseline_at?.slice(0,16)||'未建');
  document.getElementById('sensitivitySelect').value = personaData.settings.sensitivity_level||'2';
  renderDimNav(dims);
  if(dims.length) selectDim(dims[0]);
}

function renderDimNav(dims) {
  const nav = document.getElementById('dimNav');
  const dimLabels = {
    value:'💎 价值观', decision:'🎯 决策模式', identity:'🏷️ 身份',
    preference:'❤️ 偏好', sensitivity:'⚠️ 敏感话题', relationship:'🔗 关系',
    knowledge:'📚 知识边界', communication:'💬 沟通风格',
    mental_model:'🧩 思维模型', emotion:'🌊 情绪特征'
  };
  nav.innerHTML = dims.map(d=>{
    const cnt = personaData.assertions[d].length;
    return `<div class="dim-nav-item" onclick="selectDim('${d}')">${dimLabels[d]||d}<span class="count">${cnt}</span></div>`;
  }).join('');
}

function selectDim(dim) {
  currentDim = dim;
  document.querySelectorAll('.dim-nav-item').forEach(el=>el.classList.remove('active'));
  [...document.querySelectorAll('.dim-nav-item')].find(el=>el.textContent.includes(dim))?.classList.add('active');
  renderAssertions(personaData.assertions[dim]||[]);
}

function renderAssertions(list) {
  const container = document.getElementById('assertionList');
  if(!list.length) { container.innerHTML = '<div class="empty">该维度暂无断言</div>'; return; }
  container.innerHTML = list.map(a=>{
    const confPct = Math.round(a.confidence*100);
    const confClass = a.confidence<0.4?'low':a.confidence<0.7?'mid':'';
    const lockIcon = a.locked ? '🔒' : '';
    return `<div class="assertion-card${a.locked?' locked':''}">
      <div class="actions">
        ${a.locked
          ? `<button onclick="toggleLock('${a.id}',false)" title="解锁">🔓</button>`
          : `<button onclick="toggleLock('${a.id}',true)" title="锁定">🔒</button>`}
        <button onclick="editAssertion('${a.id}')" title="编辑">✏️</button>
        <button class="danger" onclick="deleteAssertion('${a.id}')" title="删除">🗑️</button>
      </div>
      <div style="font-size:14px;line-height:1.5">${lockIcon} ${esc(a.assertion)}</div>
      <div class="conf-bar"><div class="conf-fill ${confClass}" style="width:${confPct}%"></div></div>
      <div class="meta">
        <span>置信度 ${confPct}%</span>
        <span>来源 ${a.evidences.length} 条记忆</span>
        <span>${a.updated_at?.slice(0,10)||'?'}</span>
      </div>
    </div>`;
  }).join('');
}

async function toggleLock(id, lock) {
  await fetch('/api/persona/action', {method:'POST',body:JSON.stringify({action:lock?'lock':'unlock',id})});
  loadPersona();
}

async function deleteAssertion(id) {
  if(!confirm('确定删除？')) return;
  await fetch('/api/persona/action', {method:'POST',body:JSON.stringify({action:'delete',id})});
  loadPersona();
}

function editAssertion(id) {
  const a = Object.values(personaData.assertions).flat().find(x=>x.id===id);
  if(!a) return;
  const text = prompt('编辑断言:', a.assertion);
  if(text && text!==a.assertion) {
    fetch('/api/persona/action', {method:'POST',body:JSON.stringify({action:'edit',id,assertion:text})}).then(()=>loadPersona());
  }
}

async function refreshPersona() {
  const r = await fetch('/api/persona/action', {method:'POST',body:JSON.stringify({action:'refresh'})});
  const result = await r.json();
  alert('刷新完成: ' + JSON.stringify(result));
  personaData = null;
  loadPersona();
}

async function setSensitivity(level) {
  await fetch('/api/persona/action', {method:'POST',body:JSON.stringify({action:'edit',id:'__settings__',assertion:level})});
  // 直接更新数据库中的设置
  await fetch('/api/persona/action', {method:'POST',body:JSON.stringify({action:'set_sensitivity',id:level})});
}

// ── 待办管理 ──
let todoData = null;
let todoFilter = 'all';

async function loadTodos() {
  const r = await fetch('/api/todos');
  todoData = await r.json();
  // 风险横幅（独立）
  const riskDiv = document.getElementById('todoRisk');
  const risk = todoData.risk;
  if(risk.summary==='无风险') {
    riskDiv.innerHTML = '<div style="background:var(--card);border:1px solid var(--green);border-radius:6px;padding:10px 16px;color:var(--green);font-size:14px">✅ 无风险</div>';
  } else {
    riskDiv.innerHTML = '<div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;padding:10px 16px;font-size:14px">⚠️ <strong>'+risk.summary+'</strong>';
    if(risk.overdue&&risk.overdue.length) riskDiv.innerHTML += '<div style="margin-top:4px;font-size:13px">逾期: '+risk.overdue.map(x=>x.title).join(', ')+'</div>';
    if(risk.urgent&&risk.urgent.length) riskDiv.innerHTML += '<div style="margin-top:4px;font-size:13px">紧急: '+risk.urgent.map(x=>x.title).join(', ')+'</div>';
    riskDiv.innerHTML += '</div>';
  }
  // 更新筛选按钮数量
  const allTodos = (todoData.todos||[]).concat(todoData.done||[]);
  const counts = {
    all: allTodos.filter(t=>t.status!=='cancelled').length,
    high: allTodos.filter(t=>t.priority==='high'&&t.status!=='cancelled'&&t.status!=='done').length,
    doing: allTodos.filter(t=>t.status==='doing').length,
    done: (todoData.done||[]).length
  };
  document.querySelectorAll('.todo-filters .toggle-btn').forEach(b=>{
    const raw = b.getAttribute('data-label') || b.textContent.trim().split('(')[0].trim();
    b.setAttribute('data-label', raw);
    const key = b.getAttribute('data-key');
    b.textContent = raw + ' (' + (counts[key]!=null?counts[key]:'?') + ')';
  });
  filterTodos(todoFilter);
}

function refreshTodos() { todoData=null; loadTodos(); }

function filterTodos(f) {
  todoFilter = f;
  document.querySelectorAll('.todo-filters .toggle-btn').forEach(b=>b.classList.remove('active'));
  [...document.querySelectorAll('.todo-filters .toggle-btn')].forEach(b=>{
    const t = b.textContent.trim();
    if((f==='all'&&t.startsWith('全部'))||(f==='high'&&t.startsWith('高优'))||(f==='doing'&&t.startsWith('进行中'))||(f==='done'&&t.startsWith('已完成'))) b.classList.add('active');
  });
  let list = f==='done' ? (todoData.done||[]) : (todoData.todos||[]);
  if(f==='high') list = list.filter(t=>t.priority==='high');
  if(f==='doing') list = list.filter(t=>t.status==='doing');
  renderTodos(list);
}

function renderTodos(list) {
  const container = document.getElementById('todoList');
  if(!list.length) { container.innerHTML='<div class="empty">暂无待办</div>'; return; }
  const priIcon = {high:'🔴',medium:'🟡',low:'🟢'};
  container.innerHTML = list.map(t=>`
    <div class="assertion-card">
      <div class="actions">
        ${t.status!=='done'?`<button onclick="closeTodo('${t.id}')" title="完成">✅</button>`:''}
        ${t.status==='done'?`<button onclick="reopenTodo('${t.id}')" title="重开">🔄</button>`:''}
        ${t.status!=='cancelled'?`<button class="danger" onclick="cancelTodo('${t.id}')" title="取消">❌</button>`:''}
      </div>
      <div style="font-size:14px;line-height:1.5">${priIcon[t.priority]||'⚪'} ${esc(t.title)}</div>
      <div class="meta">
        <span>${t.status==='done'?'✅已完成':t.status==='cancelled'?'❌已取消':t.status}</span>
        <span>来源: ${t.source_agent||'?'}</span>
        ${t.due_date?`<span>📅 ${t.due_date}</span>`:''}
        ${t.completed_at?`<span>完成于 ${t.completed_at.slice(0,10)}</span>`:''}
      </div>
    </div>
  `).join('');
}

async function closeTodo(id) {
  const t = (todoData.todos||[]).concat(todoData.done||[]).find(x=>x.id===id);
  if(!confirm('确定完成: '+t?.title+'?')) return;
  await fetch('/api/todo/action',{method:'POST',body:JSON.stringify({action:'close',id})});
  refreshTodos();
}
async function reopenTodo(id) {
  await fetch('/api/todo/action',{method:'POST',body:JSON.stringify({action:'reopen',id})});
  refreshTodos();
}
async function cancelTodo(id) {
  const t = (todoData.todos||[]).concat(todoData.done||[]).find(x=>x.id===id);
  if(!confirm('确定取消: '+t?.title+'? (不可恢复)')) return;
  await fetch('/api/todo/action',{method:'POST',body:JSON.stringify({action:'cancel',id})});
  refreshTodos();
}

initGraph();
</script>
</body>
</html>"""


# ── Graph Data ──
def _memory_explanation(status: str, pinned: bool, user_weight: float, tags: list[str], memory_type: str = ""):
    """面向用户的记忆治理/召回解释，不暴露底层算法名。"""
    status = status or "active"
    reasons = []
    participates = status not in {"wrong", "muted", "deleted"}
    if tags:
        reasons.append("它和这些关键词相关：" + "、".join(tags[:5]))
    if str(memory_type).upper() in {"DECISION", "PREFERENCE", "REASONING"}:
        reasons.append("它记录的是判断、偏好或推理，比普通流水信息更适合作为参考")
    if pinned:
        reasons.append("你已经把它标为重要，所以系统会更优先保留它")
    if status == "active":
        reasons.append("它当前处于可引用状态")
    elif status == "expired":
        reasons.append("它已被标记为过期，仍可参考，但会被明显降权")
    elif status == "wrong":
        reasons.append("它已被标记为错误，默认不会再参与召回")
    elif status == "muted":
        reasons.append("它已被设置为不再引用，默认不会参与召回")
    elif status == "deleted":
        reasons.append("它已被软删除，默认不会参与召回")
    try:
        w = float(user_weight or 1.0)
        if w > 1.05:
            reasons.append("你提高过它的权重，因此它会更容易被想起")
        elif w < 0.95 and participates:
            reasons.append("你降低过它的权重，因此它只会谨慎参与参考")
    except Exception:
        w = 1.0
    if not reasons:
        reasons.append("它目前没有特殊治理标记，按普通长期记忆处理")
    return {
        "summary": "这条记忆会根据相关性、状态和你的治理操作决定是否参与回答。",
        "reasons": reasons,
        "participates": participates,
        "status": status,
        "pinned": bool(pinned),
        "user_weight": w,
        "suggested_actions": ["pin", "mark_wrong", "mark_expired", "mute", "delete", "restore"],
    }


def _list_space_classification_queue(limit: int = 50):
    rows = db.fetchall(
        """SELECT q.*, mu.title, mu.summary, mu.created_at AS memory_created_at
           FROM space_classification_queue q
           JOIN memory_units mu ON mu.id = q.memory_id
           WHERE q.status = 'pending'
           ORDER BY q.confidence DESC, q.created_at DESC
           LIMIT ?""",
        (limit,),
    )
    return [dict(r) for r in rows]


def _refresh_space_classification_queue(limit: int = 100, threshold: float = 0.25):
    """扫描近期未绑定 Space 的记忆，生成待确认归类候选。"""
    from datetime import datetime
    from memo.space.detector import space_detector
    from memo.store.database import new_id

    rows = db.fetchall(
        """SELECT mu.id, mu.title, mu.summary, mu.raw_text
           FROM memory_units mu
           LEFT JOIN space_memories sm ON sm.memory_id = mu.id
           WHERE sm.memory_id IS NULL
             AND mu.is_superseded = 0
             AND COALESCE(mu.status, 'active') NOT IN ('wrong','muted','deleted')
           ORDER BY mu.created_at DESC
           LIMIT ?""",
        (limit,),
    )
    created = 0
    now = datetime.now().isoformat()
    for r in rows:
        text = "\n".join([r["title"] or "", r["summary"] or "", (r["raw_text"] or "")[:1200]])
        candidates = space_detector.detect(text, top_k=2)
        for c in candidates:
            if float(c.get("confidence", 0)) < threshold:
                continue
            exists = db.fetchone(
                "SELECT id FROM space_classification_queue WHERE memory_id = ? AND suggested_space_id = ?",
                (r["id"], c["space_id"]),
            )
            if exists:
                continue
            db.execute(
                """INSERT INTO space_classification_queue
                   (id, memory_id, suggested_space_id, suggested_space_name, confidence, reason, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (new_id(), r["id"], c["space_id"], c.get("name", ""), c.get("confidence", 0), c.get("reason", ""), now, now),
            )
            created += 1
    db.commit()
    return {"created": created, "scanned": len(rows), "pending": len(_list_space_classification_queue(limit=1000))}


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
    for n in nodes[:60]:
        mentions = graph_store.get_tag_mentions(n["id"])
        items = []
        for m in mentions[:8]:
            mem = db.fetchone("SELECT id, title, summary FROM memory_units WHERE id = ?", (m.memory_unit_id,))
            items.append({
                "id": m.memory_unit_id,
                "title": mem["title"] if mem else m.memory_unit_id[:8],
                "summary": mem["summary"] if mem else "",
                "score": round(m.relevance_score, 2),
            })
        tag_memories[n["id"]] = items

    return {"nodes": nodes, "edges": edges, "tag_memories": tag_memories}


# ── HTTP Server ──
class MemoHandler(BaseHTTPRequestHandler):
    def _get_query_param(self, key: str, default: str = "") -> str:
        """从 URL query string 解析参数。"""
        from urllib.parse import parse_qs
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        vals = params.get(key, [default])
        return vals[0] if vals else default

    def do_GET(self):
        try:
            self._do_GET()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._json({"error": str(e)}, 500)

    def do_POST(self):
        try:
            self._do_GET()  # 统一路由处理
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._json({"error": str(e)}, 500)

    def _do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            if (DASHBOARD_DIST / "index.html").exists():
                self._serve_static(DASHBOARD_DIST / "index.html")
            else:
                self._html(PAGE)
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        elif path.startswith("/assets/") and (DASHBOARD_DIST / path.lstrip("/")).exists():
            self._serve_static(DASHBOARD_DIST / path.lstrip("/"))
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
        elif path == "/api/persona":
            from memo.persona.extractor import get_active_assertions, get_persona_settings
            assertions = get_active_assertions()
            settings = get_persona_settings()
            # 按维度分组
            by_dim = {}
            for a in assertions:
                d = a["dimension"]
                if d not in by_dim:
                    by_dim[d] = []
                evs = a.get("evidences", "[]")
                import json as _j
                ev_list = _j.loads(evs) if isinstance(evs, str) else evs
                evidence_details = []
                for eid in ev_list[:8]:
                    mem = db.fetchone("SELECT id, title, summary, created_at FROM memory_units WHERE id LIKE ? OR id = ?", (str(eid) + "%", str(eid)))
                    if mem:
                        evidence_details.append(dict(mem))
                by_dim[d].append({
                    "id": a["id"],
                    "dimension": a["dimension"],
                    "assertion": a["assertion"],
                    "confidence": a["confidence"],
                    "evidences": ev_list,
                    "evidence_details": evidence_details,
                    "signal_level": a["signal_level"],
                    "locked": a["locked"],
                    "is_custom": a["is_custom"],
                    "updated_at": a["updated_at"],
                })
            self._json({"assertions": by_dim, "settings": settings})
        elif path == "/api/memories":
            # 解析查询参数
            q = self._get_query_param("q", "")
            agent = self._get_query_param("agent", "")
            limit = int(self._get_query_param("limit", "500"))
            offset = int(self._get_query_param("offset", "0"))

            status = self._get_query_param("status", "active")
            include_deleted = self._get_query_param("include_deleted", "false").lower() == "true"
            sql = (
                "SELECT mu.*, s.agent_id as source_agent FROM memory_units mu"
                " LEFT JOIN sessions s ON mu.session_id = s.id"
                " WHERE mu.is_superseded=0"
            )
            if not include_deleted:
                sql += " AND COALESCE(mu.status, 'active') != 'deleted'"
            if status and status != "all":
                sql += " AND COALESCE(mu.status, 'active') = ?"
                params = [status]
            else:
                params = []
            if q:
                sql += " AND (mu.title LIKE ? OR mu.summary LIKE ? OR mu.raw_text LIKE ?)"
                params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
            if agent:
                sql += " AND s.agent_id = ?"
                params.append(agent)
            sql += " ORDER BY COALESCE(mu.pinned,0) DESC, mu.created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = db.fetchall(sql, tuple(params))
            from memo.store.graph_store import graph_store as gs
            mems = []
            for r in rows:
                tags = gs.get_memory_tags(r["id"])
                status_value = r["status"] if "status" in r.keys() else "active"
                pinned_value = bool(r["pinned"]) if "pinned" in r.keys() else False
                weight_value = r["user_weight"] if "user_weight" in r.keys() else 1.0
                tag_names = [t.name for t in tags]
                mems.append({
                    "id": r["id"], "session_id": r["session_id"],
                    "title": r["title"], "summary": r["summary"],
                    "memory_type": r["memory_type"], "confidence": r["confidence"],
                    "valid_from": r["valid_from"],
                    "status": status_value,
                    "user_weight": weight_value,
                    "pinned": pinned_value,
                    "user_note": r["user_note"] if "user_note" in r.keys() else "",
                    "source_agent": r["source_agent"] or "?",
                    "feature_tags": tag_names,
                    "explanation": _memory_explanation(status_value, pinned_value, weight_value, tag_names, r["memory_type"]),
                })
            self._json(mems)
        elif path == "/api/memory/action":
            self._handle_memory_action()
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
                "status": getattr(mem, "status", "active"),
                "user_weight": getattr(mem, "user_weight", 1.0),
                "pinned": getattr(mem, "pinned", False),
                "user_note": getattr(mem, "user_note", ""),
                "audit": memory_store.get_memory_audit(mem_id, limit=20),
                "feature_tags": [t.name for t in tags],
                "explanation": _memory_explanation(getattr(mem, "status", "active"), getattr(mem, "pinned", False), getattr(mem, "user_weight", 1.0), [t.name for t in tags], str(mem.memory_type)),
            })
        elif path == "/api/todos":
            from memo.todo.manager import list_todos, get_todo_stats, check_risk
            space_id = self._get_query_param("space_id", "")
            stats = get_todo_stats()
            risk = check_risk()
            todos = list_todos(status="todo+doing", limit=50, space_id=space_id)
            done = list_todos(status="done", limit=10, space_id=space_id)
            self._json({"todos": todos, "done": done, "stats": stats, "risk": risk})
        elif path == "/api/spaces":
            include_archived = self._get_query_param("include_archived", "false").lower() == "true"
            space_type = self._get_query_param("type", "")
            self._json(engine.space_list(include_archived=include_archived, type=space_type))
        elif path == "/api/space/classification-queue":
            limit = int(self._get_query_param("limit", "50"))
            self._json(_list_space_classification_queue(limit=limit))
        elif path == "/api/space/action":
            self._handle_space_action()
        elif path.startswith("/api/space/"):
            sid = path.split("/")[-1]
            mode = self._get_query_param("mode", "brief")
            profile = engine.space_profile(sid, mode=mode)
            if profile.get("error"):
                self._json(profile, 404); return
            self._json(profile)
        elif path == "/api/todo/action":
            self._handle_todo_action()
        elif path.startswith("/api/todo/"):
            tid = path.split("/")[-1]
            from memo.todo.manager import get_todo, get_todo_history
            todo = get_todo(tid)
            if not todo:
                self._json({"error": "not found"}, 404); return
            history = get_todo_history(tid)
            self._json({"todo": todo, "history": history})
        elif path == "/api/persona/action":
            self._handle_persona_action()
        elif path == "/api/governance":
            self._json(engine.governance_overview(limit=int(self._get_query_param("limit", "50"))))
        elif path == "/api/memory/link":
            self._handle_memory_link()
        else:
            self._json({"error": "not found"}, 404)

    def _handle_space_action(self):
        import json as _j
        length = int(self.headers.get("Content-Length", 0))
        body = _j.loads(self.rfile.read(length)) if length > 0 else {}
        action = body.get("action", "")
        if action == "create":
            result = engine.space_create(
                name=body.get("name", ""),
                type=body.get("type", "general"),
                description=body.get("description", ""),
                goal=body.get("goal", ""),
                aliases=body.get("aliases", []),
                created_by="dashboard",
            )
            self._json(result); return
        if action == "update":
            result = engine.space_update(body.get("id", ""), **body.get("fields", {}))
            self._json(result); return
        if action == "archive":
            result = engine.space_archive(body.get("id", ""))
            self._json(result); return
        if action == "restore":
            result = engine.space_restore(body.get("id", ""))
            self._json(result); return
        if action == "add_alias":
            result = engine.space_add_alias(body.get("space_id", body.get("id", "")), body.get("alias", ""))
            self._json(result); return
        if action == "remove_alias":
            result = engine.space_remove_alias(body.get("space_id", body.get("id", "")), body.get("alias", ""))
            self._json(result); return
        if action == "detect":
            result = engine.space_detect(body.get("conversation", ""), top_k=int(body.get("top_k", 3)))
            self._json(result); return
        if action == "bind_memory":
            result = engine.space_bind_memory(
                space_id=body.get("space_id", ""),
                memory_id=body.get("memory_id", ""),
                relation_type=body.get("relation_type", "related"),
                relevance=float(body.get("relevance", 0.8)),
                created_by="dashboard",
            )
            self._json(result); return
        if action == "unbind_memory":
            result = engine.space_unbind_memory(
                space_id=body.get("space_id", ""),
                memory_id=body.get("memory_id", ""),
            )
            self._json(result); return
        if action == "summarize":
            result = engine.space_profile(body.get("id", body.get("space_id", "")), mode=body.get("mode", "brief"), persist=bool(body.get("persist", False)))
            self._json(result); return
        if action == "refresh_classification_queue":
            self._json(_refresh_space_classification_queue(limit=int(body.get("limit", 100)), threshold=float(body.get("threshold", 0.25)))); return
        if action in {"accept_candidate", "reject_candidate", "new_space_candidate"}:
            self._handle_space_candidate_action(action, body); return
        self._json({"error": f"unknown action {action}"}, 400)

    def _handle_space_candidate_action(self, action: str, body: dict):
        from datetime import datetime
        cid = body.get("id", "")
        row = db.fetchone("SELECT * FROM space_classification_queue WHERE id = ?", (cid,))
        if not row:
            self._json({"error": "candidate not found"}, 404); return
        now = datetime.now().isoformat()
        if action == "reject_candidate":
            db.execute("UPDATE space_classification_queue SET status='rejected', decided_by='dashboard', decided_at=?, updated_at=? WHERE id=?", (now, now, cid))
            db.commit(); self._json({"ok": True}); return
        if action == "accept_candidate":
            sid = body.get("space_id") or row["suggested_space_id"]
            result = engine.space_bind_memory(space_id=sid, memory_id=row["memory_id"], relation_type="detected", relevance=float(row["confidence"] or 0.7), created_by="classification_queue")
            db.execute("UPDATE space_classification_queue SET status='accepted', decided_space_id=?, decided_by='dashboard', decided_at=?, updated_at=? WHERE id=?", (sid, now, now, cid))
            db.commit(); self._json(result); return
        if action == "new_space_candidate":
            result = engine.space_create(name=body.get("name") or row["suggested_space_name"] or "新空间", type=body.get("type", "general"), description=body.get("description", "由自动归类确认队列创建"), created_by="classification_queue")
            sid = result.get("id")
            if sid:
                engine.space_bind_memory(space_id=sid, memory_id=row["memory_id"], relation_type="detected", relevance=float(row["confidence"] or 0.7), created_by="classification_queue")
                db.execute("UPDATE space_classification_queue SET status='new_space', decided_space_id=?, decided_by='dashboard', decided_at=?, updated_at=? WHERE id=?", (sid, now, now, cid))
                db.commit()
            self._json(result); return

    def _handle_memory_action(self):
        import json as _j
        length = int(self.headers.get("Content-Length", 0))
        body = _j.loads(self.rfile.read(length)) if length > 0 else {}
        memory_id = body.get("id", "") or body.get("memory_id", "")
        action = body.get("action", "")
        if not memory_id:
            self._json({"error": "missing memory id"}, 400); return
        result = engine.memory_govern(
            memory_id=memory_id,
            action=action,
            actor="dashboard",
            note=body.get("note", ""),
            status=body.get("status"),
            user_weight=body.get("user_weight"),
            pinned=body.get("pinned"),
            user_note=body.get("user_note"),
        )
        if result.get("error"):
            self._json(result, 400); return
        self._json(result)

    def _handle_memory_link(self):
        import json as _j
        length = int(self.headers.get("Content-Length", 0))
        body = _j.loads(self.rfile.read(length)) if length > 0 else {}
        result = engine.memory_link(
            source_memory_id=body.get("source_memory_id", ""),
            target_memory_id=body.get("target_memory_id", ""),
            relation_type=body.get("relation_type", "MERGED_INTO"),
            confidence=float(body.get("confidence", 0.8)),
            reason=body.get("reason", ""),
            created_by="dashboard",
        )
        self._json(result)

    def _handle_persona_action(self):
        import json as _j
        length = int(self.headers.get("Content-Length", 0))
        body = _j.loads(self.rfile.read(length)) if length > 0 else {}
        action = body.get("action", "")
        aid = body.get("id", "")
        if not aid:
            self._json({"error": "missing id"}, 400); return
        now = __import__("datetime").datetime.now().isoformat()
        if action == "lock":
            db.execute("UPDATE persona_assertions SET locked=1, updated_at=? WHERE id=?", (now, aid))
        elif action == "unlock":
            db.execute("UPDATE persona_assertions SET locked=0, updated_at=? WHERE id=?", (now, aid))
        elif action == "delete":
            db.execute("UPDATE persona_assertions SET is_superseded=1, updated_at=? WHERE id=?", (now, aid))
        elif action == "edit":
            new_text = body.get("assertion", "")
            new_conf = body.get("confidence")
            if new_text:
                db.execute("UPDATE persona_assertions SET assertion=?, updated_at=? WHERE id=?", (new_text, now, aid))
            if new_conf is not None:
                db.execute("UPDATE persona_assertions SET confidence=?, updated_at=? WHERE id=?", (float(new_conf), now, aid))
        elif action == "create":
            from memo.store.database import new_id
            dim = body.get("dimension", "preference")
            text = body.get("assertion", "").strip()
            if not text:
                self._json({"error": "missing assertion"}, 400); return
            db.execute(
                """INSERT INTO persona_assertions
                   (id, dimension, assertion, confidence, evidences, signal_level, locked, is_custom, created_at, updated_at, last_refreshed)
                   VALUES (?, ?, ?, ?, '[]', 2, ?, 1, ?, ?, ?)""",
                (new_id(), dim, text, float(body.get("confidence", 0.8)), 1 if body.get("locked", False) else 0, now, now, now),
            )
        elif action == "refresh":
            from memo.core.engine import engine as _eng
            result = _eng.update_persona()
            self._json(result); return
        elif action == "set_sensitivity":
            db.execute("INSERT OR REPLACE INTO persona_settings (key, value) VALUES ('sensitivity_level', ?)", (str(aid),))
            db.commit()
            self._json({"ok": True}); return
        else:
            self._json({"error": f"unknown action {action}"}, 400); return
        db.commit()
        self._json({"ok": True})

    def _handle_todo_action(self):
        import json as _j
        length = int(self.headers.get("Content-Length", 0))
        body = _j.loads(self.rfile.read(length)) if length > 0 else {}
        action = body.get("action", "")
        tid = body.get("id", "")
        from memo.todo.manager import add_todo, close_todos, reopen_todos, update_todo
        if action == "create":
            result = add_todo(
                title=body.get("title", ""),
                description=body.get("description", ""),
                priority=body.get("priority", "medium"),
                due_date=body.get("due_date", ""),
                space_id=body.get("space_id", ""),
                source_agent="dashboard",
            )
            self._json(result); return
        if action == "close":
            close_todos([tid], agent="dashboard")
        elif action == "reopen":
            reopen_todos([tid], agent="dashboard")
        elif action == "cancel":
            update_todo(tid, status="cancelled", agent="dashboard")
        elif action == "update":
            update_todo(
                tid,
                title=body.get("title", ""),
                priority=body.get("priority", ""),
                status=body.get("status", ""),
                due_date=body.get("due_date", ""),
                description=body.get("description", ""),
                agent="dashboard",
            )
        else:
            self._json({"error": f"unknown action {action}"}, 400); return
        self._json({"ok": True})

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(code); self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Content-Length",len(body))
        self.end_headers(); self.wfile.write(body)

    def _html(self, html):
        body = html.encode()
        self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length",len(body)); self.end_headers(); self.wfile.write(body)

    def _serve_static(self, filepath: Path):
        body = filepath.read_bytes()
        content_type = mimetypes.guess_type(str(filepath))[0] or "application/octet-stream"
        if filepath.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif filepath.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif filepath.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache" if filepath.name == "index.html" else "public, max-age=31536000, immutable")
        self.send_header("Content-Length", len(body))
        self.end_headers(); self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # 安静模式


def main():
    port = 9120
    server = ThreadingHTTPServer(("0.0.0.0", port), MemoHandler)
    import sys; sys.stdout.write(f"\n  Memo 看板已启动 → http://localhost:{port}\n  按 Ctrl+C 停止\n"); sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  看板已停止")


if __name__ == "__main__":
    main()
