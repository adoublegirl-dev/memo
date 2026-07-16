<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import SpaceCard from '../components/SpaceCard.svelte';
  import MemoryCard from '../components/MemoryCard.svelte';
  let spaces = [], selected = null, profile = null;
  let form = { name: '', type: 'management', description: '' };
  async function load() { spaces = await api.spaces(); if (!selected && spaces[0]) select(spaces[0]); }
  async function select(space) { selected = space; profile = await api.space(space.id); }
  async function create() { if (!form.name.trim()) return; await api.spaceAction({ action:'create', ...form }); form = { name:'', type:'management', description:'' }; await load(); }
  onMount(load);
</script>

<section class="page">
  <h1 class="page-title">上下文空间</h1>
  <p class="page-subtitle">把个人事项、管理项目、产品路线和开发工作装进可检索、可行动的空间。</p>

  <div class="two-col" style="margin-top:26px">
    <div>
      <div class="card card-pad" style="margin-bottom:16px">
        <div style="display:grid;grid-template-columns:1fr 150px auto;gap:10px">
          <input class="input" bind:value={form.name} placeholder="新空间名称，如 Memo / 某客户项目 / 健身计划" />
          <select class="input" bind:value={form.type}>
            <option value="management">管理项目</option><option value="product">产品项目</option><option value="personal">个人事项</option><option value="client">客户事务</option><option value="dev_project">开发项目</option><option value="writing">内容创作</option><option value="general">通用</option>
          </select>
          <button class="btn primary" on:click={create}>创建</button>
        </div>
        <input class="input" style="margin-top:10px;width:100%" bind:value={form.description} placeholder="描述这个空间的目标、背景或边界" />
      </div>
      <div class="grid stagger">
        {#each spaces as space}<button style="text-align:left;border:0;background:transparent;padding:0" on:click={() => select(space)}><SpaceCard {space}/></button>{/each}
      </div>
    </div>

    <aside class="card card-pad" style="position:sticky;top:92px">
      {#if profile}
        <span class="badge gold">{profile.space.type}</span>
        <h2 style="margin:12px 0 8px">{profile.space.name}</h2>
        <p class="muted" style="line-height:1.7">{profile.space.description || profile.space.goal || '暂无描述'}</p>
        <div class="grid stats" style="grid-template-columns:repeat(3,1fr);margin-top:14px">
          <div><div class="stat-value" style="font-size:24px">{profile.status.total_memories}</div><div class="stat-label">记忆</div></div>
          <div><div class="stat-value" style="font-size:24px">{profile.status.active_todos}</div><div class="stat-label">待办</div></div>
          <div><div class="stat-value" style="font-size:24px">{profile.status.total_sessions}</div><div class="stat-label">会话</div></div>
        </div>
        <div class="section-head"><h2>关键特征词</h2></div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">{#each profile.key_feature_tags || [] as t}<span class="badge green">{t.name} · {t.c}</span>{/each}</div>
        <div class="section-head"><h2>最近记忆</h2></div>
        <div class="list">{#each (profile.recent_memories || []).slice(0,4) as m}<MemoryCard memory={m}/>{:else}<div class="empty">暂无空间记忆</div>{/each}</div>
      {:else}
        <div class="empty">选择一个空间查看简报</div>
      {/if}
    </aside>
  </div>
</section>
