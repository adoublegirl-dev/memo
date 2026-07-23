<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { RefreshCcw, Layers3, ShieldCheck, Save, Search, FileStack, ChevronRight, Eye, AlertTriangle } from '@lucide/svelte';

  let sessions = [];
  let detail = null;
  let runs = [];
  let selectedRun = null;
  let loadingSessions = false;
  let loadingDetail = false;
  let saving = false;
  let error = '';
  let toast = '';
  let minMemories = '2';
  let status = 'active';
  let activeSessionId = '';

  $: preview = detail?.canonical_preview;
  $: keepSignals = preview?.fragment_actions?.filter(x => x.suggested_action === 'keep_as_signal') || [];
  $: keepEvidence = preview?.fragment_actions?.filter(x => x.suggested_action === 'keep_as_evidence') || [];
  $: muteFragments = preview?.fragment_actions?.filter(x => x.suggested_action === 'mute_fragment') || [];

  async function loadSessions() {
    loadingSessions = true; error = ''; toast = '';
    try {
      const data = await api.episodeSessionCandidates({ limit: 80, min_memories: minMemories, status });
      sessions = data.items || [];
      if (!activeSessionId && sessions.length) await openSession(sessions[0].id);
    } catch (e) { error = e.message; }
    finally { loadingSessions = false; }
  }

  async function openSession(id) {
    activeSessionId = id;
    loadingDetail = true; error = ''; toast = '';
    try { detail = await api.episodeSessionCandidate(id); }
    catch (e) { error = e.message; }
    finally { loadingDetail = false; }
  }

  async function saveSessionPreview() {
    if (!detail) return;
    saving = true; error = ''; toast = '';
    try {
      const saved = await api.episodeCanonicalizationAction({ action: 'record_session_preview', session_id: detail.session.id, report: detail, mode: 'session_preview' });
      toast = `已保存会话层整理预览：${saved.id?.slice(0,8) || ''}`;
      await loadRuns();
    } catch (e) { error = e.message; }
    finally { saving = false; }
  }

  async function loadRuns() {
    try {
      const data = await api.episodeCanonicalizationRuns({ limit: 20 });
      runs = data.items || [];
    } catch (e) {}
  }

  async function openRun(id) {
    error = '';
    try { selectedRun = await api.episodeCanonicalizationRun(id); }
    catch (e) { error = e.message; }
  }

  function fmtTime(s) { return s ? String(s).slice(0, 19).replace('T', ' ') : ''; }
  function memoryTypeLabel(t) { return ({ FACT:'事实', DECISION:'决策', PREFERENCE:'偏好', EVENT:'事件', REASONING:'推理' })[String(t || 'FACT').toUpperCase()] || t; }
  function actionLabel(a) {
    return ({ keep_as_signal:'保留为长期信号', keep_as_evidence:'保留为证据', mute_fragment:'建议静默为过程碎片', supersede_by_canonical:'由会话记忆替代' })[a] || a;
  }
  function actionClass(a) {
    if (a === 'keep_as_signal') return 'green';
    if (a === 'keep_as_evidence') return 'yellow';
    return 'red';
  }

  onMount(async () => { await loadSessions(); await loadRuns(); });
</script>

