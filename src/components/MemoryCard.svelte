<script>
  import { createEventDispatcher } from 'svelte';
  import { FileText, GitBranch, Heart, Calendar, Lightbulb, Pin, AlertTriangle, Clock, VolumeX, Trash2, RotateCcw, HelpCircle, TrendingUp, TrendingDown, MessageSquareText } from '@lucide/svelte';
  export let memory;
  export let actionable = false;
  export let busy = false;
  const dispatch = createEventDispatcher();
  const icons = { FACT: FileText, DECISION: GitBranch, PREFERENCE: Heart, EVENT: Calendar, REASONING: Lightbulb };
  const typeLabels = { FACT: '事实', DECISION: '决策', PREFERENCE: '偏好', EVENT: '事件', REASONING: '推理' };
  const statusLabels = { active: '可引用', expired: '已过期', wrong: '已标错', muted: '不引用', deleted: '已删除' };
  let showExplain = false;
  $: typeKey = String(memory?.memory_type || 'FACT').toUpperCase();
  $: Icon = icons[typeKey] || FileText;
  $: explanation = memory?.explanation || buildExplanation(memory || {});

  function act(action, extra = {}) { if (!busy) dispatch('govern', { id: memory.id, action, ...extra }); }
  function open() { dispatch('open', { id: memory.id }); }

  function buildExplanation(m) {
    const reasons = [];
    const tags = m.feature_tags || [];
    const status = m.status || 'active';
    const weight = Number(m.user_weight ?? 1);
    const participates = !['wrong', 'muted', 'deleted'].includes(status);
    if (tags.length) reasons.push(`它和这些关键词相关：${tags.slice(0, 5).join('、')}`);
    if (m.pinned) reasons.push('你已经把它标为重要，所以它会更容易被想起');
    if (status === 'active') reasons.push('它当前处于可引用状态');
    if (status === 'expired') reasons.push('它已被标记为过期，仍可参考，但会被明显降权');
    if (status === 'wrong') reasons.push('它已被标记为错误，默认不会再参与召回');
    if (status === 'muted') reasons.push('它已被设置为不再引用，默认不会参与召回');
    if (status === 'deleted') reasons.push('它已被软删除，默认不会参与召回');
    if (weight > 1.05) reasons.push('你提高过它的权重，因此它会更容易被想起');
    if (weight < 0.95 && participates) reasons.push('你降低过它的权重，因此它只会谨慎参与参考');
    if (m.from_current_space) reasons.push('它属于当前 Space，和当前工作场景更接近');
    if (m.from_current_session) reasons.push('它来自当前会话，时间和语境都更近');
    if (!reasons.length) reasons.push('它目前没有特殊治理标记，按普通长期记忆处理');
    return { summary: '这条记忆会根据相关性、状态和你的治理操作决定是否参与回答。', reasons, participates, status, pinned: !!m.pinned, user_weight: weight, raw_score: m.raw_score, final_score: m.score };
  }
</script>

<div class="item" class:muted-memory={memory.status && memory.status !== 'active'}>
  <div style="display:flex;gap:12px;align-items:flex-start">
    <div class="badge"><Icon size={14} strokeWidth={1.5}/>{typeLabels[typeKey] || '事实'}</div>
    <div style="min-width:0;flex:1">
      <button class="title-link" on:click={open} title="查看详情">
        {#if memory.pinned}<Pin size={14} style="vertical-align:-2px;color:var(--color-gold)"/> {/if}{memory.title || '无标题记忆'}
      </button>
      <div class="item-meta">
        置信度 {Math.round((memory.confidence || 0) * 100)}% · 权重 {memory.user_weight ?? 1} · {statusLabels[memory.status || 'active'] || memory.status || '可引用'} · {memory.source_agent || memory.session_id || '?'}
      </div>
      {#if memory.summary}<div class="item-summary clamp-summary">{memory.summary}</div>{/if}
      {#if memory.user_note}<div class="item-summary">备注：{memory.user_note}</div>{/if}
      {#if memory.feature_tags?.length}
        <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">
          {#each memory.feature_tags.slice(0, 6) as tag}<span class="badge green">{tag}</span>{/each}
        </div>
      {/if}

      <div class="toolbar" style="margin-top:12px;flex-wrap:wrap">
        <button class="btn" disabled={busy} on:click={() => showExplain = !showExplain}><HelpCircle size={14}/>{showExplain ? '收起解释' : '为什么会想起它？'}</button>
        {#if actionable}
          <button class="btn" disabled={busy} on:click={() => act(memory.pinned ? 'unpin' : 'pin')}><Pin size={14}/>{memory.pinned ? '取消重要' : '标重要'}</button>
          <button class="btn" disabled={busy} on:click={() => act('boost')}><TrendingUp size={14}/>更常引用</button>
          <button class="btn" disabled={busy} on:click={() => act('lower')}><TrendingDown size={14}/>少引用</button>
          <button class="btn" disabled={busy} on:click={() => act('note')}><MessageSquareText size={14}/>备注</button>
          <button class="btn" disabled={busy} on:click={() => act('mark_wrong')}><AlertTriangle size={14}/>标为错误</button>
          <button class="btn" disabled={busy} on:click={() => act('mark_expired')}><Clock size={14}/>标为过期</button>
          <button class="btn" disabled={busy} on:click={() => act('mute')}><VolumeX size={14}/>不再引用</button>
          {#if memory.status && memory.status !== 'active'}
            <button class="btn" disabled={busy} on:click={() => act('restore')}><RotateCcw size={14}/>恢复引用</button>
          {/if}
          {#if memory.status !== 'deleted'}
            <button class="btn danger" disabled={busy} on:click={() => act('delete')}><Trash2 size={14}/>软删除</button>
          {/if}
        {/if}
      </div>

      {#if showExplain}
        <div class="card card-pad explain-card">
          <div class="item-title" style="font-size:14px">为什么会想起它？</div>
          <p class="muted" style="margin:6px 0 10px">{explanation.summary}</p>
          <ul style="margin:0;padding-left:18px;color:var(--color-text);line-height:1.7">
            {#each explanation.reasons || [] as reason}<li>{reason}</li>{/each}
          </ul>
          <div class="toolbar" style="margin-top:12px">
            {#if explanation.participates}<span class="badge green">可参与回答</span>{:else}<span class="badge">默认不再引用</span>{/if}
            {#if explanation.final_score}<span class="item-meta">排序参考分：{explanation.final_score}</span>{/if}
          </div>
          {#if actionable}
            <div class="toolbar" style="margin-top:10px;flex-wrap:wrap">
              <button class="btn" disabled={busy} on:click={() => act('pin')}>这条很重要</button>
              <button class="btn" disabled={busy} on:click={() => act('boost')}>以后多参考</button>
              <button class="btn" disabled={busy} on:click={() => act('lower')}>以后少参考</button>
              <button class="btn" disabled={busy} on:click={() => act('mute')}>别再引用</button>
              <button class="btn danger" disabled={busy} on:click={() => act('mark_wrong')}>这条是错的</button>
            </div>
          {/if}
        </div>
      {/if}
    </div>
  </div>
</div>
