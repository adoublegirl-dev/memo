<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import SpaceCard from '../components/SpaceCard.svelte';
  import MemoryCard from '../components/MemoryCard.svelte';
  let spaces = [], selected = null, profile = null, includeArchived = false, queue = [];
  let form = { name: '', type: 'management', description: '' };
  let edit = { name:'', type:'', description:'', goal:'', current_state:'', next_action:'', priority:'medium' };
  let alias = '', loading = true, op = '', notice = '';
  const busy = (name) => op === name;

  async function withOp(name, fn) {
    op = name; notice = '';
    try { return await fn(); }
    finally { op = ''; }
  }
  async function load() {
    loading = true;
    try {
      spaces = await api.spaces({ include_archived: includeArchived });
      queue = await api.spaceClassificationQueue({ limit: 30 });
      if (!selected && spaces[0]) await select(spaces[0], false);
    } finally { loading = false; }
  }
  async function select(space, setBusy = true) {
    if (setBusy) op = `select:${space.id}`;
    try {
      selected = space;
      profile = await api.space(space.id);
      edit = { name: profile.space.name || '', type: profile.space.type || 'general', description: profile.space.description || '', goal: profile.space.goal || '', current_state: profile.space.current_state || '', next_action: profile.space.next_action || '', priority: profile.space.priority || 'medium' };
    } finally { if (setBusy) op = ''; }
  }
  async function create() { if (!form.name.trim()) return; await withOp('create', async()=>{ await api.spaceAction({ action:'create', ...form }); form = { name:'', type:'management', description:'' }; selected=null; await load(); notice='已创建 Space。'; }); }
  async function save() { if(!selected) return; await withOp('save', async()=>{ await api.spaceAction({ action:'update', id:selected.id, fields:edit }); await select(selected, false); await load(); notice='已保存。'; }); }
  async function archive() {
    if(!selected) return;
    if(!confirm('归档会把这个 Space 从默认列表里隐藏，但不会删除记忆和待办。之后勾选“显示归档”即可找回并恢复。确认归档吗？')) return;
    const archivedId = selected.id;
    await withOp('archive', async()=>{ await api.spaceAction({ action:'archive', id:archivedId }); includeArchived = true; await load(); const found = spaces.find(s=>s.id===archivedId); if(found) await select(found, false); notice='已归档。系统已自动打开“显示归档”，你可以在右侧点击恢复。'; });
  }
  async function restore() { if(!selected) return; await withOp('restore', async()=>{ await api.spaceAction({ action:'restore', id:selected.id }); await select(selected, false); await load(); notice='已恢复到默认列表。'; }); }
  async function addAlias() { if(!selected || !alias.trim()) return; await withOp('alias', async()=>{ await api.spaceAction({ action:'add_alias', id:selected.id, alias }); alias=''; await select(selected, false); notice='别名已添加。'; }); }
  async function unbind(memoryId) { if(!selected || !confirm('从当前 Space 解绑这条记忆？记忆本身不会删除。')) return; await withOp(`unbind:${memoryId}`, async()=>{ await api.spaceAction({ action:'unbind_memory', space_id:selected.id, memory_id:memoryId }); await select(selected, false); await load(); notice='已解绑记忆。'; }); }
  async function refreshQueue() { await withOp('scan', async()=>{ const r = await api.spaceAction({ action:'refresh_classification_queue', limit:120, threshold:0.25 }); queue = await api.spaceClassificationQueue({ limit: 30 }); notice = `扫描完成：检查 ${r.scanned || 0} 条，新增 ${r.created || 0} 条候选。`; }); }
  async function acceptCandidate(c) { await withOp(`accept:${c.id}`, async()=>{ await api.spaceAction({ action:'accept_candidate', id:c.id }); await load(); notice='已确认归入。'; }); }
  async function rejectCandidate(c) { await withOp(`reject:${c.id}`, async()=>{ await api.spaceAction({ action:'reject_candidate', id:c.id }); queue = await api.spaceClassificationQueue({ limit: 30 }); notice='已标记为不是这个 Space。'; }); }
  async function newSpaceCandidate(c) { const name = prompt('新 Space 名称', c.suggested_space_name || c.title || '新空间'); if(!name) return; await withOp(`new:${c.id}`, async()=>{ await api.spaceAction({ action:'new_space_candidate', id:c.id, name }); selected=null; await load(); notice='已新建 Space 并绑定记忆。'; }); }
  onMount(load);
</script>

