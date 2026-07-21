<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import TodoCard from '../components/TodoCard.svelte';
  let data = null, spaces = [], loading = true, busy = false;
  let form = { title:'', priority:'medium', due_date:'', space_id:'' };
  let selected = null, detailLoading = false, editing = null;

  const priorityLabels = { high:'高优先级', medium:'中优先级', low:'低优先级' };
  const statusLabels = { todo:'待处理', doing:'进行中', done:'已完成', cancelled:'已取消' };
  function formatDue(value) { return value ? value.replace('T', ' ') : '无截止时间'; }
  function dueForInput(value) { return /^\d{4}-\d{2}-\d{2}$/.test(value || '') ? `${value}T09:00` : (value || ''); }

  async function load(){
    loading = true;
    try { [data, spaces] = await Promise.all([api.todos(), api.spaces()]); }
    finally { loading = false; }
  }
  function riskMap() {
    const map = {};
    for (const r of data?.risk?.overdue || []) map[r.id] = 'critical';
    for (const r of data?.risk?.urgent || []) map[r.id] = 'critical';
    for (const r of data?.risk?.warning || []) if (!map[r.id]) map[r.id] = r.level || 'warning';
    return map;
  }
  async function close(e){ const id = e.detail?.id || e; if(!confirm('确认完成这个待办吗？')) return; busy=true; try{ await api.todoAction({action:'close', id}); await load(); if(selected?.todo?.id===id) await openDetail({detail:{id}}); } finally{ busy=false; } }
  async function reopen(e){ const id = e.detail?.id || e; busy=true; try{ await api.todoAction({action:'reopen', id}); await load(); if(selected?.todo?.id===id) await openDetail({detail:{id}}); } finally{ busy=false; } }
  async function create(){ if(!form.title.trim()) return; busy=true; try{ await api.todoAction({action:'create', ...form}); form={title:'', priority:'medium', due_date:'', space_id:''}; await load(); } catch(e) { alert(e.message || '创建失败'); } finally{ busy=false; } }
  async function openDetail(e) { const id = e.detail?.id; if(!id) return; detailLoading=true; selected=null; try{ selected = await api.todo(id); } finally{ detailLoading=false; } }
  function startEdit(e) {
    const t = e.detail?.todo || e;
    editing = { id:t.id, title:t.title || '', description:t.description || '', priority:t.priority || 'medium', status:t.status || 'doing', due_date:dueForInput(t.due_date) };
  }
  async function saveEdit() {
    if(!editing?.title?.trim()) return;
    busy = true;
    try {
      await api.todoAction({ action:'update', ...editing });
      const id = editing.id;
      editing = null;
      await load();
      if(selected?.todo?.id === id) selected = await api.todo(id);
    } catch(e) { alert(e.message || '保存失败'); }
    finally { busy = false; }
  }
  onMount(load);
