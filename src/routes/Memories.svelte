<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import MemoryCard from '../components/MemoryCard.svelte';
  let q = '', status = 'active', memories = [], loading = false, error = '';
  let page = 1, pageSize = '50', total = 0;
  let selected = null, detailLoading = false, actionBusy = false, toast = null;
  const statusLabels = { active:'可引用', expired:'已过期', wrong:'已标错', muted:'不引用', deleted:'已删除' };
  const typeLabels = { FACT:'事实', DECISION:'决策', PREFERENCE:'偏好', EVENT:'事件', REASONING:'推理' };
  $: totalPages = Math.max(1, Math.ceil(total / Number(pageSize || 50)));

  async function load() {
    loading = true; error='';
    try {
      const limit = Number(pageSize || 50);
      const data = await api.memories({ q, status, limit, offset: (page - 1) * limit, include_total: true });
      memories = data.items || [];
      total = data.total || 0;
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

  onMount(load);
</script>
<section class="page">
  <h1 class="page-title">记忆管理</h1>
  <p class="page-subtitle">搜索、检查、标重要、纠错、过期、静默或软删除具体长期记忆。去重、合并链和输入事件请到“治理审计”。</p>
  <div class="toolbar" style="margin-top:24px;flex-wrap:wrap">
    <input class="input" style="width:min(520px,100%)" bind:value={q} on:keydown={(e)=>e.key==='Enter'&&search()} placeholder="搜索标题、摘要或原文"/>
    <select class="input" bind:value={status} on:change={search}>
      <option value="active">可引用</option><option value="expired">已过期</option><option value="wrong">已标错</option><option value="muted">不引用</option><option value="deleted">已删除</option><option value="all">全部</option>
    </select>
    <select class="input" style="width:110px" bind:value={pageSize} on:change={search}>
      <option value="50">50 / 页</option>
      <option value="100">100 / 页</option>
      <option value="200">200 / 页</option>
    </select>
    <button class="btn primary" class:loading={loading} disabled={loading} on:click={search}>{loading ? '搜索中' : '搜索'}</button>
  </div>
  <div class="item-meta" style="margin-top:10px">共 {total} 条 · 第 {page} / {totalPages} 页 · 每页 {pageSize} 条</div>

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
