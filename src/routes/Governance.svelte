<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { GitMerge, RefreshCcw, ShieldCheck, Layers3, Inbox, Search } from '@lucide/svelte';

  let overview = null;
  let loading = false;
  let error = '';
  let openGroup = '';
  let activeTab = 'source_groups';
  let page = 1;
  let pageSize = 50;
  let q = '';

  const typeLabels = { FACT:'事实', DECISION:'决策', PREFERENCE:'偏好', EVENT:'事件', REASONING:'推理' };
  const statusLabels = { active:'可引用', expired:'已过期', wrong:'已标错', muted:'已合并/静默', deleted:'已删除' };
  const tabs = [
    { id:'source_groups', label:'同源输入分组', icon:Layers3 },
    { id:'dedupe_records', label:'去重记录', icon:ShieldCheck },
    { id:'memory_links', label:'合并链', icon:GitMerge },
    { id:'ingestion_events', label:'输入事件', icon:Inbox },
    { id:'governed_memories', label:'已治理记忆', icon:RefreshCcw },
  ];

  $: total = overview?.counts?.[activeTab] || 0;
  $: totalPages = Math.max(1, Math.ceil(total / pageSize));

  async function load() {
    loading = true; error = '';
    try { overview = await api.governance({ tab: activeTab, page, page_size: pageSize, q }); }
    catch (e) { error = e.message; }
    finally { loading = false; }
  }

  async function switchTab(tab) {
    activeTab = tab;
    page = 1;
    openGroup = '';
    await load();
  }

  async function search() {
    page = 1;
    openGroup = '';
    await load();
  }

  async function gotoPage(next) {
    page = Math.min(Math.max(1, next), totalPages);
    openGroup = '';
    await load();
  }

  async function mergeMember(group, member) {
    if (!confirm(`确认将「${member.title}」合并到「${group.canonical_title}」吗？\n\n这会把源记忆标记为“不引用”，但不会物理删除。`)) return;
    await api.memoryLink({
      source_memory_id: member.id,
      target_memory_id: group.canonical_id,
      relation_type: 'MERGED_INTO',
      confidence: 1,
      reason: 'manual source group merge from governance page',
    });
    await load();
  }

  function fmtTime(s) { return s ? String(s).slice(0, 19).replace('T', ' ') : ''; }
  function countOf(tab) { return overview?.counts?.[tab] ?? 0; }
  onMount(load);
</script>