</script>
<section class="page">
  <h1 class="page-title">待办</h1>
  <p class="page-subtitle">把记忆中的行动项落到地面，并与 Context Space 绑定。</p>
  <div class="card card-pad" style="margin-top:24px">
    <div class="toolbar" style="flex-wrap:wrap">
      <input class="input" bind:value={form.title} placeholder="新待办标题" style="min-width:280px;flex:1" />
      <select class="input" bind:value={form.priority}><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select>
      <input class="input" type="datetime-local" bind:value={form.due_date} title="截止时间，精确到分钟" />
      <select class="input" bind:value={form.space_id}><option value="">不绑定 Space</option>{#each spaces as s}<option value={s.id}>{s.name}</option>{/each}</select>
      <button class="btn primary" class:loading={busy} disabled={busy} on:click={create}>{busy ? '处理中' : '创建'}</button>
    </div>
  </div>
  {#if data?.risk}
    <div class="card card-pad risk-summary" style="margin-top:18px">
      <strong>风险状态</strong>
      <p class="muted">{data.risk.summary}</p>
    </div>
  {/if}
  <div class="two-col" style="margin-top:20px">
    <div>
      <div class="section-head"><h2>进行中</h2></div>
      <div class="list">
        {#if loading}
          {#each Array(4) as _}<div class="card card-pad"><div class="skeleton" style="height:76px"></div></div>{/each}
        {:else}
          {#each data?.todos || [] as t}<TodoCard todo={t} riskLevel={riskMap()[t.id] || ''} {busy} on:open={openDetail} on:edit={startEdit} on:close={close} on:reopen={reopen}/>{:else}<div class="empty card">没有进行中的待办</div>{/each}
        {/if}
      </div>
    </div>
    <div>
      <div class="section-head"><h2>最近完成</h2></div>
      <div class="list">{#each data?.done || [] as t}<TodoCard todo={t} {busy} on:open={openDetail} on:edit={startEdit} on:close={close} on:reopen={reopen}/>{:else}<div class="empty card">暂无已完成待办</div>{/each}</div>
    </div>
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
            <span class="badge green">{priorityLabels[selected.todo.priority] || selected.todo.priority}</span>
            {#if riskMap()[selected.todo.id]}<span class="badge danger-soft">风险待办</span>{/if}
            <h2>{selected.todo.title}</h2>
            <div class="item-meta">{statusLabels[selected.todo.status] || selected.todo.status} · {formatDue(selected.todo.due_date)} · 来源 {selected.todo.source_agent || 'dashboard'}</div>
          </div>
          <button class="icon-btn" on:click={() => selected = null}>×</button>
        </div>
        <div class="modal-section"><h3>描述</h3><div class="raw-box">{selected.todo.description || '暂无描述'}</div></div>
        <div class="toolbar" style="margin-top:18px;flex-wrap:wrap">
          <button class="btn" disabled={busy} on:click={() => startEdit(selected.todo)}>编辑</button>
          {#if selected.todo.status !== 'done'}<button class="btn primary" disabled={busy} on:click={() => close({detail:{id:selected.todo.id}})}>确认完成</button>{:else}<button class="btn" disabled={busy} on:click={() => reopen({detail:{id:selected.todo.id}})}>重开</button>{/if}
        </div>
        <div class="modal-section"><h3>历史记录</h3><div class="list">{#each selected.history || [] as h}<div class="item"><div class="item-title">{statusLabels[h.from_status] || h.from_status || '新建'} → {statusLabels[h.to_status] || h.to_status}</div><div class="item-meta">{h.created_at?.slice(0,19)} · {h.agent || 'unknown'}</div>{#if h.note}<div class="item-summary">{h.note}</div>{/if}</div>{:else}<div class="empty">暂无历史记录</div>{/each}</div></div>
      {/if}
    </div>
  </div>
{/if}

{#if editing}
  <div class="modal-backdrop" role="button" tabindex="0" on:click={() => !busy && (editing = null)} on:keydown={(e)=>e.key==='Escape' && !busy && (editing=null)}>
    <div class="detail-modal" role="dialog" aria-modal="true" tabindex="0" on:click|stopPropagation on:keydown|stopPropagation>
      <div class="modal-head"><div><span class="badge green">编辑待办</span><h2>{editing.title || '未命名待办'}</h2></div><button class="icon-btn" disabled={busy} on:click={() => editing = null}>×</button></div>
      <div class="grid" style="gap:12px">
        <input class="input" bind:value={editing.title} placeholder="标题" />
        <textarea class="input" bind:value={editing.description} placeholder="描述" rows="5"></textarea>
        <div class="toolbar" style="flex-wrap:wrap">
          <select class="input" bind:value={editing.priority}><option value="high">高优先级</option><option value="medium">中优先级</option><option value="low">低优先级</option></select>
          <select class="input" bind:value={editing.status}><option value="todo">待处理</option><option value="doing">进行中</option><option value="done">已完成</option><option value="cancelled">已取消</option></select>
          <input class="input" type="datetime-local" bind:value={editing.due_date} title="截止时间，精确到分钟" />
        </div>
      </div>
      <div class="toolbar" style="justify-content:flex-end;margin-top:18px"><button class="btn" disabled={busy} on:click={() => editing = null}>取消</button><button class="btn primary" class:loading={busy} disabled={busy} on:click={saveEdit}>{busy ? '保存中' : '保存'}</button></div>
    </div>
  </div>
{/if}
