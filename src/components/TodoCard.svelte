<script>
  import { Flag, CheckCheck } from '@lucide/svelte';
  export let todo;
  export let onClose = () => {};
</script>

<div class="item" style="display:flex;align-items:center;justify-content:space-between;gap:14px">
  <div>
    <div class="item-title">{todo.title}</div>
    <div class="item-meta">{todo.priority || 'medium'} · {todo.due_date || '无截止日期'} · {todo.status}</div>
  </div>
  {#if todo.status !== 'done'}
    <button class="icon-btn" on:click={() => onClose(todo.id)} title="完成"><CheckCheck size={17}/></button>
  {:else}
    <span class="badge green"><Flag size={13}/> 已完成</span>
  {/if}
</div>
