<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  let data = null, active = '', selected = null, draft = null;
  let form = { dimension:'preference', assertion:'', confidence:0.8, locked:true };
  const labels = { value:'价值观', decision:'决策', identity:'身份', preference:'偏好', sensitivity:'敏感', relationship:'关系', knowledge:'知识边界', communication:'沟通', mental_model:'思维模型', emotion:'情绪' };

  async function load() {
    data = await api.persona();
    active = active || Object.keys(data.assertions || {})[0] || 'preference';
  }
  function edit(a) { selected = a; draft = { assertion:a.assertion, confidence:a.confidence }; }
  async function save(a) { await api.personaAction({ action:'edit', id:a.id, assertion:draft.assertion, confidence:Number(draft.confidence) }); selected=null; draft=null; await load(); }
  async function lock(a, locked) { await api.personaAction({ action:locked?'lock':'unlock', id:a.id }); await load(); }
  async function remove(a) { if(!confirm('软删除这条人格断言？它不会物理删除，可通过审计记录恢复。')) return; await api.personaAction({ action:'delete', id:a.id, note:'用户在 Dashboard 软删除' }); await load(); }
  async function create() { if(!form.assertion.trim()) return; await api.personaAction({ action:'create', ...form }); form.assertion=''; active=form.dimension; await load(); }
  async function refresh() { await api.personaAction({ action:'refresh', id:'refresh' }); await load(); }
  async function sensitivity(level) { await api.personaAction({ action:'set_sensitivity', id:String(level) }); await load(); }
  onMount(load);
</script>

<section class="page">
  <h1 class="page-title">人格画像</h1>
  <p class="page-subtitle">从长期记忆中提炼出的判断偏好和沟通倾向。支持编辑、锁定、删除、补充自定义断言和查看证据。</p>

  <div class="toolbar" style="margin:20px 0">
    <button class="btn" on:click={refresh}>增量刷新</button>
    <span class="item-meta">灵敏度</span>
    {#each [1,2,3,4,5] as l}<button class="btn" class:primary={String(l)===(data?.settings?.sensitivity_level || '2')} on:click={() => sensitivity(l)}>{l}</button>{/each}
  </div>

  <div class="card card-pad" style="margin-bottom:18px">
    <div class="section-head"><h2>新增自定义断言</h2></div>
    <div style="display:grid;grid-template-columns:180px 1fr 120px auto;gap:10px">
      <select class="input" bind:value={form.dimension}>{#each Object.entries(labels) as [k,v]}<option value={k}>{v}</option>{/each}</select>
      <input class="input" bind:value={form.assertion} placeholder="输入一条你希望固定的人格/偏好断言" />
      <input class="input" type="number" min="0" max="1" step="0.05" bind:value={form.confidence} />
      <button class="btn primary" on:click={create}>添加</button>
    </div>
  </div>

  <div class="two-col" style="grid-template-columns:260px 1fr;margin-top:24px">
    <div class="card card-pad"><div class="list">{#each Object.entries(data?.assertions || {}) as [dim, items]}<button class="btn" class:primary={active===dim} on:click={()=>active=dim} style="justify-content:space-between"><span>{labels[dim] || dim}</span><span>{items.length}</span></button>{/each}</div></div>
    <div class="list stagger">
      {#each (data?.assertions?.[active] || []) as a}
        <div class="item">
          {#if selected?.id === a.id}
            <textarea class="input" style="width:100%;min-height:90px" bind:value={draft.assertion}></textarea>
            <div class="toolbar" style="margin-top:10px"><input class="input" type="number" min="0" max="1" step="0.05" bind:value={draft.confidence}/><button class="btn primary" on:click={() => save(a)}>保存</button><button class="btn" on:click={() => selected=null}>取消</button></div>
          {:else}
            <div class="item-title">{a.locked ? '🔒 ' : ''}{a.assertion}</div>
            <div class="item-meta">置信度 {Math.round(a.confidence*100)}% · 来源 {a.evidences?.length || 0} 条记忆 · 更新 {a.updated_at?.slice(0,10) || '-'}</div>
            <div style="height:6px;background:var(--color-surface-hover);border-radius:99px;margin-top:12px"><div style={`height:100%;width:${Math.round(a.confidence*100)}%;background:var(--color-green);border-radius:99px`}></div></div>
            <div class="toolbar" style="margin-top:12px">
              <button class="btn" on:click={() => edit(a)}>编辑</button>
              <button class="btn" on:click={() => lock(a, !a.locked)}>{a.locked ? '解锁' : '锁定'}</button>
              <button class="btn danger" on:click={() => remove(a)}>删除</button>
            </div>
            <details style="margin-top:12px">
              <summary class="item-meta" style="cursor:pointer">查看证据来源</summary>
              <div class="list" style="margin-top:10px">
                {#each a.evidence_details || [] as e}<div class="card card-pad"><div class="item-title">{e.title}</div><p class="muted">{e.summary}</p><div class="item-meta">{e.id.slice(0,8)} · {e.created_at?.slice(0,10) || ''}</div></div>{:else}<div class="empty">暂无可展开证据，可能是旧版短 ID 或原记忆已不存在。</div>{/each}
              </div>
            </details>
            <details style="margin-top:10px">
              <summary class="item-meta" style="cursor:pointer">查看审计记录</summary>
              <div class="list" style="margin-top:10px">
                {#each a.audit || [] as log}<div class="item"><div class="item-title">{log.action}</div><div class="item-meta">{log.created_at?.slice(0,19)} · {log.actor}</div><div class="item-summary">{log.old_value} → {log.new_value} {log.note ? `· ${log.note}` : ''}</div></div>{:else}<div class="empty">暂无审计记录</div>{/each}
              </div>
            </details>
          {/if}
        </div>
      {:else}<div class="empty card">暂无人格断言</div>{/each}
    </div>
  </div>
</section>
