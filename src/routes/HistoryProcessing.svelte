<script>
  import { onMount, onDestroy } from 'svelte';
  import { api } from '../lib/api.js';

  let state = null, loading = false, error = '';
  let selected = new Set();
  let pollTimer = null;
  let model = { provider: 'openai-compatible', base_url: '', api_key: '', model: '', concurrency: 1, batch_size: 20 };
  const stepLabels = {
    detect: '检测历史源',
    source_import: '导入原始会话/轮次',
    memory_extract: '保守抽取记忆',
    quality_rules: '规则质量处理',
    llm_enhance: 'LLM 增强（最后一步）',
    done: '完成',
  };
  const statusLabels = { draft:'草稿', ready:'待继续', running:'运行中', paused:'已暂停', failed:'失败', done:'完成' };
  const providerOptions = [
    { id: 'openai-compatible', label: 'OpenAI 兼容', hint: 'DeepSeek / OpenRouter / 硅基流动 / 智谱等' },
    { id: 'anthropic-compatible', label: 'Anthropic 兼容', hint: 'Claude 官方 API' },
    { id: 'gemini-compatible', label: 'Gemini 兼容', hint: 'Google Gemini API' },
    { id: 'ollama', label: 'Ollama / 本地模型', hint: '本机或局域网 Ollama' },
  ];

  $: job = state?.job || {};
  $: progress = state?.job_progress || {};
  $: detectAgents = job.detect_report?.agents || [];
  $: selectedSources = Array.from(selected);
  $: isRunning = job.status === 'running';
  $: llmBlocked = job.current_step === 'llm_enhance' && progress.blocking_reason;
  $: llmProgress = job.progress?.llm_enhance || {};
  $: scanProgress = job.progress?.scan || {};
  $: noNewHistory = scanProgress.status === 'up_to_date';
  $: canContinue = state?.schema_ready && !loading && !isRunning && job.status !== 'done' && !noNewHistory;

  function applyModelFromState(nextState) {
    const saved = nextState?.job?.model_config;
    if (!saved || Object.keys(saved).length === 0) return;
    model = { ...model, ...saved, api_key: saved.api_key || model.api_key || '' };
  }

  async function load({ silent = false } = {}) {
    try {
      const next = await api.historyProcessing();
      state = next;
      const existing = next?.job?.selected_sources || [];
      selected = new Set(existing);
      applyModelFromState(next);
      if (!silent) error = '';
    } catch (e) {
      if (!silent) error = e.message;
    }
  }

  async function act(action, extra = {}) {
    loading = true; error = '';
    try {
      state = await api.historyProcessingAction({ action, selected_sources: selectedSources, model_config: model, ...extra });
      const existing = state?.job?.selected_sources || selectedSources;
      selected = new Set(existing);
      applyModelFromState(state);
    } catch (e) {
      error = e.message;
      await load({ silent: true });
    }
    finally { loading = false; }
  }

  function toggleSource(id) {
    selected = new Set(selected);
    selected.has(id) ? selected.delete(id) : selected.add(id);
  }
  function sourceLabel(id) {
    return state?.supported_sources?.find(s => s.id === id)?.label || id;
  }
  function stepIndex(step) { return (state?.steps || []).indexOf(step); }
  function providerHint(id) { return providerOptions.find(p => p.id === id)?.hint || ''; }
  function humanError(message) {
    if (!message) return '';
    if (message.includes('already running')) return '当前阶段正在处理中。为避免数据库锁定，暂时不能重复启动，请等待进度刷新。';
    return message;
  }

  onMount(() => {
    load();
    pollTimer = setInterval(() => {
      if (state?.job?.status === 'running') load({ silent: true });
    }, 2500);
  });
  onDestroy(() => { if (pollTimer) clearInterval(pollTimer); });
</script>

