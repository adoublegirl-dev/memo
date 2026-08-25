<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import StatCard from '../components/StatCard.svelte';
  import MemoryCard from '../components/MemoryCard.svelte';
  import TodoCard from '../components/TodoCard.svelte';
  import DateTimePicker from '../components/DateTimePicker.svelte';
  import { Database, MessageSquare, Share2, Activity } from '@lucide/svelte';
  let stats = null, tags = [], memories = [], todos = [], todayTodos = [], otherTodos = [], todoData = null;
  let selected = null, detailLoading = false;
  let todoSelected = null, todoDetailLoading = false, editingTodo = null, todoBusy = false;
  const typeLabels = { FACT:'事实', DECISION:'决策', PREFERENCE:'偏好', EVENT:'事件', REASONING:'推理' };
  const statusLabels = { active:'可引用', expired:'已过期', wrong:'已标错', muted:'不引用', deleted:'已删除' };
  const todoPriorityLabels = { high:'高优先级', medium:'中优先级', low:'低优先级' };
  const todoStatusLabels = { todo:'待处理', doing:'进行中', done:'已完成', cancelled:'已取消' };
  function formatDue(value) { return value ? value.replace('T', ' ') : '无截止时间'; }
  function dueForInput(value) { return /^\d{4}-\d{2}-\d{2}$/.test(value || '') ? `${value}T09:00` : (value || ''); }

  async function loadOverview() {
    const [statsData, tagsData, memoriesData, todosData] = await Promise.all([
      api.stats(), api.tags(), api.memories({ limit: 3, sort: 'recent' }), api.todos()
    ]);
    stats = statsData;
    tags = Array.isArray(tagsData) ? tagsData : [];
    memories = Array.isArray(memoriesData) ? memoriesData : [];
    todoData = todosData;
    todos = Array.isArray(todosData) ? todosData : (todosData?.todos || []);
    todayTodos = Array.isArray(todosData?.today) ? todosData.today : [];
    otherTodos = Array.isArray(todosData?.upcoming) ? todosData.upcoming : todos.filter(todo => !todayTodos.some(item => item.id === todo.id));
  }
  onMount(loadOverview);

  function riskMap() {
    const map = {};
    for (const r of todoData?.risk?.overdue || []) map[r.id] = 'critical';
    for (const r of todoData?.risk?.urgent || []) map[r.id] = 'critical';
    for (const r of todoData?.risk?.warning || []) if (!map[r.id]) map[r.id] = r.level || 'warning';
    return map;
  }
  async function openDetail(e) {
    const id = e.detail?.id;
    if (!id) return;
    detailLoading = true; selected = null;
    try { selected = await api.memory(id); }
    finally { detailLoading = false; }
  }
  async function openTodoDetail(e) {
    const id = e.detail?.id;
    if (!id) return;
    todoDetailLoading = true; todoSelected = null;
    try { todoSelected = await api.todo(id); }
    finally { todoDetailLoading = false; }
  }
  function startTodoEdit(e) {
    const t = e.detail?.todo || e;
    editingTodo = { id:t.id, title:t.title || '', description:t.description || '', priority:t.priority || 'medium', status:t.status || 'doing', due_date:dueForInput(t.due_date) };
  }
  async function closeTodo(e) {
    const id = e.detail?.id || e;
    if(!confirm('确认完成这个待办吗？')) return;
    todoBusy = true;
    try { await api.todoAction({action:'close', id}); await loadOverview(); if(todoSelected?.todo?.id===id) todoSelected = await api.todo(id); }
    finally { todoBusy = false; }
  }
  async function reopenTodo(e) {
    const id = e.detail?.id || e;
    todoBusy = true;
    try { await api.todoAction({action:'reopen', id}); await loadOverview(); if(todoSelected?.todo?.id===id) todoSelected = await api.todo(id); }
    finally { todoBusy = false; }
  }
  async function cancelTodo(e) {
    const id = e.detail?.id || e;
    if(!confirm('把这个待办移入“已取消”吗？不会物理删除，可在待办页恢复。')) return;
    todoBusy = true;
    try { await api.todoAction({action:'cancel', id}); todoSelected = null; await loadOverview(); }
    finally { todoBusy = false; }
  }
  async function saveTodoEdit() {
    if(!editingTodo?.title?.trim()) return;
    todoBusy = true;
    try {
      await api.todoAction({action:'update', ...editingTodo});
      const id = editingTodo.id;
      editingTodo = null;
      await loadOverview();
      if(todoSelected?.todo?.id===id) todoSelected = await api.todo(id);
    } catch(e) { alert(e.message || '保存失败'); }
    finally { todoBusy = false; }
  }
