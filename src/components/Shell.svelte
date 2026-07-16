<script>
  import { onMount } from 'svelte';
  import { route, navigate, theme, setTheme, initRouter } from '../lib/stores.js';
  import { LayoutDashboard, Share2, Brain, Fingerprint, CheckCircle2, Layers, Moon, Sun, Search, Sparkles } from '@lucide/svelte';

  const nav = [
    ['/', LayoutDashboard, '总览'],
    ['/graph', Share2, '图谱'],
    ['/memories', Brain, '记忆'],
    ['/spaces', Layers, '空间'],
    ['/persona', Fingerprint, '人格'],
    ['/todos', CheckCircle2, '待办'],
  ];
  onMount(() => initRouter());
</script>

<div class="shell">
  <aside class="sidebar">
    <div class="brand" title="Memo"><Sparkles size={21} strokeWidth={1.6}/></div>
    <nav class="nav">
      {#each nav as [path, Icon, label]}
        <button class:active={$route === path} on:click={() => navigate(path)} title={label}>
          <Icon size={20} strokeWidth={1.55}/>
        </button>
      {/each}
    </nav>
  </aside>
  <main class="main">
    <div class="topbar">
      <div>
        <strong>Memo</strong>
        <span class="muted" style="margin-left:10px">本地私有 AI 上下文中枢</span>
      </div>
      <div class="toolbar">
        <button class="btn" on:click={() => navigate('/memories')}><Search size={16}/> 搜索记忆</button>
        <button class="icon-btn" on:click={() => setTheme($theme === 'dark' ? 'light' : 'dark')} title="切换主题">
          {#if $theme === 'dark'}<Sun size={18}/>{:else}<Moon size={18}/>{/if}
        </button>
      </div>
    </div>
    <slot />
  </main>
</div>
