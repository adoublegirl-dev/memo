<script>
  export let icon = null;
  export let value = 0;
  export let label = '';
  export let tone = '';
</script>

<div class="card card-pad">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
    <div>
      <div class="stat-value">{value}</div>
      <div class="stat-label">{label}</div>
    </div>
    {#if icon}
      <svelte:component this={icon} size={24} strokeWidth={1.5} color={tone || 'var(--color-text-tertiary)'}/>
    {/if}
  </div>
</div>
