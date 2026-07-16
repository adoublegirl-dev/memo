<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import TodoCard from '../components/TodoCard.svelte';
  let data = null;
  async function load(){ data = await api.todos(); }
  async function close(id){ await api.todoAction({action:'close', id}); await load(); }
  onMount(load);
</script>
<section class="page">
  <h1 class="page-title">待办</h1>
  <p class="page-subtitle">把记忆中的行动项落到地面，关注风险和下一步。</p>
  {#if data?.risk}
    <div class="card card-pad" style="margin-top:24px;border-color:var(--color-gold)"><strong>风险状态</strong><p class="muted">{data.risk.summary}</p></div>
  {/if}
  <div class="two-col" style="margin-top:20px">
    <div><div class="section-head"><h2>进行中</h2></div><div class="list">{#each data?.todos || [] as t}<TodoCard todo={t} onClose={close}/>{:else}<div class="empty card">没有进行中的待办</div>{/each}</div></div>
    <div><div class="section-head"><h2>最近完成</h2></div><div class="list">{#each data?.done || [] as t}<TodoCard todo={t}/>{:else}<div class="empty card">暂无已完成待办</div>{/each}</div></div>
  </div>
</section>
