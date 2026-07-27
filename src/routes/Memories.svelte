<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import MemoryCard from '../components/MemoryCard.svelte';
  let q = '', status = 'active', memories = [], loading = false, error = '';
  let sourceSessionId = '', sourceSessions = [];
  let page = 1, pageSize = '50', total = 0, breakdown = null;
  let selected = null, detailLoading = false, actionBusy = false, sessionReviewBusy = false, toast = null;
  const statusLabels = { active:'可引用', expired:'已过期', wrong:'已标错', muted:'不引用', deleted:'已删除' };
  const sessionReviewLabels = { new:'未处理', rule_processed:'规则已处理', needs_review:'需复核', needs_llm:'需 LLM', in_review:'处理中', done:'已完成', postponed:'暂缓', has_issue:'有问题' };
  const typeLabels = { FACT:'事实', DECISION:'决策', PREFERENCE:'偏好', EVENT:'事件', REASONING:'推理' };
  $: totalPages = Math.max(1, Math.ceil(total / Number(pageSize || 50)));
  $: selectedSourceSession = sourceSessions.find(s => s.id === sourceSessionId);

  async function load() {
    loading = true; error='';
    try {
      const limit = Number(pageSize || 50);
      const data = await api.memories({ q, status, source_session_id: sourceSessionId, limit, offset: (page - 1) * limit, include_total: true });
      memories = data.items || [];
      total = data.total || 0;
      breakdown = data.breakdown || null;
    }
    catch(e) { error = e.message; }
    finally { loading = false; }
  }

  async function search() { page = 1; await load(); }
  async function gotoPage(next) { page = Math.min(Math.max(1, next), totalPages); await load(); }

  async function openDetail(e) {
    const id = e.detail?.id;
    if (!id) return;
    detailLoading = true;
    selected = null;
    try { selected = await api.memory(id); }
    finally { detailLoading = false; }
  }

  function needsConfirm(action) { return ['mark_wrong','mark_expired','mute','delete','lower'].includes(action); }
  function actionLabel(action) {
    return ({ mark_wrong:'标为错误', mark_expired:'标为过期', mute:'设为不再引用', delete:'软删除', lower:'降低引用权重' }[action] || action);
  }
  function confirmAction(action) {
    if (!needsConfirm(action)) return true;
    const msg = {
      mark_wrong:'确认把这条记忆标为“错误”吗？确认后它默认不会再参与回答。你之后可以在“错误”筛选里恢复。',
      mark_expired:'确认把这条记忆标为“过期”吗？它仍可作为低权重参考，你之后可以恢复。',
      mute:'确认设为“不再引用”吗？它不会删除，但默认不再参与回答，你之后可以恢复。',
      delete:'确认软删除这条记忆吗？它不会从数据库物理删除，可在“软删除”筛选里恢复。',
      lower:'确认降低这条记忆的引用权重吗？以后它会更少被参考。'
    }[action];
    return confirm(msg);
  }

  async function govern(e) {
    const { id, action } = e.detail;
    if (!confirmAction(action)) return;
    actionBusy = true;
    try {
      if (action === 'boost') {
        await api.memoryAction({ id, action:'update', user_weight:1.6, note:'用户要求以后多参考' });
      } else if (action === 'lower') {
        await api.memoryAction({ id, action:'update', user_weight:0.45, note:'用户要求以后少参考' });
      } else if (action === 'note') {
        const user_note = prompt('给这条记忆加一条备注', '') || '';
        if (!user_note.trim()) return;
        await api.memoryAction({ id, action:'update', user_note, note:'用户备注' });
      } else {
        const note = ['mark_wrong','mark_expired','mute','delete'].includes(action) ? prompt('可选：记录原因/备注', '') || '' : '';
        await api.memoryAction({ id, action, note });
      }
      if (needsConfirm(action)) {
        toast = { id, text:`已${actionLabel(action)}。如果是误操作，可以点这里恢复。` };
        setTimeout(() => { if (toast?.id === id) toast = null; }, 7000);
      }
      await load();
      if (selected?.id === id) selected = await api.memory(id);
    } finally { actionBusy = false; }
  }

  async function restore(id) {
    actionBusy = true;
    try { await api.memoryAction({ id, action:'restore', note:'用户撤回治理操作' }); toast = null; await load(); if (selected?.id === id) selected = await api.memory(id); }
    finally { actionBusy = false; }
  }

  async function loadSourceSessions() {
    try {
      const data = await api.sourceAware({ mode: 'sessions', page: 1, page_size: 100 });
      sourceSessions = data.sessions || [];
    } catch (e) {
      sourceSessions = [];
    }
  }

  async function clearSourceSession() { sourceSessionId = ''; page = 1; await load(); }
  async function setSessionReviewStatus(review_status) {
    if (!selectedSourceSession) return;
    const note = review_status === 'postponed' || review_status === 'has_issue' ? (prompt('可选：记录这个会话的处理备注', selectedSourceSession.session_review_note || '') || '') : (selectedSourceSession.session_review_note || '');
    sessionReviewBusy = true;
    try {
      await api.sourceSessionReviewAction({ source_session_id: selectedSourceSession.id, review_status, note });
      await loadSourceSessions();
    } finally { sessionReviewBusy = false; }
  }

  onMount(async () => { await Promise.all([loadSourceSessions(), load()]); });
