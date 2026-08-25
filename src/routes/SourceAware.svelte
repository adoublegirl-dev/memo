<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { RefreshCcw, Search, Database, AlertTriangle, Link2, Wrench, GitBranch, MessageSquareText } from '@lucide/svelte';

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
  let sort = 'updated_desc';
  let turnFilter = 'reviewable';
  let turnRole = 'all';
  let turnOrder = 'asc';
  let turnPreviewLimit = '80';
  let detailTab = 'turns';
  let selectedSessionIds = new Set();
  let selectedTurnIds = new Set();
  let batchNote = '';
  let turnBatchNote = '';
  let batchBusy = false;
  let backfillBusy = false;
  let backfillMessage = '';
  let expandedTurnIds = new Set();

  $: currentPageSize = Number(pageSize || 30);
  $: total = data?.total || 0;
  $: totalPages = Math.max(1, Math.ceil(total / currentPageSize));
  $: titleSourceItems = data?.stats?.by_title_source || [];
  $: displayTitleSourceItems = data?.stats?.by_display_title_source || [];
  $: qualityFlags = quality?.flags || {};
  $: duplicateGroups = quality?.samples?.duplicate_title_groups || [];
  $: temporarySamples = quality?.samples?.temporary_task_like_hits || [];
  $: pollutionSamples = quality?.samples?.pollution_pattern_hits || [];
  $: lowEvidenceSamples = quality?.samples?.low_evidence_hits || [];
  $: reviewStatusItems = quality?.review_summary?.by_status || [];
  $: reviewRetentionItems = quality?.review_summary?.by_retention || [];
  $: visibleTurns = detail?.turns || [];
  $: turnPage = Number(detail?.turn_page || 1);
  $: turnTotalPages = Math.max(1, Math.ceil(Number(detail?.turn_total || 0) / Number(detail?.turn_page_size || 80)));

  function fmtTime(s) { return s ? String(s).slice(0, 19).replace('T', ' ') : ''; }
  function pct(n) { return `${Math.round((Number(n || 0)) * 100)}%`; }
  function roleLabel(role) { return ({ user:'用户', assistant:'AI', tool:'工具', system:'系统' }[role] || '其他'); }
  function reviewLabel(status) { return ({ active:'待处理', in_review:'处理中', done:'已完成', soft_deleted:'已软删除' }[status] || status || '待处理'); }
  function qualityStatusLabel(status) { return ({ auto_accepted:'规则通过', auto_flagged:'待复核', auto_muted:'默认不引用', auto_rejected:'规则排除', llm_reviewed:'LLM 已复核', human_reviewed:'人工已复核' }[status] || status || '未知'); }
  function retentionLabel(value) { return ({ long_term:'长期记忆', temporary_task:'临时任务', project_state:'项目状态', noise:'噪声', candidate:'候选' }[value] || value || '未知'); }
  function short(s, n = 10) { return s ? String(s).slice(0, n) : '—'; }
  function sourceLabel(v) {
    const labels = {
      agent_original: '原始标题', first_user_turn: '首个用户问题', file_name: '文件名', user_custom: '人工展示标题',
      session_titles_json_path: 'Hana 标题(path)', session_titles_json_id: 'Hana 标题(sess)', db_title: '数据库标题',
      missing: '缺原始标题', generated_fallback: '生成兜底', unknown: '未知'
    };
    return labels[v] || v || '未知';
  }
  function preview(text, max = 420) {
    const value = String(text || '').trim();
    return value.length > max ? `${value.slice(0, max)}…` : (value || '（该轮没有可显示的正文）');
  }
  function toggleTurnExpanded(id) { expandedTurnIds = new Set(expandedTurnIds); expandedTurnIds.has(id) ? expandedTurnIds.delete(id) : expandedTurnIds.add(id); }
  async function changeTurnFilter(next) { turnFilter = next; selectedTurnIds = new Set(); expandedTurnIds = new Set(); await openDetail(detail.session.id, true, 1); }
  async function changeTurnRole(next) { turnRole = next; selectedTurnIds = new Set(); expandedTurnIds = new Set(); await openDetail(detail.session.id, true, 1); }
  async function changeTurnOrder(next) { turnOrder = next; selectedTurnIds = new Set(); expandedTurnIds = new Set(); await openDetail(detail.session.id, true, 1); }
  async function gotoTurnPage(next) { await openDetail(detail.session.id, true, Math.min(Math.max(1, next), turnTotalPages)); }
  function sourceBadgeClass(v) {
    if (v === 'agent_original' || v === 'db_title' || v === 'session_titles_json_path' || v === 'session_titles_json_id') return 'green';
    if (v === 'missing' || v === 'generated_fallback' || v === 'first_user_turn' || v === 'file_name') return 'gold';
    return '';
  }

  async function load() {
    loading = true; error = '';
    try {
      const [overview, qualityResult] = await Promise.all([
        api.sourceAware({ mode, page, page_size: currentPageSize, q, sort }),
        api.sourceAwareMemoryQuality({ limit: 8 }),
      ]);
      data = overview;
      quality = qualityResult;
    }
    catch (e) { error = e.message; }
    finally { loading = false; }
  }
  async function search() { page = 1; await load(); }
  async function changeSort() { page = 1; await load(); }
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

  async function openDetail(id, preserveView = false, pageOverride = 1) {
    detailLoading = true; error = '';
    if (!preserveView) { detailTab = 'turns'; turnFilter = 'reviewable'; turnRole = 'all'; turnOrder = 'asc'; selectedTurnIds = new Set(); expandedTurnIds = new Set(); turnBatchNote = ''; backfillMessage = ''; }
    try { detail = await api.sourceAwareSession(id, { turn_filter: turnFilter, turn_role: turnRole, turn_order: turnOrder, turn_page: pageOverride, turn_page_size: turnPreviewLimit }); }
    catch (e) { error = e.message; }
    finally { detailLoading = false; }
  }
  async function openEvidence(memoryId) {
    detailLoading = true; error = '';
    try { evidence = await api.sourceAwareEvidence(memoryId); }
    catch (e) { error = e.message; }
    finally { detailLoading = false; }
  }
  async function backfillCurrentSessionContent() {
    if (!detail?.session?.id || backfillBusy) return;
    backfillBusy = true; error = ''; backfillMessage = '';
    try {
      const inspection = await api.sourceContentBackfillAction({ source_session_id: detail.session.id, apply: false });
      if (!inspection.path_exists) { backfillMessage = '本地原始会话文件已不存在，无法自动回填。'; return; }
      if (!inspection.fillable) { backfillMessage = inspection.mismatched ? `没有可安全回填的正文；有 ${inspection.mismatched} 条记录校验不一致。` : '没有发现可回填的正文。'; return; }
      const accepted = confirm(`检测到 ${inspection.fillable} 条可安全回填的原始对话。继续后会先在线备份数据库，且只填写空正文，绝不覆盖已有内容。是否继续？`);
      if (!accepted) return;
      const result = await api.sourceContentBackfillAction({ source_session_id: detail.session.id, apply: true, confirm: 'BACKFILL_CONTENT' });
      backfillMessage = `已回填 ${result.updated || 0} 条原始对话，操作前备份已创建。`;
      await openDetail(detail.session.id, true, 1);
    } catch (e) { error = e.message; }
    finally { backfillBusy = false; }
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
      const result = await api.sourceTurnReviewAction({ source_turn_ids: Array.from(selectedTurnIds), review_status, note: turnBatchNote });
      const preserveSessionId = detail.session.id;
      selectedTurnIds = new Set(); turnBatchNote = '';
      await openDetail(preserveSessionId, true, 1);
      if (result.auto_completed_session_ids?.includes(preserveSessionId)) await load();
    } catch (e) { error = e.message; } finally { batchBusy = false; }
  }

  onMount(async () => {
    await load();
    const sourceSessionId = sessionStorage.getItem('memo-open-source-session');
    if (sourceSessionId) {
      sessionStorage.removeItem('memo-open-source-session');
      await openDetail(sourceSessionId);
    }
  });
