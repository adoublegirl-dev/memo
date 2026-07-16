<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  let graph = null;
  onMount(async()=> graph = await api.graph());
</script>
<section class="page">
  <h1 class="page-title">图谱</h1>
  <p class="page-subtitle">特征词与记忆关系的可视化入口。Canvas 图谱重写将在下一阶段接入。</p>
  <div class="card card-pad" style="margin-top:24px;min-height:520px;display:grid;place-items:center;position:relative;overflow:hidden">
    <div style="position:absolute;width:340px;height:340px;border-radius:50%;background:var(--color-gold-soft);filter:blur(28px);animation:pulse-ring 2.2s infinite"></div>
    <div style="text-align:center;z-index:1">
      <div class="stat-value">{graph?.nodes?.length || 0}</div>
      <div class="stat-label">图谱节点</div>
      <p class="muted">当前保留 API 与页面门面，后续改为 Canvas 2D + D3-force 渲染。</p>
    </div>
  </div>
</section>