<section class="page">
  <h1 class="page-title">历史会话处理</h1>
  <p class="page-subtitle">安装或升级后，按需处理本机 HanaAgent / WorkBuddy / Codex 的历史会话。旧 memo.db 不连接、不覆盖，只在当前新库上增量导入。</p>

  {#if error}<div class="card card-pad" style="color:var(--color-danger);margin-top:12px">{humanError(error)}</div>{/if}
  {#if !state?.schema_ready}
    <div class="hint-card" style="margin-top:12px">历史处理表尚未就绪，请重启 Memo 让 migration 执行完成。</div>
  {/if}

  <div class="card card-pad progress-card" style="margin-top:18px">
    <div class="progress-head">
      <div>
        <h2>处理进度</h2>
        <div class="item-meta">
          当前：{progress.current_label || stepLabels[job.current_step] || '检测历史源'} · {statusLabels[job.status] || '未开始'}
          {#if isRunning} · 后台处理中，页面每 2.5 秒自动刷新{/if}
        </div>
      </div>
      <div class="progress-percent">{progress.percent ?? 0}%</div>
    </div>
    <div class="progress-track"><div class="progress-fill" style={`width:${progress.percent || 0}%`}></div></div>
    <div class="step-row compact">
      {#each state?.steps || [] as step, i}
        <div class="step-pill" class:active={job.current_step === step} class:done={stepIndex(job.current_step) > i || job.current_step === 'done'}>{i + 1}. {stepLabels[step]}</div>
      {/each}
    </div>
    {#if noNewHistory}
      <div class="hint-card" style="margin-top:12px;color:var(--color-success)">
        没有发现新的历史会话，当前已是最新。下次有新会话后再点“检测历史”。
      </div>
    {/if}
    {#if scanProgress.status === 'has_pending'}
      <div class="hint-card" style="margin-top:12px">
        检测到 {scanProgress.total_pending || 0} 个新的或已变化的历史会话，可以继续导入。
      </div>
    {/if}
    {#if job.current_step === 'llm_enhance' && llmProgress.total}
      <div class="hint-card" style="margin-top:12px">
        LLM 子进度：{llmProgress.processed || 0}/{llmProgress.total}；每批 {llmProgress.batch_size || model.batch_size || 20} 条自动续跑。
        {#if llmProgress.failed}失败/跳过：{llmProgress.failed} 条。{/if}
        {#if llmProgress.pause_requested} 已请求暂停，当前批次完成后停止。{/if}
      </div>
    {/if}
    {#if progress.blocking_reason}<div class="hint-card" style="margin-top:12px;color:var(--color-warning)">{progress.blocking_reason}</div>{/if}
    <div class="hint-card" style="margin-top:12px">{state?.llm_note}</div>
  </div>

  <div class="grid cols-4" style="margin-top:18px">
    <div class="card stat-card"><div><strong>{statusLabels[job.status] || '未开始'}</strong><span>任务状态</span></div></div>
    <div class="card stat-card"><div><strong>{stepLabels[job.current_step] || '检测历史源'}</strong><span>当前阶段</span></div></div>
    <div class="card stat-card"><div><strong>{selectedSources.length}</strong><span>已选来源</span></div></div>
    <div class="card stat-card"><div><strong>{job.updated_at ? job.updated_at.slice(5,16).replace('T',' ') : '—'}</strong><span>最近更新</span></div></div>
  </div>

  <div class="card card-pad" style="margin-top:18px">
    <div class="toolbar" style="justify-content:space-between;gap:12px;flex-wrap:wrap">
      <div>
        <h2>1. 检测历史源</h2>
        <div class="item-meta">只读扫描本机 Agent 历史位置，不写入记忆库。</div>
      </div>
      <button class="btn primary" disabled={loading || isRunning} on:click={() => act('scan')}>{loading ? '执行中' : '检测历史'}</button>
    </div>
    <div class="source-grid" style="margin-top:12px">
      {#each detectAgents as a}
        <div class="source-card">
          <strong>{a.agent}</strong>
          <div class="item-meta">detected: {a.detected ? 'yes' : 'no'} · sessions: {a.session_count || 0}</div>
          <div class="item-meta">titles: {a.title_count || 0} / missing {a.missing_title_count || 0}</div>
        </div>
      {:else}
        <div class="empty">尚未检测。点击“检测历史”。</div>
      {/each}
    </div>
  </div>

  <div class="card card-pad" style="margin-top:18px">
    <h2>2. 选择要处理的来源</h2>
    <div class="toolbar" style="gap:8px;flex-wrap:wrap;margin-top:10px">
      {#each state?.supported_sources || [] as s}
        <button class="btn" class:primary={selected.has(s.id)} disabled={isRunning} on:click={() => toggleSource(s.id)}>{selected.has(s.id) ? '✓ ' : ''}{s.label}</button>
      {/each}
    </div>
  </div>

  <div class="card card-pad" style="margin-top:18px">
    <h2>3. 模型配置（LLM 最后一步使用）</h2>
    <div class="grid cols-4" style="margin-top:10px">
      <select class="input" bind:value={model.provider} disabled={isRunning}>
        {#each providerOptions as p}<option value={p.id}>{p.label}</option>{/each}
      </select>
      <input class="input" bind:value={model.base_url} disabled={isRunning} placeholder="Base URL，如 https://api.deepseek.com" />
      <input class="input" bind:value={model.model} disabled={isRunning} placeholder="Model，如 deepseek-chat" />
      <input class="input" bind:value={model.api_key} disabled={isRunning} placeholder="API Key（只保存本机，页面脱敏显示）" />
    </div>
    <div class="grid cols-4" style="margin-top:10px">
      <input class="input" type="number" min="1" max="8" bind:value={model.concurrency} disabled={isRunning} placeholder="并发数" />
      <input class="input" type="number" min="1" max="100" bind:value={model.batch_size} disabled={isRunning} placeholder="每批处理条数" />
      <div class="item-meta field-help">接口类型：{providerHint(model.provider)}</div>
      <div class="item-meta field-help">每批处理条数默认 20；并发默认 1，最稳。</div>
    </div>
    <div class="toolbar" style="margin-top:12px">
      <button class="btn" disabled={loading || isRunning} on:click={() => act('save_config')}>保存配置</button>
    </div>
  </div>

  <div class="card card-pad" style="margin-top:18px">
    <h2>4. 执行 / 继续</h2>
    <p class="item-meta">点击一次会启动当前阶段。进入 LLM 增强后，系统会按“每批处理条数”在后台自动续跑到完成；暂停会在当前批次结束后生效。</p>
    <div class="toolbar" style="gap:8px;flex-wrap:wrap;margin-top:12px">
      <button class="btn primary" disabled={!canContinue || selectedSources.length === 0} on:click={() => act('continue')}>{noNewHistory ? '当前已是最新' : isRunning ? '后台处理中' : loading ? '启动中' : '启动 / 继续处理'}</button>
      <button class="btn" disabled={loading || !job.id || !isRunning} on:click={() => act('pause')}>暂停</button>
      <button class="btn" disabled={loading} on:click={() => load()}>刷新状态</button>
    </div>
    {#if job.last_error}<div class="hint-card" style="margin-top:12px;color:var(--color-danger)">最近提示：{humanError(job.last_error)}</div>{/if}
  </div>

  <div class="card card-pad" style="margin-top:18px">
    <h2>执行记录</h2>
    <div class="list">
      {#each state?.events || [] as e}
        <div class="item">
          <div class="item-title">{e.event_type} · {e.created_at?.slice(0,19)}</div>
          <div class="item-summary">{e.message}</div>
        </div>
      {:else}
        <div class="empty">暂无执行记录</div>
      {/each}
    </div>
  </div>
</section>

<style>
  .step-row, .source-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:10px; }
  .step-row.compact { margin-top:14px; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
  .step-pill, .source-card { border:1px solid var(--border-subtle, rgba(148,163,184,.22)); border-radius:14px; padding:12px; background:var(--bg-card, rgba(255,255,255,.72)); }
  .step-pill.active { border-color: var(--accent, #4f8cff); box-shadow:0 0 0 2px rgba(79,140,255,.14); }
  .step-pill.done { opacity:.72; }
  .progress-head { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; }
  .progress-percent { font-size:32px; font-weight:800; color:var(--accent, #4f8cff); }
  .progress-track { height:12px; border-radius:999px; background:rgba(148,163,184,.18); overflow:hidden; margin-top:14px; }
  .progress-fill { height:100%; border-radius:999px; background:linear-gradient(90deg, var(--accent, #4f8cff), #68e1fd); transition:width .35s ease; }
  .field-help { display:flex; align-items:center; min-height:38px; }
</style>
