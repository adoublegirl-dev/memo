<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  let data = null, active = '';
  const labels = { value:'价值观', decision:'决策', identity:'身份', preference:'偏好', sensitivity:'敏感', relationship:'关系', knowledge:'知识边界', communication:'沟通', mental_model:'思维模型', emotion:'情绪' };
  onMount(async()=>{ data = await api.persona(); active = Object.keys(data.assertions || {})[0] || ''; });
</script>
<section class="page">
  <h1 class="page-title">人格画像</h1>
  <p class="page-subtitle">从长期记忆中提炼出的判断偏好和沟通倾向，辅助但不替代决策。</p>
  <div class="two-col" style="grid-template-columns:260px 1fr;margin-top:24px">
    <div class="card card-pad"><div class="list">{#each Object.entries(data?.assertions || {}) as [dim, items]}<button class="btn" class:primary={active===dim} on:click={()=>active=dim} style="justify-content:space-between"><span>{labels[dim] || dim}</span><span>{items.length}</span></button>{/each}</div></div>
    <div class="list stagger">{#each (data?.assertions?.[active] || []) as a}<div class="item"><div class="item-title">{a.assertion}</div><div class="item-meta">置信度 {Math.round(a.confidence*100)}% · 来源 {a.evidences?.length || 0} 条记忆</div><div style="height:6px;background:var(--color-surface-hover);border-radius:99px;margin-top:12px"><div style={`height:100%;width:${Math.round(a.confidence*100)}%;background:var(--color-green);border-radius:99px`}></div></div></div>{:else}<div class="empty card">暂无人格断言</div>{/each}</div>
  </div>
</section>
