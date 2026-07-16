<script>
  import { onMount, tick } from 'svelte';
  import { api } from '../lib/api.js';
  import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from 'd3-force';
  import { drag } from 'd3-drag';
  import { zoom } from 'd3-zoom';
  import { select } from 'd3-selection';

  let graph = { nodes: [], edges: [], tag_memories: {} };
  let svgEl, fullscreenSvgEl, detail = null, query = '', loading = true, fullscreen = false;
  let width = 960, height = 620;
  let fullscreenWidth = 1440, fullscreenHeight = 900;

  const color = (cat) => ({ PERSON:'#7c3aed', ORGANIZATION:'#2563eb', EVENT:'#ea580c', LOCATION:'#059669', OBJECT:'#be123c', CONCEPT:'#ca8a04' }[cat] || '#64748b');

  async function load() {
    loading = true;
    graph = await api.graph();
    loading = false;
    await tick();
    render(svgEl, width, height);
    if (fullscreen) render(fullscreenSvgEl, fullscreenWidth, fullscreenHeight);
  }

  function filteredNodes() {
    if (!query.trim()) return graph.nodes || [];
    const q = query.trim().toLowerCase();
    return (graph.nodes || []).filter(n => n.name.toLowerCase().includes(q) || String(n.category || '').toLowerCase().includes(q));
  }

  async function openFullscreen() {
    fullscreen = true;
    await tick();
    render(fullscreenSvgEl, fullscreenWidth, fullscreenHeight);
  }

  async function closeFullscreen() {
    fullscreen = false;
    await tick();
    render(svgEl, width, height);
  }

  function render(target = svgEl, w = width, h = height) {
    if (!target || !graph.nodes?.length) return;
    const nodeSet = new Set(filteredNodes().map(n => n.id));
    const nodes = (graph.nodes || []).filter(n => nodeSet.has(n.id)).map(n => ({ ...n }));
    const edges = (graph.edges || []).filter(e => nodeSet.has(e.source) && nodeSet.has(e.target)).map(e => ({ ...e }));

    const svg = select(target);
    svg.selectAll('*').remove();
    const root = svg.append('g');
    svg.call(zoom().scaleExtent([0.2, 5]).on('zoom', e => root.attr('transform', e.transform)));

    const link = root.append('g').attr('stroke-linecap', 'round').selectAll('line').data(edges).join('line')
      .attr('stroke', d => d.type === 'CONTRADICT' ? '#ef4444' : '#94a3b8')
      .attr('stroke-opacity', 0.38)
      .attr('stroke-width', d => Math.max(1, Math.min(8, d.weight * 24)));

    const node = root.append('g').selectAll('g').data(nodes).join('g').attr('class', 'graph-node')
      .style('cursor', 'pointer')
      .call(drag()
        .on('start', (event, d) => { if (!event.active) sim.alphaTarget(0.25).restart(); d.fx = d.x; d.fy = d.y; })
        .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on('end', (event, d) => { if (!event.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
      );

    node.append('circle')
      .attr('r', d => Math.max(8, Math.min(30, 8 + (d.weight || 0.1) * 36)))
      .attr('fill', d => color(d.category))
      .attr('fill-opacity', 0.86)
      .attr('stroke', 'rgba(255,255,255,.9)')
      .attr('stroke-width', 1.5);

    node.append('text')
      .attr('dy', d => -(14 + Math.max(8, Math.min(30, 8 + (d.weight || 0.1) * 36))))
      .attr('text-anchor', 'middle')
      .attr('font-size', fullscreen ? 13 : 12)
      .attr('font-weight', 700)
      .attr('fill', 'currentColor')
      .text(d => d.name.length > 10 ? d.name.slice(0, 10) + '…' : d.name);

    node.on('click', (_, d) => {
      const connected = new Set([d.id]);
      edges.forEach(e => { if ((e.source.id || e.source) === d.id) connected.add(e.target.id || e.target); if ((e.target.id || e.target) === d.id) connected.add(e.source.id || e.source); });
      node.attr('opacity', n => connected.has(n.id) ? 1 : 0.18);
      link.attr('opacity', e => ((e.source.id || e.source) === d.id || (e.target.id || e.target) === d.id) ? 1 : 0.08);
      detail = { ...d, memories: graph.tag_memories?.[d.id] || [], degree: connected.size - 1 };
    });

    svg.on('click', (event) => { if (event.target === target) { detail = null; node.attr('opacity', 1); link.attr('opacity', 1); } });

    const sim = forceSimulation(nodes)
      .force('link', forceLink(edges).id(d => d.id).distance(d => 90 - Math.min(50, d.weight * 80)).strength(d => Math.max(0.08, Math.min(0.55, d.weight * 2))))
      .force('charge', forceManyBody().strength(fullscreen ? -220 : -180))
      .force('center', forceCenter(w / 2, h / 2))
      .force('collide', forceCollide().radius(d => 26 + Math.max(8, Math.min(30, 8 + (d.weight || 0.1) * 36))))
      .on('tick', () => {
        link.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y);
        node.attr('transform', d => `translate(${d.x},${d.y})`);
      });
  }

  onMount(load);
  $: if (graph?.nodes && svgEl) { query; tick().then(() => render(svgEl, width, height)); }
  $: if (fullscreen && graph?.nodes && fullscreenSvgEl) { query; tick().then(() => render(fullscreenSvgEl, fullscreenWidth, fullscreenHeight)); }
</script>

<section class="page">
  <h1 class="page-title">图谱</h1>
  <p class="page-subtitle">基于特征词、赫布关系和记忆落点的真实交互图谱。可拖拽、缩放、搜索和点击节点查看关联。</p>

  <div class="toolbar" style="margin:20px 0">
    <input class="input" style="max-width:360px" bind:value={query} placeholder="搜索节点 / 类型" />
    <button class="btn" on:click={load}>刷新图谱</button>
    <button class="btn primary" on:click={openFullscreen}>全屏查看</button>
    <span class="item-meta">节点 {filteredNodes().length}/{graph.nodes?.length || 0} · 边 {graph.edges?.length || 0}</span>
  </div>

  <div class="two-col" style="grid-template-columns:minmax(0,1fr) 300px">
    <div class="card" style="min-height:640px;overflow:hidden;position:relative">
      <button class="btn" on:click={openFullscreen} style="position:absolute;right:14px;top:14px;z-index:2;background:rgba(255,255,255,.88);backdrop-filter:blur(10px)">⛶ 全屏</button>
      {#if loading}<div class="empty" style="padding:40px">图谱加载中...</div>{/if}
      <svg bind:this={svgEl} viewBox={`0 0 ${width} ${height}`} style="width:100%;height:640px;display:block"></svg>
    </div>
    <aside class="card card-pad" style="position:sticky;top:92px;align-self:start">
      {#if detail}
        <span class="badge green">{detail.category}</span>
        <h2 style="margin:12px 0">{detail.name}</h2>
        <div class="item-meta">权重 {detail.weight} · 激活 {detail.activations} · 邻居 {detail.degree}</div>
        <div class="section-head"><h2>关联记忆</h2></div>
        <div class="list">
          {#each detail.memories as m}<div class="item"><div class="item-title">{m.title || m.id}</div><div class="item-meta">相关度 {m.score}</div></div>{:else}<div class="empty">暂无关联记忆</div>{/each}
        </div>
      {:else}
        <div class="empty">点击节点查看详情；滚轮缩放，拖拽移动节点。</div>
      {/if}
    </aside>
  </div>
</section>

{#if fullscreen}
  <div class="graph-fullscreen" role="dialog" aria-label="图谱全屏查看">
    <div class="graph-fullscreen-head">
      <div>
        <strong>Memo 图谱全屏</strong>
        <span class="item-meta" style="margin-left:12px">节点 {filteredNodes().length}/{graph.nodes?.length || 0} · 边 {graph.edges?.length || 0}</span>
      </div>
      <div class="toolbar">
        <input class="input" style="width:300px" bind:value={query} placeholder="搜索节点 / 类型" />
        <button class="btn" on:click={load}>刷新</button>
        <button class="btn danger" on:click={closeFullscreen}>关闭</button>
      </div>
    </div>
    <div class="graph-fullscreen-body">
      <svg bind:this={fullscreenSvgEl} viewBox={`0 0 ${fullscreenWidth} ${fullscreenHeight}`} style="width:100%;height:100%;display:block"></svg>
      <aside class="graph-fullscreen-detail">
        {#if detail}
          <span class="badge green">{detail.category}</span>
          <h2 style="margin:12px 0">{detail.name}</h2>
          <div class="item-meta">权重 {detail.weight} · 激活 {detail.activations} · 邻居 {detail.degree}</div>
          <div class="section-head"><h2>关联记忆</h2></div>
          <div class="list">
            {#each detail.memories as m}<div class="item"><div class="item-title">{m.title || m.id}</div><div class="item-meta">相关度 {m.score}</div></div>{:else}<div class="empty">暂无关联记忆</div>{/each}
          </div>
        {:else}
          <div class="empty">点击节点查看详情。关闭后会回到原预览页。</div>
        {/if}
      </aside>
    </div>
  </div>
{/if}

<style>
  .graph-fullscreen {
    position: fixed;
    inset: 0;
    z-index: 9999;
    background: rgba(248, 250, 252, 0.96);
    color: var(--color-text);
    display: grid;
    grid-template-rows: auto 1fr;
    backdrop-filter: blur(18px);
  }
  :global(.dark) .graph-fullscreen { background: rgba(15, 23, 42, 0.96); }
  .graph-fullscreen-head {
    min-height: 72px;
    padding: 14px 22px;
    border-bottom: 1px solid var(--color-border);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
  }
  .graph-fullscreen-body {
    position: relative;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 330px;
    min-height: 0;
  }
  .graph-fullscreen-detail {
    border-left: 1px solid var(--color-border);
    background: var(--color-card);
    padding: 18px;
    overflow: auto;
  }
</style>
