<script>
  import { Layers, ArrowRight, CheckCircle2, Database } from '@lucide/svelte';
  export let space;
</script>

<div class="card card-pad">
  <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px">
    <div>
      <div class="badge gold"><Layers size={14}/>{space.type || 'general'}</div>
      <h3 style="margin:12px 0 6px;font-size:var(--text-xl);letter-spacing:-.03em">{space.name}</h3>
      <p class="muted" style="margin:0;line-height:1.6">{space.description || space.goal || '暂无描述'}</p>
    </div>
    <ArrowRight size={18} color="var(--color-text-tertiary)"/>
  </div>
  <div style="margin-top:18px;display:flex;gap:8px;flex-wrap:wrap">
    <span class="badge"><Database size={13}/>{space.memory_count || 0} 记忆</span>
    <span class="badge"><CheckCircle2 size={13}/>{space.todo_count || 0} 待办</span>
    <span class="badge">{space.status || 'active'}</span>
  </div>
</div>
