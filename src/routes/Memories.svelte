<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import MemoryCard from '../components/MemoryCard.svelte';
  let q = '', memories = [], loading = false;
  async function load() { loading = true; memories = await api.memories({ q, limit: 100 }); loading = false; }
  onMount(load);
</script>
<section class="page">
  <h1 class="page-title">记忆</h1>
  <p class="page-subtitle">搜索、检查和理解 Memo 沉淀下来的长期上下文。</p>
  <div class="toolbar" style="margin-top:24px"><input class="input" style="width:min(560px,100%)" bind:value={q} on:keydown={(e)=>e.key==='Enter'&&load()} placeholder="搜索标题、摘要或原文"/><button class="btn primary" on:click={load}>搜索</button></div>
  <div class="list stagger" style="margin-top:18px">
    {#if loading}
      <div class="card card-pad"><div class="skeleton" style="height:90px"></div></div>
    {:else}
      {#each memories as m}
        <MemoryCard memory={m}/>
      {:else}
        <div class="empty card">暂无匹配记忆</div>
      {/each}
    {/if}
  </div>
</section>
