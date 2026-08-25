<script>
  import { onMount, onDestroy } from 'svelte';
  import flatpickr from 'flatpickr';
  import { Mandarin } from 'flatpickr/dist/l10n/zh.js';
  import 'flatpickr/dist/flatpickr.min.css';

  export let value = '';
  export let placeholder = '选择日期和时间';
  export let disabled = false;
  export let title = '日期和时间，精确到分钟';

  let input;
  let picker = null;

  onMount(() => {
    picker = flatpickr(input, {
      enableTime: true,
      time_24hr: true,
      minuteIncrement: 1,
      allowInput: true,
      disableMobile: true,
      dateFormat: 'Y-m-d\\TH:i',
      altInput: true,
      altFormat: 'Y年m月d日 H:i',
      locale: Mandarin,
      defaultDate: value || null,
      onChange: (_dates, dateString) => { value = dateString || ''; },
      onValueUpdate: (_dates, dateString) => { value = dateString || ''; },
    });
  });

  onDestroy(() => picker?.destroy());

  $: if (picker && value !== picker.input?.value) picker.setDate(value || null, false, 'Y-m-d\\TH:i');
  $: if (picker) {
    picker.input.disabled = disabled;
    if (picker.altInput) picker.altInput.disabled = disabled;
  }
</script>

<input
  bind:this={input}
  class="input datetime-picker"
  type="text"
  {placeholder}
  {disabled}
  {title}
/>

<style>
  .datetime-picker { min-width: 205px; }
  :global(.flatpickr-calendar) {
    border: 1px solid var(--border-subtle, rgba(148,163,184,.22));
    border-radius: 14px;
    box-shadow: 0 18px 50px rgba(15,23,42,.18);
    overflow: hidden;
    font-family: inherit;
  }
  :global(.flatpickr-day.selected),
  :global(.flatpickr-day.selected:hover) {
    background: var(--accent, #4f8cff);
    border-color: var(--accent, #4f8cff);
  }
  :global(.flatpickr-day.today) { border-color: var(--accent, #4f8cff); }
  :global(.flatpickr-time input),
  :global(.flatpickr-current-month),
  :global(span.flatpickr-weekday) { font-family: inherit; }
</style>