</script>

<style>
  :global(.detail-modal.wide-modal) { width:min(1240px, calc(100vw - 32px)); max-height:90vh; }
  :global(.modal-backdrop) { padding:16px; }
  .detail-tabs { display:flex; gap:4px; margin:18px 0 2px; padding-bottom:10px; border-bottom:1px solid var(--border-subtle, rgba(148,163,184,.22)); }
  .detail-tabs button { display:inline-flex; align-items:center; gap:7px; padding:8px 12px; border:0; border-radius:8px; background:transparent; color:var(--color-text-secondary, #64748b); cursor:pointer; font-weight:600; white-space:nowrap; }
  .detail-tabs button.active { background:rgba(91,157,255,.12); color:var(--color-primary, #3178c6); }
  .detail-tabs span { padding:1px 6px; border-radius:999px; background:rgba(91,157,255,.14); font-size:11px; }
  .batch-bar { align-items:flex-start; }
  .batch-bar .btn { white-space:nowrap; flex:0 0 auto; }
  .batch-bar .input { min-width:180px; }
  .turn-item { border-left:3px solid rgba(91,157,255,.26); }
  .turn-item.user-turn { border-left-color:#4f8cff; background:color-mix(in srgb, #4f8cff 5%, var(--bg-card, white)); }
  .turn-item.assistant-turn { border-left-color:#28a66a; background:color-mix(in srgb, #28a66a 5%, var(--bg-card, white)); }
  .turn-item.muted-turn { opacity:.58; border-left-color:#94a3b8; }
  .turn-item.muted-turn .turn-preview { background:rgba(100,116,139,.08); }
  .role-badge { display:inline-flex; align-items:center; padding:2px 8px; border-radius:999px; font-size:12px; font-weight:700; margin-right:7px; }
  .role-badge.user { color:#2563eb; background:rgba(79,140,255,.14); }
  .role-badge.assistant { color:#168354; background:rgba(40,166,106,.14); }
  .role-badge.other { color:var(--color-text-secondary, #64748b); background:rgba(100,116,139,.13); }
  .turn-preview { display:block; margin-top:9px; padding:10px 12px; border-radius:8px; background:rgba(91,157,255,.09); color:var(--text, #172033); font-size:13px; font-weight:500; line-height:1.72; white-space:pre-wrap; word-break:break-word; }
  .turn-preview.expanded { max-height:480px; overflow:auto; }
  .btn.compact { padding:5px 9px; font-size:12px; white-space:nowrap; }
  .turn-pager { display:flex; justify-content:flex-end; align-items:center; gap:10px; margin-top:14px; flex-wrap:wrap; }
  .turn-filter-controls { display:flex; align-items:center; justify-content:flex-end; gap:8px; flex-wrap:wrap; }
  .turn-filter-controls .input { min-width:178px; flex:1 1 190px; }
  @media (max-width:720px) { .turn-filter-controls { justify-content:stretch; width:100%; } .turn-filter-controls .input { width:100%; } }
</style>

<section class="page">
  <div class="page-head-row">
    <div>
      <h1 class="page-title">来源溯源</h1>
      <p class="page-subtitle">查看记忆来自哪段会话、哪些原始对话构成证据，以及是否存在待回填或质量风险。原文只在打开单个本地会话详情时读取。</p>
    </div>
    <button class="btn primary" class:loading={loading} disabled={loading} on:click={load}><RefreshCcw size={16}/> 刷新</button>
  </div>

  {#if error}<div class="card card-pad" style="color:var(--color-danger);margin-top:16px">{error}</div>{/if}

  <div class="grid cols-4" style="margin-top:22px">
    <div class="card stat-card"><Database size={20}/><div><strong>{loading && !data ? '—' : data?.stats?.source_sessions || 0}</strong><span>来源会话</span></div></div>
    <div class="card stat-card"><AlertTriangle size={20}/><div><strong>{loading && !data ? '—' : data?.stats?.missing_original_titles || 0}</strong><span>缺原始标题</span></div></div>
    <div class="card stat-card"><Link2 size={20}/><div><strong>{loading && !data ? '—' : data?.stats?.memories_with_evidence || 0}</strong><span>有证据记忆</span></div></div>
    <div class="card stat-card"><Wrench size={20}/><div><strong>{loading && !data ? '—' : pct(data?.stats?.tool_turn_ratio)}</strong><span>工具/过程占比</span></div></div>
  </div>

  <div class="card card-pad" style="margin-top:18px">
    <div class="section-head" style="margin:0 0 12px">
      <div>
        <h2>记忆质量体检</h2>
        <p class="section-subtitle">这是只读风险雷达：帮助发现可能需要处理的记忆，但不会删除、合并或改写任何记忆。</p>
      </div>
      <span class="badge {qualityFlags.pollution_pattern_hits ? 'gold' : 'green'}">系统/工具污染命中 {qualityFlags.pollution_pattern_hits ?? '—'}</span>
    </div>
    <div class="grid cols-4">
      <div class="card stat-card"><AlertTriangle size={18}/><div><strong>{qualityFlags.temporary_task_like_hits ?? '—'}</strong><span>疑似临时任务</span></div></div>
      <div class="card stat-card"><GitBranch size={18}/><div><strong>{qualityFlags.duplicate_title_groups ?? '—'}</strong><span>同会话重复标题组</span></div></div>
      <div class="card stat-card"><AlertTriangle size={18}/><div><strong>{qualityFlags.pollution_pattern_hits ?? '—'}</strong><span>系统/工具污染</span></div></div>
      <div class="card stat-card"><Link2 size={18}/><div><strong>{qualityFlags.low_evidence_hits ?? '—'}</strong><span>证据不足记忆</span></div></div>
    </div>
    <div class="toolbar" style="gap:8px;flex-wrap:wrap;margin-top:12px">
      {#if quality?.review_summary?.ready}
        {#each reviewStatusItems as item}<span class="badge">{qualityStatusLabel(item.review_status)} · {item.c}</span>{/each}
        {#each reviewRetentionItems as item}<span class="badge">{retentionLabel(item.retention_class)} · {item.c}</span>{/each}
      {:else}
        <span class="badge gold">规则处理表尚未迁移</span>
      {/if}
    </div>
    <div class="grid cols-2" style="margin-top:12px">
      <div class="item">
        <div class="item-title">疑似临时任务样本</div>
        {#each temporarySamples.slice(0, 4) as item}
          <button class="title-link" on:click={() => openEvidence(item.id)}>· {item.title}</button>
          <div class="item-meta">命中：{item.matched?.join('、') || '规则关键词'}</div>
        {:else}
          <div class="item-meta">暂无命中</div>
        {/each}
      </div>
      <div class="item">
        <div class="item-title">同会话重复标题候选</div>
        {#each duplicateGroups.slice(0, 4) as group}
          <button class="title-link" on:click={() => group.items?.[0]?.id && openEvidence(group.items[0].id)}>· {group.count} 条：{group.items?.[0]?.title || group.normalized_title}</button>
          <div class="item-meta">仅在同一来源会话内比较，减少泛化标题误报</div>
        {:else}
          <div class="item-meta">暂无命中</div>
        {/each}
      </div>
      <div class="item">
        <div class="item-title">系统/工具污染样本</div>
        {#each pollutionSamples.slice(0, 4) as item}
          <button class="title-link" on:click={() => openEvidence(item.id)}>· {item.title}</button>
        {:else}<div class="item-meta">暂无命中</div>{/each}
      </div>
      <div class="item">
        <div class="item-title">证据不足样本</div>
        {#each lowEvidenceSamples.slice(0, 4) as item}
          <button class="title-link" on:click={() => openEvidence(item.id)}>· {item.title}</button>
        {:else}<div class="item-meta">暂无命中</div>{/each}
      </div>
    </div>
  </div>

  <div class="card card-pad" style="margin-top:18px">
    <div class="toolbar" style="justify-content:space-between;gap:12px;flex-wrap:wrap">
      <div class="toolbar" style="gap:8px;flex-wrap:wrap">
        <button class="btn" class:primary={mode === 'sessions'} on:click={() => switchMode('sessions')}>来源会话</button>
        <button class="btn" class:primary={mode === 'missing_titles'} on:click={() => switchMode('missing_titles')}>缺标题队列</button>
        <div style="position:relative"><Search size={15} style="position:absolute;left:10px;top:10px;color:var(--color-text-secondary)"/><input class="input" style="padding-left:32px;width:320px" bind:value={q} on:keydown={(e)=>{ if(e.key==='Enter') search(); }} placeholder="搜索展示标题、Agent、session id" /></div>
      </div>
      <div class="toolbar" style="gap:8px">
        <select class="input" style="width:170px" bind:value={sort} on:change={changeSort}>
          <option value="updated_desc">按最近更新</option>
          <option value="turns_desc">按对话记录数</option>
          <option value="reviewable_desc">按可审阅正文数</option>
          <option value="coverage_asc">按正文覆盖率（低优先）</option>
        </select>
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
    <div class="item-meta" style="margin-top:12px">当前：{mode === 'missing_titles' ? '缺标题队列' : '来源会话总览'} · 匹配 {total} 条 · 第 {page} / {totalPages} 页</div>
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
      <div class="item-title">来源溯源数据结构尚未完整就绪</div>
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
              <button class="title-link" on:click={() => openDetail(s.id)} aria-label="打开会话详情：{s.display_title || s.agent_session_id || '未命名来源会话'}">{s.display_title || s.agent_session_id || '未命名来源会话'}</button>
              <div class="item-meta">{s.source_agent || 'unknown'} · {short(s.id, 8)} · {fmtTime(s.updated_at || s.imported_at)}</div>
              </div>
            </div>
          </div>
          <div class="toolbar" style="gap:8px;flex-wrap:wrap;margin-top:12px">
            <span class="badge {sourceBadgeClass(s.title_source)}">Agent 原始标题：{sourceLabel(s.title_source)}</span>
            <span class="badge {sourceBadgeClass(s.display_title_source)}">展示标题：{sourceLabel(s.display_title_source)}</span>
            {#if s.is_missing_title}<span class="badge gold">展示标题，不是原始标题</span>{/if}
          </div>
          <div class="item-summary">
            对话记录 {s.turn_count || s.message_count || 0} · 可审阅正文 {s.reviewable_turn_count || 0} · 内部事件 {s.internal_event_count || 0} · 待回填 {s.pending_content_turn_count || 0}
          </div>
          <div class="item-meta">正文状态：{s.pending_content_turn_count > 0 ? '待回填（原始文件可用时会补正文）' : s.reviewable_turn_count > 0 ? '已可审阅' : '没有可审阅正文或原始来源缺失'} · episodes {s.episode_count || 0} · memories {s.memory_count || 0}</div>
          <div class="item-meta">path: {s.source_path || '—'} · hash: {short(s.source_hash, 12)}</div>
        </div>
      {:else}
        <div class="empty card">暂无来源溯源数据。请先到“历史处理”检测并导入本地会话。</div>
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
        <div class="card stat-card"><MessageSquareText size={18}/><div><strong>{detail.turns?.length || 0}</strong><span>当前页对话</span></div></div>
        <div class="card stat-card"><GitBranch size={18}/><div><strong>{detail.episodes?.length || 0}</strong><span>对话片段</span></div></div>
        <div class="card stat-card"><Database size={18}/><div><strong>{detail.memory_units?.length || 0}</strong><span>记忆单元</span></div></div>
        <div class="card stat-card"><Link2 size={18}/><div><strong>{detail.memory_units?.reduce((n,m)=>n + Number(m.evidence_count || 0), 0) || 0}</strong><span>证据关联</span></div></div>
      </div>

      <div class="modal-section">
        <h3>来源会话元信息</h3>
        <div class="raw-box">original_title: {detail.session.original_title || '缺失'}\ndisplay_title: {detail.session.display_title || '—'}\nsource_path: {detail.session.source_path || '—'}\nsource_hash: {detail.session.source_hash || '—'}</div>
      </div>

      {#if Number(detail.pending_content_turn_count || 0) > 0}
        <div class="hint-card" style="margin-top:14px">
          该会话有 {detail.pending_content_turn_count} 条旧记录仅保存了原文长度，正文尚未回填。
          <button class="btn" style="margin-left:10px" disabled={backfillBusy} on:click={backfillCurrentSessionContent}>{backfillBusy ? '正在安全检查…' : '从本地会话文件回填'}</button>
        </div>
      {/if}
      {#if backfillMessage}<div class="item-meta" style="margin-top:10px">{backfillMessage}</div>{/if}

      <div class="detail-tabs" role="tablist">
        <button class:active={detailTab === 'turns'} on:click={() => detailTab = 'turns'}>对话内容审阅 <span>{detail?.turn_counts?.reviewable || 0}</span></button>
        <button class:active={detailTab === 'memories'} on:click={() => detailTab = 'memories'}>记忆单元 <span>{detail.memory_units?.length || 0}</span></button>
      </div>

      {#if detailTab === 'memories'}
      <div class="modal-section">
        <h3>记忆单元</h3>
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
          {:else}<div class="empty card">暂无记忆单元</div>{/each}
        </div>
      </div>
      {:else}
      <div class="modal-section">
        <div class="section-head" style="margin:0 0 12px">
          <div>
            <h3>对话内容审阅</h3>
            <div class="item-meta">当前筛选：{turnFilter === 'reviewable' ? '可审阅对话（有正文的用户/助手内容）' : turnFilter === 'internal' ? '内部过程 / 工具 / 空正文事件' : '全部记录'} · 当前页 {visibleTurns.length} 条 / 筛选命中 {detail?.turn_total || 0} 条 / 会话总计 {detail?.turn_counts?.all || 0} 条。仅在打开此本地会话详情时读取原文。</div>
          </div>
          <div class="turn-filter-controls">
            <select class="input" value={turnFilter} on:change={(e) => changeTurnFilter(e.currentTarget.value)}>
              <option value="reviewable">可审阅对话（{detail?.turn_counts?.reviewable || 0}）</option>
              <option value="all">全部记录（{detail?.turn_counts?.all || 0}）</option>
              <option value="internal">内部过程 / 工具（{detail?.turn_counts?.internal || 0}）</option>
            </select>
            <select class="input" value={turnRole} on:change={(e) => changeTurnRole(e.currentTarget.value)}>
              <option value="all">全部角色</option>
              <option value="user">仅用户（{detail?.turn_role_counts?.user || 0}）</option>
              <option value="assistant">仅 AI（{detail?.turn_role_counts?.assistant || 0}）</option>
            </select>
            <select class="input" value={turnOrder} on:change={(e) => changeTurnOrder(e.currentTarget.value)}>
              <option value="asc">时间从早到晚</option>
              <option value="desc">时间从晚到早</option>
            </select>
            <select class="input" bind:value={turnPreviewLimit} on:change={() => openDetail(detail.session.id, true, 1)}>
              <option value="80">每页 80 条</option>
              <option value="150">每页 150 条</option>
              <option value="300">每页 300 条</option>
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
            <div class="item turn-item" class:user-turn={t.role === 'user'} class:assistant-turn={t.role === 'assistant'} class:muted-turn={t.review_status === 'soft_deleted'}>
              <div class="item-row" style="align-items:flex-start">
                <label style="display:flex;gap:10px;align-items:flex-start;min-width:0;cursor:pointer;flex:1">
                  <input type="checkbox" checked={selectedTurnIds.has(t.id)} on:change={() => toggleTurn(t.id)} aria-label="选择对话内容" />
                  <span style="min-width:0;flex:1">
                    <span class="item-title"><span class="role-badge {t.role === 'user' ? 'user' : t.role === 'assistant' ? 'assistant' : 'other'}">{roleLabel(t.role)}</span>第 {t.turn_index + 1} 轮</span>
                    <span class="item-meta" style="display:block">{fmtTime(t.timestamp) || '无时间戳'} · {t.is_final_answer ? '最终回答' : '普通内容'} · {t.is_tool_call || t.is_tool_result ? '工具过程' : '对话内容'} · {reviewLabel(t.review_status)}</span>
                    {#if String(t.content || '').trim()}
                      <span class="turn-preview" class:expanded={expandedTurnIds.has(t.id)}>{expandedTurnIds.has(t.id) ? t.content : preview(t.content)}</span>
                    {:else if Number(t.content_length || 0) > 0}
                      <span class="turn-preview">（这条旧导入记录目前只有原文长度信息，正文尚未从本地会话文件回填。）</span>
                    {:else}
                      <span class="turn-preview">（该轮原始记录本身没有可显示的正文。）</span>
                    {/if}
                    {#if t.review_note}<span class="item-meta" style="display:block">处理理由：{t.review_note}</span>{/if}
                  </span>
                </label>
                {#if String(t.content || '').length > 420}<button class="btn compact" on:click={() => toggleTurnExpanded(t.id)}>{expandedTurnIds.has(t.id) ? '收起' : '展开'}</button>{/if}
              </div>
            </div>
          {:else}<div class="empty card">当前筛选没有匹配的对话内容。可调整内容类型或角色筛选查看其他记录。</div>{/each}
        </div>
        <div class="turn-pager">
          <button class="btn compact" disabled={detailLoading || turnPage <= 1} on:click={() => gotoTurnPage(turnPage - 1)}>上一页</button>
          <span class="item-meta">第 {turnPage} / {turnTotalPages} 页 · 每页 {detail?.turn_page_size || 80} 条</span>
          <button class="btn compact" disabled={detailLoading || turnPage >= turnTotalPages} on:click={() => gotoTurnPage(turnPage + 1)}>下一页</button>
        </div>
      </div>
      {/if}
    </div>
  </div>
{/if}

{#if evidence}
  <div class="modal-backdrop" role="presentation" on:click={closeEvidenceBackdrop}>
    <div class="detail-modal wide-modal">
      <div class="modal-head">
        <div>
          <div class="toolbar" style="gap:8px;flex-wrap:wrap"><span class="badge green">记忆证据链</span><span class="badge">{evidence.memory.memory_type}</span><span class="badge">{evidence.memory.memory_granularity}</span></div>
          <h2>{evidence.memory.title || evidence.memory.summary || evidence.memory.id}</h2>
          <div class="item-meta">memory {evidence.memory.id} · session {evidence.source_session?.display_title || evidence.source_session?.id || '—'}</div>
        </div>
        <button class="icon-btn" on:click={() => evidence = null}>×</button>
      </div>
      <div class="modal-section"><h3>记忆单元</h3><div class="raw-box">summary: {evidence.memory.summary || '—'}\nspeaker_scope: {evidence.memory.speaker_scope}\nsource_confidence: {pct(evidence.memory.source_confidence)}\nepisode: {evidence.episode?.title || evidence.memory.episode_id || '—'}</div></div>
      <div class="modal-section">
        <h3>来源对话证据（只读元信息）</h3>
        <div class="list">
          {#each evidence.evidence || [] as ev}
            <div class="item">
              <div class="item-title">#{ev.turn_index} · {ev.role} · {ev.evidence_role}</div>
              <div class="item-meta">weight {ev.weight} · len {ev.content_length} · hash {short(ev.content_hash, 12)} · {fmtTime(ev.timestamp)} · {ev.source_event_type}</div>
              <div class="item-summary">source_session: {ev.display_title || ev.source_session_id} · original title: {ev.original_title || '缺失'} · display source: {sourceLabel(ev.display_title_source)}</div>
            </div>
          {:else}<div class="empty card">暂无证据关联</div>{/each}
        </div>
      </div>
    </div>
  </div>
{/if}

{#if detailLoading}
  <div class="toast-card" style="position:fixed;right:24px;bottom:24px;z-index:10000">加载中…</div>
{/if}
