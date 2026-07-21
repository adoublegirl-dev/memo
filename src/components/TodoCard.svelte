<script>
  import { createEventDispatcher } from 'svelte';
  import { CheckCheck, RotateCcw, Pencil, Eye } from '@lucide/svelte';
  export let todo;
  export let riskLevel = '';
  export let busy = false;
  const dispatch = createEventDispatcher();

  const priorityLabels = { high: '高优先级', medium: '中优先级', low: '低优先级' };
  const statusLabels = { todo: '待处理', doing: '进行中', done: '已完成', cancelled: '已取消' };
  const riskLabels = { critical: '高风险', warning: '风险预警', info: '长期未处理' };
  function formatDue(value) {
    if (!value) return '无截止时间';
    return value.replace('T', ' ');
  }
</script>

<div class="item todo-card" class:risk-todo={!!riskLevel} class:critical-risk={riskLevel === 'critical'}>
  <div class="todo-main">
    <div class="todo-content">
      <div class="todo-title-row">
        <button class="title-link" on:click={() => dispatch('open', { id: todo.id })} title="查看详情">
          {todo.title}
        </button>
        {#if riskLevel}<span class="badge danger-soft">{riskLabels[riskLevel] || '风险'}</span>{/if}
      </div>
      <div class="item-meta">
        {priorityLabels[todo.priority] || todo.priority || '中优先级'} · {formatDue(todo.due_date)} · {statusLabels[todo.status] || todo.status}{todo.space_id ? ` · Space ${todo.space_id.slice(0,8)}` : ''}
      </div>
      {#if todo.description}<div class="item-summary clamp-summary">{todo.description}</div>{/if}
    </div>
    <div class="todo-actions">
      <button class="icon-btn" disabled={busy} on:click={() => dispatch('open', { id: todo.id })} title="查看详情"><Eye size={16}/></button>
      <button class="icon-btn" disabled={busy} on:click={() => dispatch('edit', { todo })} title="编辑"><Pencil size={16}/></button>
      {#if todo.status !== 'done'}
        <button class="icon-btn" disabled={busy} on:click={() => dispatch('close', { id: todo.id })} title="完成"><CheckCheck size={17}/></button>
      {:else}
        <button class="btn" disabled={busy} on:click={() => dispatch('reopen', { id: todo.id })} title="重开"><RotateCcw size={15}/>重开</button>
      {/if}
    </div>
  </div>
</div>
