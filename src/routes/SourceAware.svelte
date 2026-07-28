<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { RefreshCcw, Search, Database, AlertTriangle, Link2, Wrench, Eye, GitBranch, MessageSquareText } from '@lucide/svelte';

  let data = null;
  let quality = null;
  let detail = null;
  let evidence = null;
  let loading = false;
  let detailLoading = false;
  let error = '';
  let mode = 'sessions';
  let page = 1;
  let pageSize = '30';
  let q = '';
  let turnFilter = 'primary';
  let turnPreviewLimit = '80';
  let selectedSessionIds = new Set();
  let selectedTurnIds = new Set();
  let batchNote = '';
  let turnBatchNote = '';
  let batchBusy = false;

  $: currentPageSize = Number(pageSize || 30);
  $: total = data?.total || 0;
  $: totalPages = Math.max(1, Math.ceil(total / currentPageSize));
  $: titleSourceItems = data?.stats?.by_title_source || [];
  $: displayTitleSourceItems = data?.stats?.by_display_title_source || [];
  $: qualityFlags = quality?.flags || {};
  $: duplicateGroups = quality?.samples?.duplicate_title_groups || [];
  $: temporarySamples = quality?.samples?.temporary_task_like_hits || [];
  $: reviewStatusItems = quality?.review_summary?.by_status || [];
  $: reviewRetentionItems = quality?.review_summary?.by_retention || [];
  $: filteredTurns = filterTurns(detail?.turns || []);
  $: visibleTurns = filteredTurns.slice(0, Number(turnPreviewLimit || 80));

  function fmtTime(s) { return s ? String(s).slice(0, 19).replace('T', ' ') : ''; }
  function pct(n) { return `${Math.round((Number(n || 0)) * 100)}%`; }
  function short(s, n = 10) { return s ? String(s).slice(0, n) : '—'; }
  function sourceLabel(v) {
    const labels = {
      agent_original: '原始标题', first_user_turn: '首个用户问题', file_name: '文件名', user_custom: '人工展示标题',
      session_titles_json_path: 'Hana 标题(path)', session_titles_json_id: 'Hana 标题(sess)', db_title: '数据库标题',
      missing: '缺原始标题', generated_fallback: '生成兜底', unknown: '未知'
    };
    return labels[v] || v || '未知';
  }
  function filterTurns(turns) {
    if (turnFilter === 'all') return turns;
    if (turnFilter === 'tool') return turns.filter(t => t.is_tool_call || t.is_tool_result || t.role === 'tool');
    return turns.filter(t => t.role === 'user' || (t.role === 'assistant' && t.is_final_answer && !t.is_tool_call && !t.is_tool_result));
  }
  function sourceBadgeClass(v) {
    if (v === 'agent_original' || v === 'db_title' || v === 'session_titles_json_path' || v === 'session_titles_json_id') return 'green';
    if (v === 'missing' || v === 'generated_fallback' || v === 'first_user_turn' || v === 'file_name') return 'gold';
    return '';
  }

  async function load() {
    loading = true; error = '';
    try {
      const [overview, qualityResult] = await Promise.all([
        api.sourceAware({ mode, page, page_size: currentPageSize, q }),
        api.sourceAwareMemoryQuality({ limit: 8 }),
      ]);
      data = overview;
      quality = qualityResult;
    }
    catch (e) { error = e.message; }
    finally { loading = false; }
  }
  async function search() { page = 1; await load(); }
  async function switchMode(next) { mode = next; page = 1; await load(); }
  async function gotoPage(next) { page = Math.min(Math.max(1, next), totalPages); selectedSessionIds = new Set(); await load(); }
  function toggleSession(id) { selectedSessionIds = new Set(selectedSessionIds); selectedSessionIds.has(id) ? selectedSessionIds.delete(id) : selectedSessionIds.add(id); }
  function togglePageSessions() {
    const ids = (data?.sessions || []).map(s => s.id);
    const allSelected = ids.length > 0 && ids.every(id => selectedSessionIds.has(id));
    selectedSessionIds = new Set(allSelected ? [] : ids);
  }
  async function batchSessionReview(review_status) {
    if (!selectedSessionIds.size || batchBusy) return;
    batchBusy = true; error = '';
    try {
      await api.sourceSessionReviewAction({ source_session_ids: Array.from(selectedSessionIds), review_status, note: batchNote });
      selectedSessionIds = new Set(); batchNote = ''; await load();
    } catch (e) { error = e.message; } finally { batchBusy = false; }
  }

  async function openDetail(id) {
    detailLoading = true; error = ''; selectedTurnIds = new Set(); turnBatchNote = '';
    try { detail = await api.sourceAwareSession(id); }
    catch (e) { error = e.message; }
    finally { detailLoading = false; }
  }
  async function openEvidence(memoryId) {
    detailLoading = true; error = '';
    try { evidence = await api.sourceAwareEvidence(memoryId); }
    catch (e) { error = e.message; }
    finally { detailLoading = false; }
  }
  function closeDetailBackdrop(e) { if (e.target === e.currentTarget) detail = null; }
  function closeEvidenceBackdrop(e) { if (e.target === e.currentTarget) evidence = null; }
  function toggleTurn(id) { selectedTurnIds = new Set(selectedTurnIds); selectedTurnIds.has(id) ? selectedTurnIds.delete(id) : selectedTurnIds.add(id); }
  function toggleVisibleTurns() {
    const ids = visibleTurns.map(t => t.id);
    const allSelected = ids.length > 0 && ids.every(id => selectedTurnIds.has(id));
    selectedTurnIds = new Set(allSelected ? [] : ids);
  }
  async function batchTurnReview(review_status) {
    if (!selectedTurnIds.size || batchBusy) return;
    batchBusy = true; error = '';
    try {
      await api.sourceTurnReviewAction({ source_turn_ids: Array.from(selectedTurnIds), review_status, note: turnBatchNote });
      selectedTurnIds = new Set(); turnBatchNote = ''; await openDetail(detail.session.id);
    } catch (e) { error = e.message; } finally { batchBusy = false; }
  }

  onMount(load);
