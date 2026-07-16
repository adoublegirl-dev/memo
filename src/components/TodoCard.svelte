<script>
  import { Flag, CheckCheck, RotateCcw } from '@lucide/svelte';
  export let todo;
  export let onClose = () => {};
</script>

<div class="item" style="display:flex;align-items:center;justify-content:space-between;gap:14px">
  <div>
    <div class="item-title">{todo.title}</div>
    <div class="item-meta">{todo.priority || 'medium'} · {todo.due_date || '无截止日期'} · {todo.status}{todo.space_id ? ` · Space ${todo.space_id.slice(0,8)}` : ''}</div>
    {#if todo.description}<div class="item-summary">{todo.description}</div>{/if}
  </div>
  {#if todo.status !== 'done'}
    <button class="icon-btn" on:click={() => onClose(todo.id)} title="完成"><CheckCheck size={17}/></button>
  {:else}
    <button class="btn" on:click={() => onClose(todo.id)} title="重开"><RotateCcw size={15}/>重开</button>
  {/if}
</div>