<section class="page">
  <div class="page-head-row">
    <div>
      <h1 class="page-title">记忆治理总控</h1>
      <p class="page-subtitle">这里是重复来源、去重事件、合并链和治理状态的审计台。数据支持分页查看，默认每页 50 条；全量记忆检索请到“记忆”页面。</p>
    </div>
    <button class="btn primary" class:loading={loading} disabled={loading} on:click={load}><RefreshCcw size={16}/> 刷新</button>
  </div>

  {#if error}<div class="card card-pad" style="color:var(--color-danger);margin-top:16px">{error}</div>{/if}

  <div class="grid cols-4" style="margin-top:22px">
    <div class="card stat-card"><Layers3 size={20}/><div><strong>{countOf('source_groups')}</strong><span>同源组</span></div></div>
    <div class="card stat-card"><ShieldCheck size={20}/><div><strong>{countOf('dedupe_records')}</strong><span>去重记录</span></div></div>
    <div class="card stat-card"><GitMerge size={20}/><div><strong>{countOf('memory_links')}</strong><span>合并链</span></div></div>
    <div class="card stat-card"><Inbox size={20}/><div><strong>{countOf('ingestion_events')}</strong><span>输入事件</span></div></div>
  </div>

  <div class="card card-pad" style="margin-top:18px">
    <div class="toolbar" style="justify-content:space-between;gap:12px;flex-wrap:wrap">
      <div class="toolbar" style="gap:8px;flex-wrap:wrap">
        {#each tabs as t}
          <button class="btn" class:primary={activeTab === t.id} disabled={loading} on:click={() => switchTab(t.id)}><svelte:component this={t.icon} size={15}/> {t.label} <span class="badge">{countOf(t.id)}</span></button>
        {/each}
      </div>
      <div class="toolbar" style="gap:8px">
        <div style="position:relative"><Search size={15} style="position:absolute;left:10px;top:10px;color:var(--text-muted)"/><input class="input" style="padding-left:32px;width:260px" bind:value={q} on:keydown={(e)=>{ if(e.key==='Enter') search(); }} placeholder="搜索治理记录" /></div>
        <select class="input" style="width:110px" bind:value={pageSize} on:change={search}>
          <option value="50">50 / 页</option>
          <option value="100">100 / 页</option>
          <option value="200">200 / 页</option>
        </select>
        <button class="btn" disabled={loading} on:click={search}>搜索</button>
      </div>
    </div>
    <div class="item-meta" style="margin-top:12px">当前：{tabs.find(t => t.id === activeTab)?.label} · 共 {total} 条 · 第 {page} / {totalPages} 页</div>
  </div>

  {#if loading}
    <div class="list stagger" style="margin-top:14px">{#each Array(4) as _}<div class="card card-pad"><div class="skeleton" style="height:112px"></div></div>{/each}</div>
  {:else if activeTab === 'source_groups'}
    <div class="section-title" style="margin-top:28px">同源输入分组</div>
    <div class="list stagger" style="margin-top:14px">
      {#each overview?.source_groups || [] as group}
        <div class="card card-pad source-group-card">
          <div class="item-row">
            <div>
              <div class="item-title">{group.canonical_title || '未命名同源组'}</div>
              <div class="item-meta">{group.count} 条 · 主记忆 {group.canonical_id?.slice(0,8)} · {fmtTime(group.created_at_min)} ~ {fmtTime(group.created_at_max)}</div>
            </div>
            <button class="btn" on:click={() => openGroup = openGroup === group.source_hash ? '' : group.source_hash}>{openGroup === group.source_hash ? '收起' : '展开'}</button>
          </div>
          <div class="toolbar" style="margin-top:12px;flex-wrap:wrap">
            {#each group.memory_types || [] as t}<span class="badge green">{typeLabels[String(t).toUpperCase()] || t}</span>{/each}
            {#each group.statuses || [] as s}<span class="badge">{statusLabels[s] || s}</span>{/each}
          </div>
          <p class="item-summary" style="margin-top:12px">{group.normalized_preview}</p>
          {#if openGroup === group.source_hash}
            <div class="list" style="margin-top:14px">
              {#each group.members as member}
                <div class="item source-member" class:canonical={member.id === group.canonical_id}>
                  <div>
                    <div class="item-title">{member.title}</div>
                    <div class="item-meta">{member.id.slice(0,8)} · {typeLabels[String(member.memory_type || 'FACT').toUpperCase()] || member.memory_type} · {statusLabels[member.status || 'active']} · 置信度 {Math.round((member.confidence || 0) * 100)}%</div>
                    <div class="item-summary">{member.summary}</div>
                  </div>
                  {#if member.id !== group.canonical_id && member.status !== 'muted'}
                    <button class="btn" on:click={() => mergeMember(group, member)}>合并到主记忆</button>
                  {:else if member.id === group.canonical_id}
                    <span class="badge green">主记忆</span>
                  {:else}
                    <span class="badge">已合并</span>
                  {/if}
                </div>
              {/each}
            </div>
          {/if}
        </div>
      {:else}
        <div class="empty card">暂无同源重复组</div>
      {/each}
    </div>
  {:else if activeTab === 'dedupe_records'}
    <div class="section-title" style="margin-top:28px">去重记录</div>
    <div class="list" style="margin-top:14px">
      {#each overview?.dedupe_records || [] as r}
        <div class="item"><div class="item-title">{r.decision} · {r.reason || r.fact_key || r.action_key || r.normalized_hash?.slice(0,12)}</div><div class="item-meta">{fmtTime(r.created_at)} · {r.source_agent || 'unknown'} · memory {r.memory_id?.slice(0,8) || '无'}</div><div class="item-summary">fact: {r.fact_key || '无'} · action: {r.action_key || '无'} · entity: {r.entity_key || '无'}</div></div>
      {:else}<div class="empty card">暂无去重记录</div>{/each}
    </div>
  {:else if activeTab === 'memory_links'}
    <div class="section-title" style="margin-top:28px">合并链</div>
    <div class="list" style="margin-top:14px">
      {#each overview?.memory_links || [] as l}
        <div class="item"><div class="item-title">{l.relation_type}: {l.source_memory_id?.slice(0,8)} → {l.target_memory_id?.slice(0,8)}</div><div class="item-meta">{fmtTime(l.created_at)} · {l.created_by} · 置信度 {Math.round((l.confidence || 0) * 100)}%</div><div class="item-summary">{l.reason}</div></div>
      {:else}<div class="empty card">暂无合并链</div>{/each}
    </div>
  {:else if activeTab === 'ingestion_events'}
    <div class="section-title" style="margin-top:28px">输入事件</div>
    <div class="list" style="margin-top:14px">
      {#each overview?.ingestion_events || [] as e}
        <div class="item"><div class="item-title">{e.status} · {e.source_type} · {e.source_agent || 'unknown'}</div><div class="item-meta">{fmtTime(e.created_at)} · source {e.source_session_id || '无'} · memory {e.processed_memory_id?.slice(0,8) || '无'}</div><div class="item-summary">{e.reason || e.conversation_hash || e.source_message_hash}</div></div>
      {:else}<div class="empty card">暂无输入事件</div>{/each}
    </div>
  {:else}
    <div class="section-title" style="margin-top:28px">已治理记忆</div>
    <div class="list" style="margin-top:14px">
      {#each overview?.governed_memories || [] as m}
        <div class="item"><div class="item-title">{m.title || '未命名记忆'}</div><div class="item-meta">{m.id?.slice(0,8)} · {typeLabels[String(m.memory_type || 'FACT').toUpperCase()] || m.memory_type} · {statusLabels[m.status] || m.status} · {fmtTime(m.updated_at)}</div><div class="item-summary">{m.summary}</div></div>
      {:else}<div class="empty card">暂无已治理记忆</div>{/each}
    </div>
  {/if}

  <div class="toolbar" style="justify-content:flex-end;margin-top:18px">
    <button class="btn" disabled={loading || page <= 1} on:click={() => gotoPage(page - 1)}>上一页</button>
    <span class="item-meta">第 {page} / {totalPages} 页，每页 {pageSize} 条，共 {total} 条</span>
    <button class="btn" disabled={loading || page >= totalPages} on:click={() => gotoPage(page + 1)}>下一页</button>
  </div>
</section>