</script>

<section class="page">
  <h1 class="page-title">总览</h1>
  <p class="page-subtitle">你的跨 Agent 长期上下文资产，一眼看清当前活跃状态。</p>

  {#if stats}
    <div class="grid stats" style="margin-top:26px">
      <StatCard icon={Database} value={stats.memories} label="记忆" tone="var(--color-gold)" />
      <StatCard icon={MessageSquare} value={stats.sessions} label="会话" />
      <StatCard icon={Share2} value={stats.relations} label="关系" />
      <StatCard icon={Activity} value={stats.vector_index_size} label="向量索引" />
    </div>
  {:else}
    <div class="grid stats" style="margin-top:26px">{#each Array(4) as _}<div class="card card-pad"><div class="skeleton" style="height:70px"></div></div>{/each}</div>
  {/if}

  <div class="section-head"><h2>活跃特征词</h2></div>
  <div class="card card-pad" style="display:flex;gap:8px;flex-wrap:wrap">
    {#each tags.slice(0, 28) as tag}<span class="badge green">{tag.name}</span>{/each}
    {#if !tags.length}<div class="empty">暂无特征词</div>{/if}
  </div>

  <div class="two-col" style="margin-top:18px">
    <div>
      <div class="section-head"><h2>最近记忆</h2></div>
      <div class="list stagger">{#each memories as m}<MemoryCard memory={m} on:open={openDetail}/>{:else}<div class="empty card">暂无记忆</div>{/each}</div>
    </div>
    <div>
      <div class="section-head"><h2>今日待办</h2><span class="item-meta">含逾期未完成</span></div>
      <div class="risk-mini">{todoData?.risk?.summary || '正在检查'}</div>
      <div class="list stagger">{#each todayTodos.slice(0,5) as t}<TodoCard todo={t} riskLevel={riskMap()[t.id] || ''} busy={todoBusy} on:open={openTodoDetail} on:edit={startTodoEdit} on:close={closeTodo} on:cancel={cancelTodo} on:reopen={reopenTodo}/>{:else}<div class="empty card">今天没有到期或逾期待办</div>{/each}</div>
      <div class="section-head" style="margin-top:14px"><h2>其他进行中</h2></div>
      <div class="list stagger">{#each otherTodos.slice(0,3) as t}<TodoCard todo={t} riskLevel={riskMap()[t.id] || ''} busy={todoBusy} on:open={openTodoDetail} on:edit={startTodoEdit} on:close={closeTodo} on:cancel={cancelTodo} on:reopen={reopenTodo}/>{:else}<div class="empty card">暂无其他待办</div>{/each}</div>
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
            <span class="badge green">{typeLabels[String(selected.memory_type || 'FACT').toUpperCase()] || '事实'}</span>
            <h2>{selected.title || '无标题记忆'}</h2>
            <div class="item-meta">{statusLabels[selected.status || 'active']} · 置信度 {Math.round((selected.confidence || 0) * 100)}% · 权重 {selected.user_weight ?? 1}</div>
          </div>
          <button class="icon-btn" on:click={() => selected = null}>×</button>
        </div>
        <div class="modal-section"><h3>摘要</h3><p>{selected.summary_detail || selected.summary || '暂无摘要'}</p></div>
        <div class="modal-section"><h3>{selected.raw_text_source === 'source_turns' ? '原始对话证据' : '原文'}</h3><div class="raw-box">{selected.raw_text || (selected.raw_text_pending_count ? `旧版导入的 ${selected.raw_text_pending_count} 条关联对话正文尚未回填。` : '暂无可显示的原文')}</div></div>
        {#if selected.feature_tags?.length}<div class="modal-section"><h3>标签</h3><div class="toolbar" style="flex-wrap:wrap">{#each selected.feature_tags as tag}<span class="badge green">{tag}</span>{/each}</div></div>{/if}
      {/if}
    </div>
  </div>
{/if}

{#if todoDetailLoading || todoSelected}
  <div class="modal-backdrop" role="button" tabindex="0" on:click={() => !todoDetailLoading && (todoSelected = null)} on:keydown={(e)=>e.key==='Escape' && !todoDetailLoading && (todoSelected=null)}>
    <div class="detail-modal" role="dialog" aria-modal="true" tabindex="0" on:click|stopPropagation on:keydown|stopPropagation>
      {#if todoDetailLoading}
        <div class="skeleton" style="height:220px"></div>
      {:else}
        <div class="modal-head"><div><span class="badge green">{todoPriorityLabels[todoSelected.todo.priority] || todoSelected.todo.priority}</span>{#if riskMap()[todoSelected.todo.id]} <span class="badge danger-soft">风险待办</span>{/if}<h2>{todoSelected.todo.title}</h2><div class="item-meta">{todoStatusLabels[todoSelected.todo.status] || todoSelected.todo.status} · {formatDue(todoSelected.todo.due_date)} · 来源 {todoSelected.todo.source_agent || 'dashboard'}</div></div><button class="icon-btn" on:click={() => todoSelected = null}>×</button></div>
        <div class="modal-section"><h3>描述</h3><div class="raw-box">{todoSelected.todo.description || '暂无描述'}</div></div>
        <div class="toolbar" style="margin-top:18px;flex-wrap:wrap"><button class="btn" disabled={todoBusy} on:click={() => startTodoEdit(todoSelected.todo)}>编辑</button>{#if todoSelected.todo.status === 'todo' || todoSelected.todo.status === 'doing'}<button class="btn primary" disabled={todoBusy} on:click={() => closeTodo({detail:{id:todoSelected.todo.id}})}>确认完成</button><button class="btn danger" disabled={todoBusy} on:click={() => cancelTodo({detail:{id:todoSelected.todo.id}})}>移入已取消</button>{:else}<button class="btn" disabled={todoBusy} on:click={() => reopenTodo({detail:{id:todoSelected.todo.id}})}>恢复为待处理</button>{/if}</div>
        <div class="modal-section"><h3>历史记录</h3><div class="list">{#each todoSelected.history || [] as h}<div class="item"><div class="item-title">{todoStatusLabels[h.from_status] || h.from_status || '新建'} → {todoStatusLabels[h.to_status] || h.to_status}</div><div class="item-meta">{h.created_at?.slice(0,19)} · {h.agent || 'unknown'}</div>{#if h.note}<div class="item-summary">{h.note}</div>{/if}</div>{:else}<div class="empty">暂无历史记录</div>{/each}</div></div>
      {/if}
    </div>
  </div>
{/if}

{#if editingTodo}
  <div class="modal-backdrop" role="button" tabindex="0" on:click={() => !todoBusy && (editingTodo = null)} on:keydown={(e)=>e.key==='Escape' && !todoBusy && (editingTodo=null)}>
    <div class="detail-modal" role="dialog" aria-modal="true" tabindex="0" on:click|stopPropagation on:keydown|stopPropagation>
      <div class="modal-head"><div><span class="badge green">编辑待办</span><h2>{editingTodo.title || '未命名待办'}</h2></div><button class="icon-btn" disabled={todoBusy} on:click={() => editingTodo = null}>×</button></div>
      <div class="grid" style="gap:12px"><input class="input" bind:value={editingTodo.title} placeholder="标题" /><textarea class="input" bind:value={editingTodo.description} placeholder="描述" rows="5"></textarea><div class="toolbar" style="flex-wrap:wrap"><select class="input" bind:value={editingTodo.priority}><option value="high">高优先级</option><option value="medium">中优先级</option><option value="low">低优先级</option></select><select class="input" bind:value={editingTodo.status}><option value="todo">待处理</option><option value="doing">进行中</option><option value="done">已完成</option><option value="cancelled">已取消</option></select><DateTimePicker bind:value={editingTodo.due_date} title="截止时间，精确到分钟" /></div></div>
      <div class="toolbar" style="justify-content:flex-end;margin-top:18px"><button class="btn" disabled={todoBusy} on:click={() => editingTodo = null}>取消</button><button class="btn primary" class:loading={todoBusy} disabled={todoBusy} on:click={saveTodoEdit}>{todoBusy ? '保存中' : '保存'}</button></div>
    </div>
  </div>
{/if}
