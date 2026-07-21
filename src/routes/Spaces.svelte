<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import SpaceCard from '../components/SpaceCard.svelte';
  import MemoryCard from '../components/MemoryCard.svelte';
  let spaces = [], selected = null, profile = null, includeArchived = false, queue = [];
  let projectCandidates = [], candidateDetail = null, candidateLoading = false;
  let projectCandidateVisibleLimit = 30;
  let sourceSessionStats = null;
  let selectedCandidateIds = [], useLlmCandidateNaming = false;
  let form = { name: '', type: 'management', description: '' };
  let edit = { name:'', type:'', description:'', goal:'', current_state:'', next_action:'', priority:'medium' };
  let alias = '', loading = true, op = '', notice = '';
  const busy = (name) => op === name;

  async function withOp(name, fn) {
    op = name; notice = '';
    try { return await fn(); }
    catch (e) { alert(e.message || '操作失败'); }
    finally { op = ''; }
  }
  async function load() {
    loading = true;
    try {
      spaces = await api.spaces({ include_archived: includeArchived });
      queue = await api.spaceClassificationQueue({ limit: 30 });
      projectCandidates = await api.spaceCandidates({ limit: 1000 });
      const sourceSessions = await api.sourceSessions({ limit: 1 });
      sourceSessionStats = sourceSessions.stats;
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
  async function refreshQueue() { await withOp('scan', async()=>{ const r = await api.spaceAction({ action:'refresh_classification_queue', limit:120, threshold:0.25 }); queue = await api.spaceClassificationQueue({ limit: 30 }); notice = r.reason || `扫描完成：检查 ${r.scanned || 0} 条，新增 ${r.created || 0} 条候选。`; }); }
  async function acceptCandidate(c) { await withOp(`accept:${c.id}`, async()=>{ await api.spaceAction({ action:'accept_candidate', id:c.id }); await load(); notice='已确认归入。'; }); }
  async function rejectCandidate(c) { await withOp(`reject:${c.id}`, async()=>{ await api.spaceAction({ action:'reject_candidate', id:c.id }); queue = await api.spaceClassificationQueue({ limit: 30 }); notice='已标记为不是这个 Space。'; }); }
  async function newSpaceCandidate(c) { const name = prompt('新 Space 名称', c.suggested_space_name || c.title || '新空间'); if(!name) return; await withOp(`new:${c.id}`, async()=>{ await api.spaceAction({ action:'new_space_candidate', id:c.id, name }); selected=null; await load(); notice='已新建 Space 并绑定记忆。'; }); }

  async function backfillSourceSessions() {
    await withOp('backfill-source-sessions', async()=>{
      const r = await api.spaceCandidateAction({ action:'backfill_source_sessions', limit:200 });
      const t = await api.spaceCandidateAction({ action:'refresh_project_candidate_display_titles', limit:500 });
      const sourceSessions = await api.sourceSessions({ limit:1 });
      sourceSessionStats = sourceSessions.stats;
      projectCandidates = await api.spaceCandidates({ limit:1000 });
      notice = `来源会话索引已更新：本次处理 ${r.created || 0} 个，剩余 ${r.remaining || 0} 个；刷新候选展示名 ${t.updated || 0} 条。此操作只建立来源索引，不改变记忆权重。`;
    });
  }
  async function scanProjectCandidates() {
    await withOp('scan-project-candidates', async()=>{
      const r = await api.spaceCandidateAction({ action:'scan_project_candidates', full_scan:true, min_memories:1, use_llm:useLlmCandidateNaming });
      projectCandidates = await api.spaceCandidates({ limit:1000 });
      projectCandidateVisibleLimit = 30;
      notice = `项目整理全量扫描完成：共检查 ${r.scanned || 0} 个会话，新增 ${r.created || 0} 个候选，更新 ${r.updated || 0} 个。当前待处理候选 ${projectCandidates.length} 个，默认展示前 30 个，可在列表底部继续展开。`;
    });
  }
  async function openCandidate(c) {
    candidateLoading = true; candidateDetail = null;
    try { candidateDetail = await api.spaceCandidate(c.id); }
    finally { candidateLoading = false; }
  }
  async function acceptProjectCandidate(c) {
    if(!confirm(`确认候选「${c.candidate_name}」为新 Space？\n\n这只会建立 Space 绑定和来源索引，不会改变记忆权重、置顶、重要性或原文。`)) return;
    const name = prompt('确认为新 Space，名称为：', c.candidate_name || '新项目');
    if(!name) return;
    await withOp(`accept-project:${c.id}`, async()=>{
      await api.spaceCandidateAction({ action:'accept_project_candidate', id:c.id, name, type:c.candidate_type || 'project', description:c.description || '' });
      candidateDetail = null; selected = null; await load(); notice='候选项目已确认为正式 Space。';
    });
  }
  async function mergeProjectCandidateToSelected(c) {
    if(!selected) { alert('请先在右侧选择要合并到的 Space。'); return; }
    if(!confirm(`把候选「${c.candidate_name}」合并到当前 Space「${selected.name}」？\n这会绑定来源会话、记忆和待办，但不会删除原始数据，也不会改变记忆权重、置顶或重要性。`)) return;
    await withOp(`merge-project:${c.id}`, async()=>{
      await api.spaceCandidateAction({ action:'merge_project_candidate_to_space', id:c.id, space_id:selected.id });
      candidateDetail = null; await load(); await select(selected, false); notice='候选项目已合并到当前 Space。';
    });
  }
  async function ignoreProjectCandidate(c) {
    if(!confirm(`忽略候选「${c.candidate_name}」？它不会创建 Space，也不会绑定数据。`)) return;
    await withOp(`ignore-project:${c.id}`, async()=>{
      await api.spaceCandidateAction({ action:'ignore_project_candidate', id:c.id, note:'用户在项目整理队列中忽略' });
      candidateDetail = null; projectCandidates = await api.spaceCandidates({ limit:1000 }); selectedCandidateIds = selectedCandidateIds.filter(id => id !== c.id); notice='已忽略这个候选项目。';
    });
  }
  function toggleCandidate(id) {
    selectedCandidateIds = selectedCandidateIds.includes(id) ? selectedCandidateIds.filter(x => x !== id) : [...selectedCandidateIds, id];
  }
  async function mergeSelectedCandidates() {
    if(selectedCandidateIds.length < 2) { alert('请至少选择两个候选项目。'); return; }
    const sample = projectCandidates.find(c => c.id === selectedCandidateIds[0]);
    if(!confirm(`将选中的 ${selectedCandidateIds.length} 个候选合并为新 Space？\n\n这只会建立 Space 绑定和来源索引，不会改变任何记忆权重。`)) return;
    const name = prompt('合并为新 Space，名称为：', sample?.candidate_name || '合并项目');
    if(!name) return;
    await withOp('merge-selected-projects', async()=>{
      await api.spaceCandidateAction({ action:'merge_project_candidates', ids:selectedCandidateIds, name, type:'project' });
      selectedCandidateIds = []; candidateDetail = null; selected = null; await load(); notice='已将多个候选合并为一个正式 Space。';
    });
  }
  function pct(v) { return Math.round((v || 0) * 100); }
  function shortId(v) { return (v || '').slice(0, 8); }
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

      <div class="section-head" style="margin-top:22px"><div><h2>项目整理候选</h2><p class="item-meta">基于历史会话自动发现候选项目；系统只提示，确认/合并/忽略都由你手动决定。</p></div><div class="toolbar" style="flex-wrap:wrap;justify-content:flex-end"><label class="item-meta" style="display:flex;gap:6px;align-items:center"><input type="checkbox" bind:checked={useLlmCandidateNaming}/>用摘要轻量优化命名</label><button class="btn" class:loading={busy('backfill-source-sessions')} disabled={!!op} on:click={backfillSourceSessions}>更新来源索引</button><button class="btn" class:loading={busy('merge-selected-projects')} disabled={!!op || selectedCandidateIds.length < 2} on:click={mergeSelectedCandidates}>合并选中 {selectedCandidateIds.length || ''}</button><button class="btn" class:loading={busy('scan-project-candidates')} disabled={!!op} on:click={scanProjectCandidates}>{busy('scan-project-candidates')?'扫描中':'扫描历史会话'}</button></div></div>
      <div class="hint-card" style="margin:10px 0 12px">确认候选只会建立 Space 绑定和来源索引，不会修改记忆权重、置顶、重要性、原文或赫布关系。{#if sourceSessionStats} 来源索引：{sourceSessionStats.total || 0} 个，未映射内部会话 {sourceSessionStats.unmapped_sessions || 0} 个。{/if}</div>
      <div class="list">
        {#each projectCandidates.slice(0, projectCandidateVisibleLimit) as c}
          <div class="item">
            <div class="toolbar" style="justify-content:space-between;align-items:flex-start">
              <label class="item-meta" style="display:flex;gap:8px;align-items:flex-start"><input type="checkbox" checked={selectedCandidateIds.includes(c.id)} on:change={() => toggleCandidate(c.id)} />选择</label>
              <div style="flex:1">
                <div class="item-title">{c.candidate_name}</div>
                <div class="item-meta">置信度 {pct(c.confidence)}% · 来源 {c.source_session_ids?.length || 0} 个会话 / {c.source_memory_ids?.length || 0} 条记忆 / {c.source_todo_ids?.length || 0} 个待办</div>
              </div>
              <span class="badge gold">候选</span>
            </div>
            <p class="muted" style="margin:8px 0 0;white-space:pre-line">{c.reason}</p>
            {#if c.suggested_existing_space_name}<div class="hint-card" style="margin-top:10px">系统建议：可能属于已有 Space「{c.suggested_existing_space_name}」。请先查看来源证据，再手动合并。</div>{/if}
            {#if c.merge_suggestions?.length}
              <div class="item-meta" style="margin-top:8px">可能合并：{c.merge_suggestions.map(s => `${s.name} ${pct(s.similarity)}%`).join('；')}</div>
            {/if}
            <div class="toolbar" style="margin-top:10px;flex-wrap:wrap">
              <button class="btn" disabled={!!op || candidateLoading} on:click={() => openCandidate(c)}>查看来源</button>
              <button class="btn primary" class:loading={busy(`accept-project:${c.id}`)} disabled={!!op} on:click={() => acceptProjectCandidate(c)}>确认为新项目</button>
              <button class="btn danger" class:loading={busy(`ignore-project:${c.id}`)} disabled={!!op} on:click={() => ignoreProjectCandidate(c)}>忽略</button>
            </div>
          </div>
        {:else}
          <div class="empty card">暂无候选项目。点击“扫描历史会话”后，系统会先生成候选，不会自动创建正式 Space。</div>
        {/each}
        {#if projectCandidates.length > projectCandidateVisibleLimit}
          <button class="btn" style="width:100%;justify-content:center" on:click={() => projectCandidateVisibleLimit = Math.min(projectCandidateVisibleLimit + 30, projectCandidates.length)}>查看更多：再显示 30 条（已显示 {projectCandidateVisibleLimit} / {projectCandidates.length}）</button>
        {/if}
      </div>

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

{#if candidateLoading}
  <div class="modal-backdrop"><div class="detail-modal"><div class="skeleton" style="height:240px"></div></div></div>
{/if}

{#if candidateDetail}
  <div class="modal-backdrop" role="button" tabindex="0" on:keydown={(e)=>{ if(e.key==='Escape') candidateDetail=null; }} on:click={(e)=>{ if(e.target===e.currentTarget) candidateDetail=null; }}>
    <div class="detail-modal wide-modal">
      <div class="modal-head">
        <div>
          <span class="badge gold">候选项目 · {pct(candidateDetail.confidence)}%</span>
          <h2>{candidateDetail.candidate_name}</h2>
          <div class="item-meta">来源 {candidateDetail.source_session_ids.length} 个会话 / {candidateDetail.source_memory_ids.length} 条记忆 / {candidateDetail.source_todo_ids.length} 个待办</div>
        </div>
        <button class="icon-btn" disabled={!!op} on:click={() => candidateDetail = null}>×</button>
      </div>
      <div class="modal-section"><h3>为什么推荐</h3><div class="raw-box" style="white-space:pre-line">{candidateDetail.reason}\n\n{candidateDetail.description}</div></div>
      <div class="hint-card">边界说明：确认或合并这个候选，只会绑定来源会话、记忆和待办到 Space；不会改变 memory_units.signal_level / user_weight / pinned，也不会重写记忆原文。</div>
      {#if candidateDetail.suggested_aliases?.length}<div class="modal-section"><h3>建议别名 / 关键词</h3><div style="display:flex;gap:6px;flex-wrap:wrap">{#each candidateDetail.suggested_aliases as a}<span class="badge green">{a}</span>{/each}</div></div>{/if}
      {#if candidateDetail.merge_suggestions?.length}<div class="modal-section"><h3>可能合并对象</h3>{#each candidateDetail.merge_suggestions as s}<div class="hint-card" style="margin-top:8px">{s.name} · {pct(s.similarity)}% · {s.reason}</div>{/each}</div>{/if}
      <div class="modal-section"><h3>来源会话原始证据</h3>
        <div class="list">
          {#each candidateDetail.source_sessions || [] as s}
            <div class="item">
              <div class="item-title">{s.display_title || s.title || `会话 ${shortId(s.id)}`}</div>
              <div class="item-meta">原始会话名：{s.original_title || s.title || '未命名'} · {s.agent_id} · {s.created_at} · {s.memories?.length || 0} 条记忆片段</div>
              {#each s.memories || [] as m}
                <div class="raw-box" style="margin-top:10px">
                  <strong>{m.title || '未命名记忆'}</strong>
                  <p>{m.summary}</p>
                  {#if m.raw_text}<details><summary>展开原始片段</summary><pre>{m.raw_text}</pre></details>{/if}
                </div>
              {/each}
            </div>
          {:else}
            <div class="empty">没有找到来源会话，但仍可查看关联记忆片段。</div>
          {/each}
        </div>
      </div>
      {#if candidateDetail.source_todos?.length}<div class="modal-section"><h3>关联待办</h3>{#each candidateDetail.source_todos as t}<div class="item"><div class="item-title">{t.title}</div><div class="item-meta">{t.priority} · {t.status} · {t.due_date || '无截止时间'}</div><p class="muted">{t.description}</p></div>{/each}</div>{/if}
      <div class="toolbar" style="justify-content:flex-end;margin-top:18px;flex-wrap:wrap">
        <button class="btn" disabled={!!op} on:click={() => candidateDetail = null}>先不处理</button>
        <button class="btn primary" class:loading={busy(`accept-project:${candidateDetail.id}`)} disabled={!!op} on:click={() => acceptProjectCandidate(candidateDetail)}>确认为新项目</button>
        <button class="btn danger" class:loading={busy(`ignore-project:${candidateDetail.id}`)} disabled={!!op} on:click={() => ignoreProjectCandidate(candidateDetail)}>忽略</button>
      </div>
    </div>
  </div>
{/if}
