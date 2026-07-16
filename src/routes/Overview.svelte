<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import StatCard from '../components/StatCard.svelte';
  import MemoryCard from '../components/MemoryCard.svelte';
  import TodoCard from '../components/TodoCard.svelte';
  import { Database, MessageSquare, Share2, Activity } from '@lucide/svelte';
  let stats = null, tags = [], memories = [], todos = [];
  let selected = null, detailLoading = false;
  const typeLabels = { FACT:'事实', DECISION:'决策', PREFERENCE:'偏好', EVENT:'事件', REASONING:'推理' };
  const statusLabels = { active:'可引用', expired:'已过期', wrong:'已标错', muted:'不引用', deleted:'已删除' };
  onMount(async () => {
    const [statsData, tagsData, memoriesData, todosData] = await Promise.all([
      api.stats(), api.tags(), api.memories({ limit: 3 }), api.todos()
    ]);
    stats = statsData;
    tags = Array.isArray(tagsData) ? tagsData : [];
    memories = Array.isArray(memoriesData) ? memoriesData : [];
    todos = Array.isArray(todosData) ? todosData : (todosData?.todos || []);
  });
  async function openDetail(e) {
    const id = e.detail?.id;
    if (!id) return;
    detailLoading = true; selected = null;
    try { selected = await api.memory(id); }
    finally { detailLoading = false; }
  }
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
      <div class="list stagger">{#each memories as m}<MemoryCard memory={m} on:open={openDetail}/>{:else}<div class="empty card">暂无记忆</div>{/each}</div>
    </div>
    <div>
      <div class="section-head"><h2>待办速览</h2></div>
      <div class="list stagger">{#each todos.slice(0,5) as t}<TodoCard todo={t}/>{:else}<div class="empty card">暂无待办</div>{/each}</div>
    </div>
  </div>
</section>

{#if detailLoading || selected}
  <div class="modal-backdrop" role="button" tabindex="0" on:click={() => !detailLoading && (selected = null)} on:keydown={(e)=>e.key==='Escape' && !detailLoading && (selected=null)}>
    <div class="detail-modal" role="dialog" aria-modal="true" tabindex="0" on:click|stopPropagation on:keydown|stopPropagation>
      {#if detailLoading}
        <div class="skeleton" style="height:220px"></div>
      {:else}
        <div class="modal-head">
          <div>
            <span class="badge green">{typeLabels[String(selected.memory_type || 'FACT').toUpperCase()] || '事实'}</span>
            <h2>{selected.title || '无标题记忆'}</h2>
            <div class="item-meta">{statusLabels[selected.status || 'active']} · 置信度 {Math.round((selected.confidence || 0) * 100)}% · 权重 {selected.user_weight ?? 1}</div>
          </div>
          <button class="icon-btn" on:click={() => selected = null}>×</button>
        </div>
        <div class="modal-section"><h3>摘要</h3><p>{selected.summary_detail || selected.summary || '暂无摘要'}</p></div>
        <div class="modal-section"><h3>原文</h3><div class="raw-box">{selected.raw_text || '暂无原文'}</div></div>
        {#if selected.feature_tags?.length}<div class="modal-section"><h3>标签</h3><div class="toolbar" style="flex-wrap:wrap">{#each selected.feature_tags as tag}<span class="badge green">{tag}</span>{/each}</div></div>{/if}
      {/if}
    </div>
  </div>
{/if}