<section class="page">
  <h1 class="page-title">上下文空间</h1>
  <p class="page-subtitle">把个人事项、管理项目、产品路线和开发工作装进可检索、可行动的空间。</p>
  {#if notice}<div class="toast-card"><span>{notice}</span><button class="btn" on:click={()=>notice=''}>知道了</button></div>{/if}

  <div class="two-col" style="margin-top:26px">
    <div>
      <div class="card card-pad" style="margin-bottom:16px">
        <div style="display:grid;grid-template-columns:1fr 150px auto;gap:10px">
          <input class="input" bind:value={form.name} placeholder="新空间名称，如 Memo / 某客户项目 / 健身计划" />
          <select class="input" bind:value={form.type}>
            <option value="management">管理项目</option><option value="product">产品项目</option><option value="personal">个人事项</option><option value="client">客户事务</option><option value="dev_project">开发项目</option><option value="writing">内容创作</option><option value="general">通用</option>
          </select>
          <button class="btn primary" class:loading={busy('create')} disabled={!!op} on:click={create}>{busy('create')?'创建中':'创建'}</button>
        </div>
        <input class="input" style="margin-top:10px;width:100%" bind:value={form.description} placeholder="描述这个空间的目标、背景或边界" />
        <label class="item-meta" style="display:flex;gap:8px;margin-top:10px"><input type="checkbox" bind:checked={includeArchived} on:change={load}/>显示归档 <span>（归档只是隐藏/暂停，不删除内容，可随时恢复）</span></label>
      </div>
      {#if loading}
        <div class="grid">{#each Array(3) as _}<div class="card card-pad"><div class="skeleton" style="height:92px"></div></div>{/each}</div>
      {:else}
        <div class="grid stagger">
          {#each spaces as space}<button class="space-select" class:active={selected?.id===space.id} disabled={!!op} on:click={() => select(space)}><SpaceCard {space}/>{#if busy(`select:${space.id}`)}<span class="inline-loading">加载中...</span>{/if}</button>{/each}
        </div>
      {/if}

      <div class="section-head" style="margin-top:22px"><h2>自动归类确认队列</h2><button class="btn" class:loading={busy('scan')} disabled={!!op} on:click={refreshQueue}>{busy('scan')?'扫描中':'扫描近期记忆'}</button></div>
      <div class="list">
        {#each queue as c}
          <div class="item">
            <div class="item-title">{c.title}</div>
            <div class="item-meta">建议归入：{c.suggested_space_name || c.suggested_space_id} · 置信度 {Math.round((c.confidence || 0) * 100)}% · {c.reason}</div>
            <p class="muted" style="margin:8px 0 0">{c.summary}</p>
            <div class="toolbar" style="margin-top:10px">
              <button class="btn primary" class:loading={busy(`accept:${c.id}`)} disabled={!!op} on:click={() => acceptCandidate(c)}>确认归入</button>
              <button class="btn" class:loading={busy(`new:${c.id}`)} disabled={!!op} on:click={() => newSpaceCandidate(c)}>新建 Space</button>
              <button class="btn danger" class:loading={busy(`reject:${c.id}`)} disabled={!!op} on:click={() => rejectCandidate(c)}>不是这个</button>
            </div>
          </div>
        {:else}
          <div class="empty card">暂无待确认归类。点击“扫描近期记忆”生成候选。</div>
        {/each}
      </div>
    </div>

    <aside class="card card-pad" style="position:sticky;top:92px">
      {#if profile}
        <span class="badge gold">{profile.space.status === 'archived' ? '已归档' : profile.space.type}</span>
        <h2 style="margin:12px 0 8px">{profile.space.name}</h2>
        {#if profile.space.status === 'archived'}<div class="hint-card">这个 Space 已归档：默认列表会隐藏它，但内容没有删除。需要继续使用时点击“恢复”。</div>{/if}
        <div class="grid" style="gap:8px;margin:12px 0">
          <input class="input" bind:value={edit.name} placeholder="名称" />
          <input class="input" bind:value={edit.description} placeholder="描述" />
          <input class="input" bind:value={edit.goal} placeholder="目标" />
          <input class="input" bind:value={edit.current_state} placeholder="当前状态" />
          <input class="input" bind:value={edit.next_action} placeholder="下一步动作" />
          <div class="toolbar"><button class="btn primary" class:loading={busy('save')} disabled={!!op} on:click={save}>{busy('save')?'保存中':'保存'}</button>{#if profile.space.status === 'archived'}<button class="btn" class:loading={busy('restore')} disabled={!!op} on:click={restore}>恢复</button>{:else}<button class="btn danger" class:loading={busy('archive')} disabled={!!op} on:click={archive}>归档</button>{/if}</div>
        </div>
        <div class="toolbar" style="margin:12px 0"><input class="input" bind:value={alias} placeholder="新增别名"/><button class="btn" class:loading={busy('alias')} disabled={!!op} on:click={addAlias}>添加别名</button></div>
        <div class="grid stats" style="grid-template-columns:repeat(3,1fr);margin-top:14px">
          <div><div class="stat-value" style="font-size:24px">{profile.status.total_memories}</div><div class="stat-label">记忆</div></div>
          <div><div class="stat-value" style="font-size:24px">{profile.status.active_todos}</div><div class="stat-label">待办</div></div>
          <div><div class="stat-value" style="font-size:24px">{profile.status.total_sessions}</div><div class="stat-label">会话</div></div>
        </div>
        <div class="section-head"><h2>关键特征词</h2></div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">{#each profile.key_feature_tags || [] as t}<span class="badge green">{t.name} · {t.c}</span>{/each}</div>
        <div class="section-head"><h2>最近记忆</h2></div>
        <div class="list">{#each (profile.recent_memories || []).slice(0,4) as m}<div><MemoryCard memory={m}/><button class="btn danger" class:loading={busy(`unbind:${m.id}`)} disabled={!!op} style="margin-top:6px" on:click={() => unbind(m.id)}>解绑</button></div>{:else}<div class="empty">暂无空间记忆</div>{/each}</div>
      {:else}
        <div class="empty">选择一个空间查看简报</div>
      {/if}
    </aside>
  </div>
</section>