</script>

<section class="page">
  <div class="page-head-row">
    <div>
      <h1 class="page-title">Source-aware 审计</h1>
      <p class="page-subtitle">查看真实 Agent 来源会话、缺原始标题队列，以及 memory → turn → source_session 的证据链。默认只展示元信息，不展示原始正文。</p>
    </div>
    <button class="btn primary" class:loading={loading} disabled={loading} on:click={load}><RefreshCcw size={16}/> 刷新</button>
  </div>

  {#if error}<div class="card card-pad" style="color:var(--color-danger);margin-top:16px">{error}</div>{/if}

  <div class="grid cols-4" style="margin-top:22px">
    <div class="card stat-card"><Database size={20}/><div><strong>{loading && !data ? '—' : data?.stats?.source_sessions || 0}</strong><span>Source Sessions</span></div></div>
    <div class="card stat-card"><AlertTriangle size={20}/><div><strong>{loading && !data ? '—' : data?.stats?.missing_original_titles || 0}</strong><span>缺原始标题</span></div></div>
    <div class="card stat-card"><Link2 size={20}/><div><strong>{loading && !data ? '—' : data?.stats?.memories_with_evidence || 0}</strong><span>有证据记忆</span></div></div>
    <div class="card stat-card"><Wrench size={20}/><div><strong>{loading && !data ? '—' : pct(data?.stats?.tool_turn_ratio)}</strong><span>工具/过程占比</span></div></div>
  </div>

  <div class="card card-pad" style="margin-top:18px">
    <div class="section-head" style="margin:0 0 12px">
      <div>
        <h2>Memory Quality 只读审计</h2>
        <p class="section-subtitle">只展示候选风险，不删除、不合并、不写入真实记忆。</p>
      </div>
      <span class="badge {qualityFlags.pollution_pattern_hits ? 'gold' : 'green'}">系统/工具污染命中 {qualityFlags.pollution_pattern_hits ?? '—'}</span>
    </div>
    <div class="grid cols-4">
      <div class="card stat-card"><AlertTriangle size={18}/><div><strong>{qualityFlags.temporary_task_like_hits ?? '—'}</strong><span>疑似临时任务</span></div></div>
      <div class="card stat-card"><GitBranch size={18}/><div><strong>{qualityFlags.duplicate_title_groups ?? '—'}</strong><span>重复标题组</span></div></div>
      <div class="card stat-card"><Link2 size={18}/><div><strong>{quality?.counts?.memories_with_evidence ?? '—'}</strong><span>有证据记忆</span></div></div>
      <div class="card stat-card"><AlertTriangle size={18}/><div><strong>{qualityFlags.missing_original_titles ?? '—'}</strong><span>缺原始标题会话</span></div></div>
    </div>
    <div class="toolbar" style="gap:8px;flex-wrap:wrap;margin-top:12px">
      {#if quality?.review_summary?.ready}
        {#each reviewStatusItems as item}<span class="badge">状态：{item.review_status} · {item.c}</span>{/each}
        {#each reviewRetentionItems as item}<span class="badge">保留类：{item.retention_class} · {item.c}</span>{/each}
      {:else}
        <span class="badge gold">规则处理表尚未迁移</span>
      {/if}
    </div>
    <div class="grid cols-2" style="margin-top:12px">
      <div class="item">
        <div class="item-title">疑似临时任务样本</div>
        {#each temporarySamples.slice(0, 4) as item}
          <div class="item-summary">· {item.title} <span class="item-meta">({item.matched?.join(', ')})</span></div>
        {:else}
          <div class="item-meta">暂无命中</div>
        {/each}
      </div>
      <div class="item">
        <div class="item-title">重复标题候选</div>
        {#each duplicateGroups.slice(0, 4) as group}
          <div class="item-summary">· {group.count} 条：{group.items?.[0]?.title || group.normalized_title}</div>
        {:else}
          <div class="item-meta">暂无命中</div>
        {/each}
      </div>
    </div>
  </div>

  <div class="card card-pad" style="margin-top:18px">
    <div class="toolbar" style="justify-content:space-between;gap:12px;flex-wrap:wrap">
      <div class="toolbar" style="gap:8px;flex-wrap:wrap">
        <button class="btn" class:primary={mode === 'sessions'} on:click={() => switchMode('sessions')}>Source Sessions</button>
        <button class="btn" class:primary={mode === 'missing_titles'} on:click={() => switchMode('missing_titles')}>Missing Titles</button>
        <div style="position:relative"><Search size={15} style="position:absolute;left:10px;top:10px;color:var(--color-text-secondary)"/><input class="input" style="padding-left:32px;width:320px" bind:value={q} on:keydown={(e)=>{ if(e.key==='Enter') search(); }} placeholder="搜索展示标题、Agent、session id" /></div>
      </div>
      <div class="toolbar" style="gap:8px">
        <select class="input" style="width:110px" bind:value={pageSize} on:change={search}>
          <option value="30">30 / 页</option>
          <option value="50">50 / 页</option>
          <option value="100">100 / 页</option>
        </select>
        <button class="btn" disabled={loading} on:click={search}>搜索</button>
      </div>
    </div>
    <div class="toolbar" style="gap:8px;flex-wrap:wrap;margin-top:14px">
      {#each titleSourceItems as item}<span class="badge {sourceBadgeClass(item.title_source)}">原始：{sourceLabel(item.title_source)} · {item.c}</span>{/each}
      {#each displayTitleSourceItems as item}<span class="badge {sourceBadgeClass(item.display_title_source)}">展示：{sourceLabel(item.display_title_source)} · {item.c}</span>{/each}
    </div>
    <div class="item-meta" style="margin-top:12px">当前：{mode === 'missing_titles' ? 'Missing Titles 队列' : 'Source Sessions 总览'} · 匹配 {total} 条 · 第 {page} / {totalPages} 页</div>
    <div class="batch-bar" style="margin-top:12px">
      <button class="btn" on:click={togglePageSessions}>{(data?.sessions || []).length && (data?.sessions || []).every(s => selectedSessionIds.has(s.id)) ? '取消本页全选' : '全选本页'}</button>
      <span class="item-meta">已选 {selectedSessionIds.size} 个会话（仅对勾选项生效）</span>
      <input class="input" bind:value={batchNote} placeholder="统一处理理由（可选）" />
      <button class="btn" disabled={!selectedSessionIds.size || batchBusy} on:click={() => batchSessionReview('in_review')}>标记处理中</button>
      <button class="btn primary" disabled={!selectedSessionIds.size || batchBusy} on:click={() => batchSessionReview('done')}>标记完成</button>
      <button class="btn" disabled={!selectedSessionIds.size || batchBusy} on:click={() => batchSessionReview('needs_review')}>标记待审</button>
    </div>
  </div>

  {#if data?.schema_status && !data.schema_status.ready}
    <div class="card card-pad" style="margin-top:16px;border-color:color-mix(in srgb, var(--color-warning) 36%, var(--color-border))">
      <div class="item-title">Source-aware schema 尚未完整就绪</div>
      <div class="item-summary">当前数据库缺少必要表/字段，Dashboard 暂不读取详情，避免误报。生产库修复或真实导入前需要先按闸门流程确认。</div>
      <div class="raw-box" style="margin-top:12px">{JSON.stringify(data.schema_status.missing, null, 2)}</div>
    </div>
  {/if}

  {#if loading}
    <div class="list stagger" style="margin-top:14px">{#each Array(5) as _}<div class="card card-pad"><div class="skeleton" style="height:104px"></div></div>{/each}</div>
  {:else}
    <div class="list stagger" style="margin-top:16px">
      {#each data?.sessions || [] as s}
        <div class="card card-pad">
          <div class="item-row">
            <div style="display:flex;gap:10px;align-items:flex-start;min-width:0">
              <input type="checkbox" checked={selectedSessionIds.has(s.id)} on:change={() => toggleSession(s.id)} aria-label="选择会话" />
              <div style="min-width:0">
              <div class="item-title">{s.display_title || s.agent_session_id || '未命名来源会话'}</div>
              <div class="item-meta">{s.source_agent || 'unknown'} · {short(s.id, 8)} · {fmtTime(s.updated_at || s.imported_at)}</div>
              </div>
            </div>
            <button class="btn" on:click={() => openDetail(s.id)}><Eye size={15}/> 详情</button>
          </div>
          <div class="toolbar" style="gap:8px;flex-wrap:wrap;margin-top:12px">
            <span class="badge {sourceBadgeClass(s.title_source)}">Agent 原始标题：{sourceLabel(s.title_source)}</span>
            <span class="badge {sourceBadgeClass(s.display_title_source)}">展示标题：{sourceLabel(s.display_title_source)}</span>
            {#if s.is_missing_title}<span class="badge gold">展示标题，不是原始标题</span>{/if}
          </div>
          <div class="item-summary">
            turns {s.turn_count || s.message_count || 0} · episodes {s.episode_count || 0} · memories {s.memory_count || 0} · evidence {s.evidence_count || 0} · tool calls {s.tool_call_count || 0} · tool results {s.tool_result_count || 0}
          </div>
          <div class="item-meta">path: {s.source_path || '—'} · hash: {short(s.source_hash, 12)}</div>
        </div>
      {:else}
        <div class="empty card">暂无 source-aware 数据。可先用测试库 apply 验证，生产导入前仍需确认。</div>
      {/each}
    </div>
  {/if}

  <div class="toolbar" style="justify-content:flex-end;margin-top:18px">
    <button class="btn" disabled={loading || page <= 1} on:click={() => gotoPage(page - 1)}>上一页</button>
    <span class="item-meta">第 {page} / {totalPages} 页，每页 {pageSize} 条，匹配 {total} 条</span>
    <button class="btn" disabled={loading || page >= totalPages} on:click={() => gotoPage(page + 1)}>下一页</button>
  </div>
</section>

{#if detail}
  <div class="modal-backdrop" role="presentation" on:click={closeDetailBackdrop}>
    <div class="detail-modal wide-modal">
      <div class="modal-head">
        <div>
          <div class="toolbar" style="gap:8px;flex-wrap:wrap">
            <span class="badge green">{detail.session.source_agent}</span>
            <span class="badge {sourceBadgeClass(detail.session.title_source)}">原始：{sourceLabel(detail.session.title_source)}</span>
            <span class="badge {sourceBadgeClass(detail.session.display_title_source)}">展示：{sourceLabel(detail.session.display_title_source)}</span>
          </div>
          <h2>{detail.session.display_title || detail.session.agent_session_id}</h2>
          <div class="item-meta">{detail.session.id} · {fmtTime(detail.session.updated_at || detail.session.imported_at)}</div>
        </div>
        <button class="icon-btn" on:click={() => detail = null}>×</button>
      </div>

      <div class="grid cols-4">
        <div class="card stat-card"><MessageSquareText size={18}/><div><strong>{detail.turns?.length || 0}</strong><span>Turns</span></div></div>
        <div class="card stat-card"><GitBranch size={18}/><div><strong>{detail.episodes?.length || 0}</strong><span>Episodes</span></div></div>
        <div class="card stat-card"><Database size={18}/><div><strong>{detail.memory_units?.length || 0}</strong><span>Memory Units</span></div></div>
        <div class="card stat-card"><Link2 size={18}/><div><strong>{detail.memory_units?.reduce((n,m)=>n + Number(m.evidence_count || 0), 0) || 0}</strong><span>Evidence</span></div></div>
      </div>

      <div class="modal-section">
        <h3>Source Session 元信息</h3>
        <div class="raw-box">original_title: {detail.session.original_title || '缺失'}\ndisplay_title: {detail.session.display_title || '—'}\nsource_path: {detail.session.source_path || '—'}\nsource_hash: {detail.session.source_hash || '—'}</div>
      </div>

      <div class="modal-section">
        <h3>Memory Units</h3>
        <div class="list">
          {#each detail.memory_units || [] as m}
            <div class="item">
              <div class="item-row">
                <div>
                  <div class="item-title">{m.title || m.summary || m.id}</div>
                  <div class="item-meta">{m.memory_type} · {m.memory_granularity} · {m.speaker_scope} · 置信度 {pct(m.source_confidence)} · evidence {m.evidence_count}</div>
                  <div class="item-summary">{m.summary}</div>
                </div>
                <button class="btn" on:click={() => openEvidence(m.id)}><Link2 size={15}/> 证据链</button>
              </div>
            </div>
          {:else}<div class="empty card">暂无 memory_units</div>{/each}
        </div>
      </div>

      <div class="modal-section">
        <div class="section-head" style="margin:0 0 12px">
          <div>
            <h3>Turns 元信息（不展示原文）</h3>
            <div class="item-meta">当前显示 {visibleTurns.length} 条 / 筛选后 {filteredTurns.length} 条 / 已加载 {detail.turns?.length || 0} 条。详情页默认只预览，不代表数据被截断。</div>
          </div>
          <div class="toolbar" style="gap:8px;flex-wrap:wrap">
            <select class="input" style="width:190px" bind:value={turnFilter}>
              <option value="primary">只看用户和最终回答</option>
              <option value="tool">只看 tool/process</option>
              <option value="all">全部 turns</option>
            </select>
            <select class="input" style="width:110px" bind:value={turnPreviewLimit}>
              <option value="80">前 80</option>
              <option value="150">前 150</option>
              <option value="300">前 300</option>
            </select>
          </div>
        </div>
        <div class="batch-bar" style="margin:0 0 12px">
          <button class="btn" on:click={toggleVisibleTurns}>{visibleTurns.length && visibleTurns.every(t => selectedTurnIds.has(t.id)) ? '取消当前全选' : '全选当前显示'}</button>
          <span class="item-meta">已选 {selectedTurnIds.size} 条（仅对勾选项生效）</span>
          <input class="input" bind:value={turnBatchNote} placeholder="统一处理理由（可选）" />
          <button class="btn" disabled={!selectedTurnIds.size || batchBusy} on:click={() => batchTurnReview('in_review')}>标记处理中</button>
          <button class="btn" disabled={!selectedTurnIds.size || batchBusy} on:click={() => batchTurnReview('done')}>标记完成</button>
          <button class="btn danger" disabled={!selectedTurnIds.size || batchBusy} on:click={() => batchTurnReview('soft_deleted')}>批量软删除</button>
        </div>
        <div class="list">
          {#each visibleTurns as t}
            <div class="item" class:muted-turn={t.review_status === 'soft_deleted'}>
              <div class="item-row">
                <label style="display:flex;gap:10px;align-items:flex-start;min-width:0;cursor:pointer">
                  <input type="checkbox" checked={selectedTurnIds.has(t.id)} on:change={() => toggleTurn(t.id)} aria-label="选择对话内容" />
                  <span>
                    <span class="item-title">#{t.turn_index} · {t.role} · {t.source_event_type || 'message'}</span>
                    <span class="item-meta" style="display:block">len {t.content_length} · hash {short(t.content_hash, 12)} · {fmtTime(t.timestamp)} · final {t.is_final_answer ? 'yes' : 'no'} · tool {t.tool_name || '—'} · 状态 {t.review_status}</span>
                    {#if t.review_note}<span class="item-meta" style="display:block">理由：{t.review_note}</span>{/if}
                  </span>
                </label>
              </div>
            </div>
          {:else}<div class="empty card">暂无 turns</div>{/each}
        </div>
      </div>
    </div>
  </div>
{/if}

{#if evidence}
  <div class="modal-backdrop" role="presentation" on:click={closeEvidenceBackdrop}>
    <div class="detail-modal wide-modal">
      <div class="modal-head">
        <div>
          <div class="toolbar" style="gap:8px;flex-wrap:wrap"><span class="badge green">Memory Evidence</span><span class="badge">{evidence.memory.memory_type}</span><span class="badge">{evidence.memory.memory_granularity}</span></div>
          <h2>{evidence.memory.title || evidence.memory.summary || evidence.memory.id}</h2>
          <div class="item-meta">memory {evidence.memory.id} · session {evidence.source_session?.display_title || evidence.source_session?.id || '—'}</div>
        </div>
        <button class="icon-btn" on:click={() => evidence = null}>×</button>
      </div>
      <div class="modal-section"><h3>Memory Unit</h3><div class="raw-box">summary: {evidence.memory.summary || '—'}\nspeaker_scope: {evidence.memory.speaker_scope}\nsource_confidence: {pct(evidence.memory.source_confidence)}\nepisode: {evidence.episode?.title || evidence.memory.episode_id || '—'}</div></div>
      <div class="modal-section">
        <h3>Evidence Turns（只读元信息）</h3>
        <div class="list">
          {#each evidence.evidence || [] as ev}
            <div class="item">
              <div class="item-title">#{ev.turn_index} · {ev.role} · {ev.evidence_role}</div>
              <div class="item-meta">weight {ev.weight} · len {ev.content_length} · hash {short(ev.content_hash, 12)} · {fmtTime(ev.timestamp)} · {ev.source_event_type}</div>
              <div class="item-summary">source_session: {ev.display_title || ev.source_session_id} · original title: {ev.original_title || '缺失'} · display source: {sourceLabel(ev.display_title_source)}</div>
            </div>
          {:else}<div class="empty card">暂无 evidence links</div>{/each}
        </div>
      </div>
    </div>
  </div>
{/if}

{#if detailLoading}
  <div class="toast-card" style="position:fixed;right:24px;bottom:24px;z-index:10000">加载中…</div>
{/if}
