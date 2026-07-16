<script>
  import { FileText, GitBranch, Heart, Calendar, Lightbulb } from '@lucide/svelte';
  export let memory;
  const icons = { FACT: FileText, DECISION: GitBranch, PREFERENCE: Heart, EVENT: Calendar, REASONING: Lightbulb };
  $: Icon = icons[memory?.memory_type] || FileText;
</script>

<div class="item">
  <div style="display:flex;gap:12px;align-items:flex-start">
    <div class="badge"><Icon size={14} strokeWidth={1.5}/>{memory.memory_type || 'FACT'}</div>
    <div style="min-width:0;flex:1">
      <div class="item-title">{memory.title || '无标题记忆'}</div>
      <div class="item-meta">置信度 {Math.round((memory.confidence || 0) * 100)}% · {memory.source_agent || memory.session_id || '?'}</div>
      {#if memory.summary}<div class="item-summary">{memory.summary}</div>{/if}
      {#if memory.feature_tags?.length}
        <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">
          {#each memory.feature_tags.slice(0, 6) as tag}<span class="badge green">{tag}</span>{/each}
        </div>
      {/if}
    </div>
  </div>
</div>
