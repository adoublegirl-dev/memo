<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import StatCard from '../components/StatCard.svelte';
  import MemoryCard from '../components/MemoryCard.svelte';
  import TodoCard from '../components/TodoCard.svelte';
  import { Database, MessageSquare, Share2, Activity } from '@lucide/svelte';
  let stats = null, tags = [], memories = [], todos = [];
  onMount(async () => {
    [stats, tags, memories, todos] = await Promise.all([
      api.stats(), api.tags(), api.memories({ limit: 3 }), api.todos()
    ]);
    todos = todos.todos || [];
  });
</script>

<section class="page">
  <h1 class="page-title">总览</h1>
  <p class="page-subtitle">你的跨 Agent 长期上下文资产，一眼看清当前活跃状态。</p>

  {#if stats}
    <div class="grid stats" style="margin-top:26px">
      <StatCard icon={Database} value={stats.memories} label="记忆" tone="var(--color-gold)" />
      <StatCard icon={MessageSquare} value={stats.sessions} label="会话" />
      <StatCard icon={Share2} value={stats.relations} label="关系" />
      <StatCard icon={Activity} value={stats.vector_index_size} label="向量索引" />
    </div>
  {:else}
    <div class="grid stats" style="margin-top:26px">{#each Array(4) as _}<div class="card card-pad"><div class="skeleton" style="height:70px"></div></div>{/each}</div>
  {/if}

  <div class="section-head"><h2>活跃特征词</h2></div>
  <div class="card card-pad" style="display:flex;gap:8px;flex-wrap:wrap">
    {#each tags.slice(0, 28) as tag}<span class="badge green">{tag.name}</span>{/each}
    {#if !tags.length}<div class="empty">暂无特征词</div>{/if}
  </div>

  <div class="two-col" style="margin-top:18px">
    <div>
      <div class="section-head"><h2>最近记忆</h2></div>
      <div class="list stagger">{#each memories as m}<MemoryCard memory={m}/>{:else}<div class="empty card">暂无记忆</div>{/each}</div>
    </div>
    <div>
      <div class="section-head"><h2>待办速览</h2></div>
      <div class="list stagger">{#each todos.slice(0,5) as t}<TodoCard todo={t}/>{:else}<div class="empty card">暂无待办</div>{/each}</div>
    </div>
  </div>
</section>