<section class="page">
  <div class="page-head-row">
    <div>
      <h1 class="page-title">会话层记忆整理</h1>
      <p class="page-subtitle">在现有 memory_units 上增加一层会话视角：把同一会话下的碎片归拢，生成会话级 canonical memory 候选，并判断底层碎片应保留为长期信号、证据链，还是静默为过程碎片。</p>
    </div>
    <button class="btn" on:click={loadSessions} disabled={loadingSessions}><RefreshCcw size={16}/> 刷新会话</button>
  </div>

  <div class="safety-strip">
    <ShieldCheck size={18}/>
    <div><strong>安全模式：</strong>当前只做会话级预览。保存预览只写 canonicalization_runs 审计，不会修改 memory_units，不会静默旧记忆，不会创建 canonical memory。</div>
  </div>

  {#if error}<div class="card card-pad error-box">{error}</div>{/if}
  {#if toast}<div class="card card-pad success-box">{toast}</div>{/if}

  <div class="toolbar filters">
    <div style="position:relative"><Search size={15} style="position:absolute;left:10px;top:10px;color:var(--text-muted)"/><input class="input" style="padding-left:32px;width:180px" bind:value={minMemories} placeholder="最少记忆数" /></div>
    <select class="input" style="width:150px" bind:value={status}>
      <option value="active">active 会话</option>
      <option value="completed">completed 会话</option>
      <option value="all">全部状态</option>
    </select>
    <button class="btn" on:click={loadSessions}>筛选</button>
  </div>

  <div class="session-layout">
    <aside class="card session-list">
      <div class="list-head"><Layers3 size={17}/> 会话候选 <span>{sessions.length}</span></div>
      {#if loadingSessions}
        <div class="card-pad"><div class="skeleton" style="height:120px"></div></div>
      {:else if sessions.length === 0}
        <div class="card-pad empty-inline">暂无满足条件的会话。</div>
      {:else}
        {#each sessions as s}
          <button class="session-item" class:active={activeSessionId === s.id} on:click={() => openSession(s.id)}>
            <div>
              <strong>{s.display_title || '未命名会话'}</strong>
              <span>{fmtTime(s.created_at)} · {s.active_memory_count} 条记忆</span>
              <small>{s.value_hint}</small>
            </div>
            <ChevronRight size={16}/>
          </button>
        {/each}
      {/if}
    </aside>

    <main class="session-detail">
      {#if loadingDetail}
        <div class="card card-pad"><div class="skeleton" style="height:360px"></div></div>
      {:else if !detail}
        <div class="card card-pad empty-state"><FileStack size={28}/><p>选择一个会话，查看会话层整理建议。</p></div>
      {:else}
        <div class="card card-pad">
          <div class="item-row">
            <div>
              <div class="item-title">{detail.session.display_title || detail.source_session?.title || detail.session.title || '未命名会话'}</div>
              <div class="item-meta">{detail.session.agent_id} · {fmtTime(detail.session.created_at)} · {detail.memories.length} 条底层记忆</div>
            </div>
            <button class="btn" on:click={saveSessionPreview} disabled={saving}><Save size={16}/> {saving ? '保存中...' : '保存预览审计'}</button>
          </div>
        </div>

        {#if preview}
          <div class="card card-pad canonical-card">
            <div class="item-row">
              <div>
                <div class="section-title">建议生成的会话级 Canonical Memory</div>
                <div class="item-meta">score {Math.round((preview.long_term_value_score || 0) * 100)}% · {memoryTypeLabel(preview.suggested_memory_type)} · 来源碎片 {preview.source_memory_ids?.length || 0} 条</div>
              </div>
              <span class="badge green">预览</span>
            </div>
            <h3>{preview.title}</h3>
            <div class="candidate-body">
              <div><strong>用户意图：</strong>{preview.user_intent}</div>
              {#if preview.key_facts?.length}<div><strong>关键事实：</strong>{preview.key_facts.join('；')}</div>{/if}
              {#if preview.decision_or_result}<div><strong>决策 / 结果：</strong>{preview.decision_or_result}</div>{/if}
              <div><strong>处理过程：</strong>{preview.process_summary}</div>
              <div><strong>后续影响：</strong>{preview.future_impact}</div>
            </div>
            <div class="toolbar" style="margin-top:12px;flex-wrap:wrap">
              {#each preview.feature_tags || [] as tag}<span class="badge green">{tag}</span>{/each}
            </div>
          </div>

          <div class="grid cols-3 fragment-stats">
            <div class="card stat-card"><strong>{keepSignals.length}</strong><span>保留为长期信号</span></div>
            <div class="card stat-card"><strong>{keepEvidence.length}</strong><span>保留为证据链</span></div>
            <div class="card stat-card warn"><strong>{muteFragments.length}</strong><span>建议静默过程碎片</span></div>
          </div>
        {/if}

        <div class="section-title" style="margin-top:22px">底层记忆碎片治理建议</div>
        <div class="list" style="margin-top:12px">
          {#each preview?.fragment_actions || [] as f}
            <div class="card card-pad fragment-card">
              <div class="item-row">
                <div>
                  <div class="item-title">{f.title}</div>
                  <div class="item-meta">{memoryTypeLabel(f.memory_type)} · score {Math.round((f.score || 0) * 100)}%</div>
                </div>
                <span class="badge" class:green={actionClass(f.suggested_action)==='green'} class:yellow={actionClass(f.suggested_action)==='yellow'} class:red={actionClass(f.suggested_action)==='red'}>{actionLabel(f.suggested_action)}</span>
              </div>
              <p class="item-summary">{f.reason}</p>
            </div>
          {/each}
        </div>
      {/if}
    </main>
  </div>

  <div class="section-title" style="margin-top:28px">会话层整理审计</div>
  <div class="list" style="margin-top:12px">
    {#if runs.length === 0}
      <div class="card card-pad empty-inline">暂无 canonicalization 审计。</div>
    {:else}
      {#each runs as run}
        <div class="card card-pad run-card">
          <div class="item-row">
            <div>
              <div class="item-title">{run.canonical_title || run.mode}</div>
              <div class="item-meta">{fmtTime(run.created_at)} · 输入 {run.input_memory_count} · 输出 {run.output_memory_count} · 建议静默 {run.muted_count}</div>
            </div>
            <button class="btn" on:click={() => openRun(run.id)}><Eye size={16}/> 查看</button>
          </div>
        </div>
      {/each}
    {/if}
  </div>

  {#if selectedRun}
    <div class="modal-backdrop" role="button" tabindex="0" on:click={() => selectedRun = null} on:keydown={(e)=>{ if(e.key==='Escape'||e.key==='Enter') selectedRun=null; }}>
      <div class="modal card card-pad" role="dialog" aria-modal="true" tabindex="0" on:click|stopPropagation on:keydown|stopPropagation>
        <div class="item-row"><div><div class="item-title">会话层整理审计详情</div><div class="item-meta">{selectedRun.id}</div></div><button class="btn" on:click={() => selectedRun = null}>关闭</button></div>
        <pre class="json-preview">{JSON.stringify(selectedRun.report, null, 2)}</pre>
      </div>
    </div>
  {/if}
</section>

<style>
  .safety-strip{margin-top:18px;display:flex;gap:10px;align-items:flex-start;padding:14px 16px;border:1px solid rgba(34,197,94,.25);background:rgba(34,197,94,.08);border-radius:18px;color:var(--text)}
  .filters{margin-top:18px;gap:10px;flex-wrap:wrap}.session-layout{display:grid;grid-template-columns:340px minmax(0,1fr);gap:18px;margin-top:18px}.session-list{overflow:hidden}.list-head{display:flex;align-items:center;gap:8px;padding:14px 16px;border-bottom:1px solid var(--border);font-weight:700}.list-head span{margin-left:auto;color:var(--text-muted);font-weight:500}.session-item{width:100%;border:0;border-bottom:1px solid var(--border);background:transparent;color:var(--text);padding:14px 16px;text-align:left;display:flex;align-items:center;gap:10px;cursor:pointer}.session-item:hover,.session-item.active{background:var(--bg-soft)}.session-item div{min-width:0;display:grid;gap:4px}.session-item strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.session-item span,.session-item small{font-size:12px;color:var(--text-muted)}.session-detail{display:grid;gap:14px;align-content:start}.canonical-card{border-left:3px solid var(--accent)}.canonical-card h3{margin:14px 0 8px}.candidate-body{display:grid;gap:8px;font-size:14px;line-height:1.65}.fragment-stats{margin-top:14px}.fragment-stats .stat-card{padding:16px}.fragment-stats .stat-card strong{font-size:24px}.fragment-stats .warn{background:rgba(239,68,68,.06)}.fragment-card{border-left:3px solid rgba(148,163,184,.35)}.badge.yellow{background:rgba(245,158,11,.12);color:#b45309;border-color:rgba(245,158,11,.25)}.badge.red{background:rgba(239,68,68,.1);color:var(--color-danger);border-color:rgba(239,68,68,.22);display:inline-flex;align-items:center;gap:4px}.error-box{color:var(--color-danger);margin-top:14px}.success-box{color:#15803d;margin-top:14px}.empty-state{min-height:260px;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--text-muted);gap:10px;text-align:center}.empty-inline{color:var(--text-muted)}.modal-backdrop{position:fixed;inset:0;background:rgba(15,23,42,.38);display:flex;align-items:center;justify-content:center;z-index:20;padding:24px}.modal{width:min(980px,90vw);max-height:84vh;overflow:auto}.json-preview{margin-top:14px;white-space:pre-wrap;background:var(--bg-soft);border:1px solid var(--border);border-radius:14px;padding:14px;font-size:12px;color:var(--text)}@media(max-width:980px){.session-layout{grid-template-columns:1fr}.session-list{max-height:420px;overflow:auto}}
</style>