</script>
<section class="page">
  <h1 class="page-title">记忆管理</h1>
  <p class="page-subtitle">搜索、检查、标重要、纠错、过期、静默或软删除具体长期记忆。去重、合并链和输入事件请到“治理审计”。</p>
  <div class="grid cols-4" style="margin-top:22px">
    <div class="card stat-card"><div><strong>{breakdown?.library_total ?? '—'}</strong><span>记忆库总量</span></div></div>
    <div class="card stat-card"><div><strong>{breakdown?.active_available ?? '—'}</strong><span>可引用且未替代</span></div></div>
    <div class="card stat-card"><div><strong>{breakdown?.muted_available ?? '—'}</strong><span>不引用但保留</span></div></div>
    <div class="card stat-card"><div><strong>{breakdown?.superseded ?? '—'}</strong><span>已被替代</span></div></div>
  </div>
  <div class="hint-card" style="margin-top:12px">总览里的“记忆”是全库总量；本页默认展示“可引用且未被替代”的记忆。因此当前筛选 {total} 条，可能小于记忆库总量。</div>
  <div class="card card-pad" style="margin-top:18px">
    <div class="toolbar" style="justify-content:space-between;gap:12px;flex-wrap:wrap">
      <div class="toolbar" style="gap:8px;flex-wrap:wrap">
        <input class="input" style="width:min(520px,100%)" bind:value={q} on:keydown={(e)=>e.key==='Enter'&&search()} placeholder="搜索标题、摘要或原文"/>
        <select class="input" bind:value={status} on:change={search}>
          <option value="active">可引用</option><option value="expired">已过期</option><option value="wrong">已标错</option><option value="muted">不引用</option><option value="deleted">已删除</option><option value="all">全部</option>
        </select>
        <select class="input" style="width:min(420px,100%)" bind:value={sourceSessionId} on:change={search}>
          <option value="">全部来源会话</option>
          {#each sourceSessions as s}
            <option value={s.id}>{s.source_agent} · {s.display_title || s.agent_session_id || s.id} · {s.memory_count || 0} 条</option>
          {/each}
        </select>
      </div>
      <div class="toolbar" style="gap:8px">
        <select class="input" style="width:110px" bind:value={pageSize} on:change={search}>
          <option value="50">50 / 页</option>
          <option value="100">100 / 页</option>
          <option value="200">200 / 页</option>
        </select>
        <button class="btn primary" class:loading={loading} disabled={loading} on:click={search}>{loading ? '搜索中' : '搜索'}</button>
      </div>
    </div>
    <div class="item-meta" style="margin-top:12px">当前筛选共 {total} 条 · 第 {page} / {totalPages} 页 · 每页 {pageSize} 条</div>
    {#if selectedSourceSession}
      <div class="hint-card" style="margin-top:12px">
        <div><strong>当前按来源会话筛选：</strong>{selectedSourceSession.display_title || selectedSourceSession.agent_session_id}</div>
        <div class="item-meta" style="margin-top:6px">
          {selectedSourceSession.source_agent} · memories {selectedSourceSession.memory_count || 0} · 已规则处理 {selectedSourceSession.quality_reviewed_count || 0} · 长期 {selectedSourceSession.long_term_count || 0} · 临时 {selectedSourceSession.temporary_task_count || 0} · 噪声 {selectedSourceSession.noise_count || 0} · 需LLM {selectedSourceSession.needs_llm_count || 0}
        </div>
        <div class="toolbar" style="gap:8px;flex-wrap:wrap;margin-top:10px">
          <span class="badge green">状态：{sessionReviewLabels[selectedSourceSession.effective_review_status] || selectedSourceSession.effective_review_status || '未处理'}</span>
          {#if selectedSourceSession.session_review_note}<span class="badge">备注：{selectedSourceSession.session_review_note}</span>{/if}
          <button class="btn" disabled={sessionReviewBusy} on:click={() => setSessionReviewStatus('in_review')}>标记处理中</button>
          <button class="btn" disabled={sessionReviewBusy} on:click={() => setSessionReviewStatus('done')}>标记已完成</button>
          <button class="btn" disabled={sessionReviewBusy} on:click={() => setSessionReviewStatus('postponed')}>暂缓</button>
          <button class="btn" disabled={sessionReviewBusy} on:click={() => setSessionReviewStatus('needs_llm')}>需 LLM</button>
          <button class="btn" on:click={clearSourceSession}>清除会话筛选</button>
        </div>
      </div>
    {/if}
  </div>

  {#if toast}
    <div class="toast-card">
      <span>{toast.text}</span>
      <button class="btn" disabled={actionBusy} on:click={() => restore(toast.id)}>撤回</button>
    </div>
  {/if}
  {#if error}<div class="card card-pad" style="margin-top:12px;color:var(--color-danger)">{error}</div>{/if}
  <div class="list stagger" style="margin-top:18px">
    {#if loading}
      {#each Array(4) as _}<div class="card card-pad"><div class="skeleton" style="height:96px"></div></div>{/each}
    {:else}
      {#each memories as m}
        <MemoryCard memory={m} actionable busy={actionBusy} on:govern={govern} on:open={openDetail}/>
      {:else}
        <div class="empty card">暂无匹配记忆</div>
      {/each}
    {/if}
  </div>
  <div class="toolbar" style="justify-content:flex-end;margin-top:18px">
    <button class="btn" disabled={loading || page <= 1} on:click={() => gotoPage(page - 1)}>上一页</button>
    <span class="item-meta">第 {page} / {totalPages} 页，每页 {pageSize} 条，共 {total} 条</span>
    <button class="btn" disabled={loading || page >= totalPages} on:click={() => gotoPage(page + 1)}>下一页</button>
  </div>
</section>

{#if detailLoading || selected}
  <div class="modal-backdrop" role="button" tabindex="0" on:click={() => !detailLoading && (selected = null)} on:keydown={(e)=>e.key==='Escape' && !detailLoading && (selected=null)}>
    <div class="detail-modal" role="dialog" aria-modal="true" tabindex="0" on:click|stopPropagation on:keydown|stopPropagation>
      {#if detailLoading}
        <div class="skeleton" style="height:220px"></div>
      {:else}
        <div class="modal-head">
          <div>
            <span class="badge green">{typeLabels[String(selected.memory_type || 'FACT').toUpperCase()] || '事实'}</span>
            <h2>{selected.title || '无标题记忆'}</h2>
            <div class="item-meta">{statusLabels[selected.status || 'active']} · 置信度 {Math.round((selected.confidence || 0) * 100)}% · 权重 {selected.user_weight ?? 1}</div>
            {#if selected.source_session}
              <div class="item-meta">来源会话：{selected.source_session.display_title || selected.source_session.id} · {selected.source_session.source_agent}</div>
            {/if}
          </div>
          <button class="icon-btn" on:click={() => selected = null}>×</button>
        </div>
        <div class="modal-section">
          <h3>摘要</h3>
          <p>{selected.summary_detail || selected.summary || '暂无摘要'}</p>
        </div>
        <div class="modal-section">
          <h3>原文</h3>
          <div class="raw-box">{selected.raw_text || '暂无原文'}</div>
        </div>
        {#if selected.feature_tags?.length}
          <div class="modal-section"><h3>标签</h3><div class="toolbar" style="flex-wrap:wrap">{#each selected.feature_tags as tag}<span class="badge green">{tag}</span>{/each}</div></div>
        {/if}
        <div class="modal-section">
          <h3>治理记录</h3>
          <div class="list">
            {#each selected.audit || [] as a}<div class="item"><div class="item-title">{a.action}</div><div class="item-meta">{a.created_at?.slice(0,19)} · {a.actor}</div><div class="item-summary">{a.old_value} → {a.new_value} {a.note ? `· ${a.note}` : ''}</div></div>{:else}<div class="empty">暂无治理记录</div>{/each}
          </div>
        </div>
      {/if}
    </div>
  </div>
{/if}
