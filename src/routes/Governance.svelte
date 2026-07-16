<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { GitMerge, RefreshCcw, ShieldCheck, Layers3 } from '@lucide/svelte';

  let overview = null;
  let loading = false;
  let error = '';
  let openGroup = '';

  const typeLabels = { FACT:'事实', DECISION:'决策', PREFERENCE:'偏好', EVENT:'事件', REASONING:'推理' };
  const statusLabels = { active:'可引用', expired:'已过期', wrong:'已标错', muted:'已合并/静默', deleted:'已删除' };

  async function load() {
    loading = true; error = '';
    try { overview = await api.governance({ limit: 80 }); }
    catch (e) { error = e.message; }
    finally { loading = false; }
  }

  async function mergeMember(group, member) {
    if (!confirm(`确认将「${member.title}」合并到「${group.canonical_title}」吗？\n\n这会把源记忆标记为“不引用”，但不会物理删除。`)) return;
    await api.memoryLink({
      source_memory_id: member.id,
      target_memory_id: group.canonical_id,
      relation_type: 'MERGED_INTO',
      confidence: 1,
      reason: 'manual source group merge from governance page',
    });
    await load();
  }

  function fmtTime(s) { return s ? String(s).slice(0, 19).replace('T', ' ') : ''; }
  onMount(load);
</script>

<section class="page">
  <div class="page-head-row">
    <div>
      <h1 class="page-title">记忆治理总控</h1>
      <p class="page-subtitle">按同源输入聚合重复记忆，查看 ingestion、去重记录和合并链。分类不同不会拆成多条展示，统一回到同一个 source group 里维护。</p>
    </div>
    <button class="btn primary" class:loading={loading} disabled={loading} on:click={load}><RefreshCcw size={16}/> 刷新</button>
  </div>

  {#if error}<div class="card card-pad" style="color:var(--color-danger);margin-top:16px">{error}</div>{/if}

  <div class="grid cols-4" style="margin-top:22px">
    <div class="card stat-card"><ShieldCheck size={20}/><div><strong>{overview?.dedupe_records?.length ?? 0}</strong><span>去重记录</span></div></div>
    <div class="card stat-card"><Layers3 size={20}/><div><strong>{overview?.source_groups?.length ?? 0}</strong><span>同源组</span></div></div>
    <div class="card stat-card"><GitMerge size={20}/><div><strong>{overview?.memory_links?.length ?? 0}</strong><span>合并链</span></div></div>
    <div class="card stat-card"><RefreshCcw size={20}/><div><strong>{overview?.ingestion_events?.length ?? 0}</strong><span>输入事件</span></div></div>
  </div>

  <div class="section-title" style="margin-top:28px">同源输入分组</div>
  <div class="list stagger" style="margin-top:14px">
    {#if loading}
      {#each Array(4) as _}<div class="card card-pad"><div class="skeleton" style="height:112px"></div></div>{/each}
    {:else if overview?.source_groups?.length}
      {#each overview.source_groups as group}
        <div class="card card-pad source-group-card">
          <div class="item-row">
            <div>
              <div class="item-title">{group.canonical_title || '未命名同源组'}</div>
              <div class="item-meta">
                {group.count} 条 · 主记忆 {group.canonical_id?.slice(0,8)} · {fmtTime(group.created_at_min)} ~ {fmtTime(group.created_at_max)}
              </div>
            </div>
            <button class="btn" on:click={() => openGroup = openGroup === group.source_hash ? '' : group.source_hash}>{openGroup === group.source_hash ? '收起' : '展开'}</button>
          </div>
          <div class="toolbar" style="margin-top:12px;flex-wrap:wrap">
            {#each group.memory_types || [] as t}<span class="badge green">{typeLabels[String(t).toUpperCase()] || t}</span>{/each}
            {#each group.statuses || [] as s}<span class="badge">{statusLabels[s] || s}</span>{/each}
          </div>
          <p class="item-summary" style="margin-top:12px">{group.normalized_preview}</p>
          {#if openGroup === group.source_hash}
            <div class="list" style="margin-top:14px">
              {#each group.members as member}
                <div class="item source-member" class:canonical={member.id === group.canonical_id}>
                  <div>
                    <div class="item-title">{member.title}</div>
                    <div class="item-meta">{member.id.slice(0,8)} · {typeLabels[String(member.memory_type || 'FACT').toUpperCase()] || member.memory_type} · {statusLabels[member.status || 'active']} · 置信度 {Math.round((member.confidence || 0) * 100)}%</div>
                    <div class="item-summary">{member.summary}</div>
                  </div>
                  {#if member.id !== group.canonical_id && member.status !== 'muted'}
                    <button class="btn" on:click={() => mergeMember(group, member)}>合并到主记忆</button>
                  {:else if member.id === group.canonical_id}
                    <span class="badge green">主记忆</span>
                  {:else}
                    <span class="badge">已合并</span>
                  {/if}
                </div>
              {/each}
            </div>
          {/if}
        </div>
      {/each}
    {:else}
      <div class="empty card">暂无同源重复组</div>
    {/if}
  </div>

  <div class="section-title" style="margin-top:28px">最近合并链</div>
  <div class="list" style="margin-top:14px">
    {#each overview?.memory_links || [] as l}
      <div class="item"><div class="item-title">{l.relation_type}: {l.source_memory_id?.slice(0,8)} → {l.target_memory_id?.slice(0,8)}</div><div class="item-meta">{fmtTime(l.created_at)} · {l.created_by}</div><div class="item-summary">{l.reason}</div></div>
    {:else}
      {#if !loading}<div class="empty card">暂无合并链</div>{/if}
    {/each}
  </div>
</section>
