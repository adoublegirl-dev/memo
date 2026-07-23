<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { Play, Save, RefreshCcw, FileStack, ShieldCheck, AlertTriangle, CheckCircle2, Clock3 } from '@lucide/svelte';

  const sampleText = `User:\n请修复 Memo Desktop Companion 发布包，确保不包含 data、logs、docs。\n\nAssistant:\n已重新打包并检查发布包，resources/app 下不包含 .env、data、logs、docs。GitHub Release 已发布，普通用户推荐下载 Setup 安装包。`;

  let sourceAgent = 'generic';
  let sourceSessionId = 'dashboard-preview';
  let mode = 'recommended';
  let format = 'auto';
  let text = sampleText;
  let report = null;
  let runs = [];
  let selectedRun = null;
  let loading = false;
  let saving = false;
  let loadingRuns = false;
  let error = '';
  let toast = '';

  $: recommended = report?.recommended || 0;
  $: manual = report?.manual_review || 0;
  $: skipped = report?.skipped || 0;
  $: total = report?.candidate_episodes || 0;

  async function preview() {
    loading = true; error = ''; toast = '';
    try {
      report = await api.episodePreview({ source_agent: sourceAgent, source_session_id: sourceSessionId, mode, format, text });
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function saveRun() {
    if (!report) return;
    saving = true; error = ''; toast = '';
    try {
      const saved = await api.episodeImportRunAction({ action: 'record_preview', report, source_agent: sourceAgent, source_path: 'dashboard://paste', mode });
      toast = `已保存预览审计：${saved.id?.slice(0, 8) || ''}`;
      await loadRuns();
    } catch (e) {
      error = e.message;
    } finally {
      saving = false;
    }
  }

  async function loadRuns() {
    loadingRuns = true;
    error = '';
    try {
      const data = await api.episodeImportRuns({ limit: 20, source_agent: '' });
      runs = data.items || [];
    } catch (e) {
      error = e.message;
    } finally {
      loadingRuns = false;
    }
  }

  async function openRun(id) {
    error = '';
    try {
      selectedRun = await api.episodeImportRun(id);
    } catch (e) {
      error = e.message;
    }
  }

  function statusLabel(status) {
    if (status === 'recommended') return '推荐导入';
    if (status === 'manual_review') return '人工确认';
    return '跳过';
  }

  function statusClass(status) {
    if (status === 'recommended') return 'green';
    if (status === 'manual_review') return 'yellow';
    return 'red';
  }

  function fmtTime(s) { return s ? String(s).slice(0, 19).replace('T', ' ') : ''; }

  onMount(loadRuns);
</script>

<section class="page">
  <div class="page-head-row">
    <div>
      <h1 class="page-title">历史记忆迁移</h1>
      <p class="page-subtitle">把 Agent 历史会话先切成用户意图级 Episode，再生成长期记忆候选。当前只做预览和审计，不会导入聊天记录，也不会写入长期记忆。</p>
    </div>
    <button class="btn" on:click={loadRuns} disabled={loadingRuns}><RefreshCcw size={16}/> 刷新审计</button>
  </div>

  <div class="safety-strip">
    <ShieldCheck size={18}/>
    <div><strong>安全模式：</strong>本页只做 dry-run 预览。点击“保存预览审计”只写入 import_runs 记录，不写 memory_units，不创建 Space，不生成图谱关系。</div>
  </div>

  {#if error}<div class="card card-pad error-box">{error}</div>{/if}
  {#if toast}<div class="card card-pad success-box">{toast}</div>{/if}

  <div class="episode-grid">
    <div class="card card-pad">
      <div class="section-title"><FileStack size={18}/> 会话片段</div>
      <div class="form-grid">
        <label>来源 Agent
          <select class="input" bind:value={sourceAgent}>
            <option value="generic">generic</option>
            <option value="hanaagent">HanaAgent</option>
            <option value="workbuddy">WorkBuddy</option>
            <option value="qoder">Qoder</option>
            <option value="codex">Codex</option>
            <option value="claude">Claude</option>
            <option value="cursor">Cursor</option>
          </select>
        </label>
        <label>解析格式
          <select class="input" bind:value={format}>
            <option value="auto">自动</option>
            <option value="jsonl">JSONL</option>
            <option value="markdown">Markdown / 文本</option>
          </select>
        </label>
        <label>模式
          <select class="input" bind:value={mode}>
            <option value="recommended">推荐模式</option>
            <option value="manual">手动模式</option>
            <option value="comprehensive">全面模式</option>
          </select>
        </label>
        <label>来源会话 ID
          <input class="input" bind:value={sourceSessionId} placeholder="可选" />
        </label>
      </div>
      <textarea class="transcript" bind:value={text} placeholder="粘贴 JSONL、Markdown 或 User/Assistant 文本"></textarea>
      <div class="toolbar" style="justify-content:space-between;gap:10px;flex-wrap:wrap">
        <div class="item-meta">当前 MVP 支持粘贴文本预览；自动扫描本地 Agent 目录将在下一步接入。</div>
        <button class="btn primary" on:click={preview} disabled={loading || !text.trim()}><Play size={16}/> {loading ? '分析中...' : '生成 Episode 预览'}</button>
      </div>
    </div>

    <div class="card card-pad">
      <div class="section-title">预览统计</div>
      {#if report}
        <div class="stats-mini">
          <div><strong>{total}</strong><span>候选 Episode</span></div>
          <div><strong>{recommended}</strong><span>推荐导入</span></div>
          <div><strong>{manual}</strong><span>人工确认</span></div>
          <div><strong>{skipped}</strong><span>跳过</span></div>
        </div>
        <button class="btn" style="margin-top:16px" on:click={saveRun} disabled={saving}><Save size={16}/> {saving ? '保存中...' : '保存预览审计'}</button>
        <div class="item-meta" style="margin-top:10px">保存后可在下方“预览审计记录”里回看，不会导入长期记忆。</div>
      {:else}
        <div class="empty-state">
          <Clock3 size={28}/>
          <p>粘贴一段会话后点击“生成 Episode 预览”。</p>
        </div>
      {/if}
    </div>
  </div>

  {#if report}
    <div class="section-title" style="margin-top:26px">Episode 候选</div>
    <div class="list" style="margin-top:12px">
      {#each report.items || [] as item}
        <div class="card card-pad episode-card">
          <div class="item-row">
            <div>
              <div class="item-title">{item.title}</div>
              <div class="item-meta">{item.agent_name} · score {Math.round((item.score || 0) * 100)}% · {item.memory_type}</div>
            </div>
            <span class="badge" class:green={statusClass(item.status)==='green'} class:yellow={statusClass(item.status)==='yellow'} class:red={statusClass(item.status)==='red'}>{statusLabel(item.status)}</span>
          </div>
          <div class="candidate-body">
            <div><strong>用户意图：</strong>{item.user_intent}</div>
            {#if item.key_facts?.length}<div><strong>关键事实：</strong>{item.key_facts.join('；')}</div>{/if}
            {#if item.final_conclusion}<div><strong>最终结论：</strong>{item.final_conclusion}</div>{/if}
            {#if item.decision_or_result}<div><strong>决策 / 结果：</strong>{item.decision_or_result}</div>{/if}
            {#if item.future_impact}<div><strong>后续影响：</strong>{item.future_impact}</div>{/if}
          </div>
          <div class="toolbar tags" style="margin-top:12px;flex-wrap:wrap">
            {#each item.feature_tags || [] as tag}<span class="badge green">{tag}</span>{/each}
            {#each item.sensitive_hints || [] as hint}<span class="badge red"><AlertTriangle size={12}/> {hint}</span>{/each}
          </div>
          {#if item.skip_reasons?.length}<div class="item-meta" style="margin-top:10px">跳过/确认原因：{item.skip_reasons.join('；')}</div>{/if}
        </div>
      {/each}
    </div>
  {/if}

  <div class="section-title" style="margin-top:28px">预览审计记录</div>
  <div class="list" style="margin-top:12px">
    {#if loadingRuns}
      <div class="card card-pad"><div class="skeleton" style="height:80px"></div></div>
    {:else if runs.length === 0}
      <div class="card card-pad empty-inline">暂无记录。</div>
    {:else}
      {#each runs as run}
        <div class="card card-pad run-card">
          <div class="item-row">
            <div>
              <div class="item-title">{run.source_agent || 'unknown'} · {run.mode}</div>
              <div class="item-meta">{fmtTime(run.created_at)} · sessions {run.scanned_sessions} · turns {run.scanned_turns} · candidates {run.candidate_episodes}</div>
            </div>
            <button class="btn" on:click={() => openRun(run.id)}>查看</button>
          </div>
          <div class="toolbar" style="margin-top:10px;gap:8px">
            <span class="badge green">推荐 {run.summary?.recommended || 0}</span>
            <span class="badge yellow">确认 {run.summary?.manual_review || 0}</span>
            <span class="badge red">跳过 {run.summary?.skipped || 0}</span>
          </div>
        </div>
      {/each}
    {/if}
  </div>

  {#if selectedRun}
    <div class="modal-backdrop" role="button" tabindex="0" on:click={() => selectedRun = null} on:keydown={(e) => { if (e.key === 'Escape' || e.key === 'Enter') selectedRun = null; }}>
      <div class="modal card card-pad" role="dialog" aria-modal="true" tabindex="0" on:click|stopPropagation on:keydown|stopPropagation>
        <div class="item-row">
          <div>
            <div class="item-title">预览审计详情</div>
            <div class="item-meta">{selectedRun.id} · {fmtTime(selectedRun.created_at)}</div>
          </div>
          <button class="btn" on:click={() => selectedRun = null}>关闭</button>
        </div>
        <pre class="json-preview">{JSON.stringify(selectedRun.report, null, 2)}</pre>
      </div>
    </div>
  {/if}
</section>

<style>
  .safety-strip{margin-top:18px;display:flex;gap:10px;align-items:flex-start;padding:14px 16px;border:1px solid rgba(34,197,94,.25);background:rgba(34,197,94,.08);border-radius:18px;color:var(--text)}
  .episode-grid{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(280px,.6fr);gap:18px;margin-top:18px}
  .form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:14px}
  label{display:flex;flex-direction:column;gap:6px;font-size:13px;color:var(--text-muted)}
  .transcript{width:100%;min-height:280px;margin:14px 0;padding:14px;border:1px solid var(--border);border-radius:16px;background:var(--bg-soft);color:var(--text);font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;resize:vertical;box-sizing:border-box}
  .stats-mini{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:14px}
  .stats-mini div{padding:14px;border-radius:16px;background:var(--bg-soft);border:1px solid var(--border)}
  .stats-mini strong{display:block;font-size:24px}.stats-mini span{font-size:12px;color:var(--text-muted)}
  .empty-state{height:220px;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--text-muted);gap:10px;text-align:center}.empty-inline{color:var(--text-muted)}
  .candidate-body{margin-top:12px;display:grid;gap:8px;font-size:14px;line-height:1.65}.candidate-body strong{color:var(--text)}
  .episode-card{border-left:3px solid var(--accent)}.run-card{border-left:3px solid rgba(99,102,241,.5)}
  .badge.yellow{background:rgba(245,158,11,.12);color:#b45309;border-color:rgba(245,158,11,.25)}.badge.red{background:rgba(239,68,68,.1);color:var(--color-danger);border-color:rgba(239,68,68,.22);display:inline-flex;align-items:center;gap:4px}
  .error-box{color:var(--color-danger);margin-top:14px}.success-box{color:#15803d;margin-top:14px}
  .modal-backdrop{position:fixed;inset:0;background:rgba(15,23,42,.38);display:flex;align-items:center;justify-content:center;z-index:20;padding:24px}.modal{width:min(920px,90vw);max-height:84vh;overflow:auto}.json-preview{margin-top:14px;white-space:pre-wrap;background:var(--bg-soft);border:1px solid var(--border);border-radius:14px;padding:14px;font-size:12px;color:var(--text)}
  @media(max-width:900px){.episode-grid{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr}}
</style>
