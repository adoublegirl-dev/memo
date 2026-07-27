<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';

  let state = null, loading = false, error = '';
  let selected = new Set();
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

  $: job = state?.job || {};
  $: detectAgents = job.detect_report?.agents || [];
  $: selectedSources = Array.from(selected);
  $: canContinue = state?.schema_ready && !loading && job.status !== 'done';

  async function load() {
    try {
      state = await api.historyProcessing();
      const existing = state?.job?.selected_sources || [];
      selected = new Set(existing);
    } catch (e) { error = e.message; }
  }
  async function act(action, extra = {}) {
    loading = true; error = '';
    try {
      state = await api.historyProcessingAction({ action, selected_sources: selectedSources, model_config: model, ...extra });
      const existing = state?.job?.selected_sources || selectedSources;
      selected = new Set(existing);
    } catch (e) { error = e.message; }
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

  onMount(load);
</script>

<section class="page">
  <h1 class="page-title">历史会话处理</h1>
  <p class="page-subtitle">安装或升级后，按需处理本机 HanaAgent / WorkBuddy / Codex 的历史会话。旧 memo.db 不连接、不覆盖，只在当前新库上增量导入。</p>

  {#if error}<div class="card card-pad" style="color:var(--color-danger);margin-top:12px">{error}</div>{/if}
  {#if !state?.schema_ready}
    <div class="hint-card" style="margin-top:12px">历史处理表尚未就绪，请重启 Memo 让 migration 执行完成。</div>
  {/if}

  <div class="grid cols-4" style="margin-top:18px">
    <div class="card stat-card"><div><strong>{statusLabels[job.status] || '未开始'}</strong><span>任务状态</span></div></div>
    <div class="card stat-card"><div><strong>{stepLabels[job.current_step] || '检测历史源'}</strong><span>当前阶段</span></div></div>
    <div class="card stat-card"><div><strong>{selectedSources.length}</strong><span>已选来源</span></div></div>
    <div class="card stat-card"><div><strong>{job.updated_at ? job.updated_at.slice(5,16).replace('T',' ') : '—'}</strong><span>最近更新</span></div></div>
  </div>

  <div class="card card-pad" style="margin-top:18px">
    <h2>处理顺序</h2>
    <div class="step-row">
      {#each state?.steps || [] as step, i}
        <div class="step-pill" class:active={job.current_step === step} class:done={stepIndex(job.current_step) > i || job.current_step === 'done'}>{i + 1}. {stepLabels[step]}</div>
      {/each}
    </div>
    <div class="hint-card" style="margin-top:12px">{state?.llm_note}</div>
  </div>

  <div class="card card-pad" style="margin-top:18px">
    <div class="toolbar" style="justify-content:space-between;gap:12px;flex-wrap:wrap">
      <div>
        <h2>1. 检测历史源</h2>
        <div class="item-meta">只读扫描本机 Agent 历史位置，不写入记忆库。</div>
      </div>
      <button class="btn primary" disabled={loading} on:click={() => act('scan')}>{loading ? '执行中' : '检测历史'}</button>
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
        <button class="btn" class:primary={selected.has(s.id)} on:click={() => toggleSource(s.id)}>{selected.has(s.id) ? '✓ ' : ''}{s.label}</button>
      {/each}
    </div>
  </div>

  <div class="card card-pad" style="margin-top:18px">
    <h2>3. 模型配置（LLM 最后一步使用）</h2>
    <div class="grid cols-4" style="margin-top:10px">
      <input class="input" bind:value={model.base_url} placeholder="Base URL，如 https://api.deepseek.com" />
      <input class="input" bind:value={model.model} placeholder="Model，如 deepseek-chat" />
      <input class="input" bind:value={model.api_key} placeholder="API Key（只保存本机）" />
      <input class="input" bind:value={model.batch_size} placeholder="批次大小" />
    </div>
    <div class="toolbar" style="margin-top:12px">
      <button class="btn" disabled={loading} on:click={() => act('save_config')}>保存配置</button>
    </div>
  </div>

  <div class="card card-pad" style="margin-top:18px">
    <h2>4. 执行 / 继续</h2>
    <p class="item-meta">每次点击会执行当前阶段并写入状态。中断、重启或失败后，可以回来点“继续下一步”。</p>
    <div class="toolbar" style="gap:8px;flex-wrap:wrap;margin-top:12px">
      <button class="btn primary" disabled={!canContinue || selectedSources.length === 0} on:click={() => act('continue')}>{loading ? '执行中' : '继续下一步'}</button>
      <button class="btn" disabled={loading || !job.id} on:click={() => act('pause')}>暂停</button>
      <button class="btn" disabled={loading} on:click={load}>刷新状态</button>
    </div>
    {#if job.last_error}<div class="hint-card" style="margin-top:12px;color:var(--color-danger)">最近错误：{job.last_error}</div>{/if}
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
  .step-pill, .source-card { border:1px solid var(--border-subtle, rgba(148,163,184,.22)); border-radius:14px; padding:12px; background:var(--bg-card, rgba(255,255,255,.72)); }
  .step-pill.active { border-color: var(--accent, #4f8cff); box-shadow:0 0 0 2px rgba(79,140,255,.14); }
  .step-pill.done { opacity:.72; }
</style>
