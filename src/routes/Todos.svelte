<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import TodoCard from '../components/TodoCard.svelte';
  let data = null, spaces = [];
  let form = { title:'', priority:'medium', due_date:'', space_id:'' };
  async function load(){ [data, spaces] = await Promise.all([api.todos(), api.spaces()]); }
  async function close(id){ await api.todoAction({action:'close', id}); await load(); }
  async function reopen(id){ await api.todoAction({action:'reopen', id}); await load(); }
  async function create(){ if(!form.title.trim()) return; await api.todoAction({action:'create', ...form}); form={title:'', priority:'medium', due_date:'', space_id:''}; await load(); }
  onMount(load);
</script>
<section class="page">
  <h1 class="page-title">待办</h1>
  <p class="page-subtitle">把记忆中的行动项落到地面，并与 Context Space 绑定。</p>
  <div class="card card-pad" style="margin-top:24px">
    <div class="toolbar" style="flex-wrap:wrap">
      <input class="input" bind:value={form.title} placeholder="新待办标题" style="min-width:280px;flex:1" />
      <select class="input" bind:value={form.priority}><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select>
      <input class="input" bind:value={form.due_date} placeholder="截止日期 YYYY-MM-DD" />
      <select class="input" bind:value={form.space_id}><option value="">不绑定 Space</option>{#each spaces as s}<option value={s.id}>{s.name}</option>{/each}</select>
      <button class="btn primary" on:click={create}>创建</button>
    </div>
  </div>
  {#if data?.risk}
    <div class="card card-pad" style="margin-top:18px;border-color:var(--color-gold)"><strong>风险状态</strong><p class="muted">{data.risk.summary}</p></div>
  {/if}
  <div class="two-col" style="margin-top:20px">
    <div><div class="section-head"><h2>进行中</h2></div><div class="list">{#each data?.todos || [] as t}<TodoCard todo={t} onClose={close}/>{:else}<div class="empty card">没有进行中的待办</div>{/each}</div></div>
    <div><div class="section-head"><h2>最近完成</h2></div><div class="list">{#each data?.done || [] as t}<TodoCard todo={t} onClose={reopen}/>{:else}<div class="empty card">暂无已完成待办</div>{/each}</div></div>
  </div>
</section>
