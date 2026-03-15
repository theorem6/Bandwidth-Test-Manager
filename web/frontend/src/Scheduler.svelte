<script lang="ts">
  import { onMount } from 'svelte';
  import { getBackendStatus, schedulerStart, schedulerStop } from './lib/api';
  import type { BackendStatus } from './lib/api';

  export let loadStatus: () => Promise<void>;
  export let onToast: (msg: string, type?: 'success' | 'error') => void;

  let starting = false;
  let stopping = false;
  let status: BackendStatus | null = null;
  let statusError = '';

  /** Human-readable description of cron expression (e.g. "5 * * * *" → "Every hour at :05"). */
  function formatCronFrequency(cron: string): string {
    const s = (cron || '').trim();
    if (!s) return 'Not set';
    const parts = s.split(/\s+/);
    if (parts.length < 5) return s;
    const [min, hour, day, month, dow] = parts;
    const minNum = min === '*' ? null : parseInt(min, 10);
    const hourNum = hour === '*' ? null : parseInt(hour, 10);
    const isNum = (x: string) => /^\d+$/.test(x);
    const step = (x: string) => (x.includes('/') ? parseInt(x.split('/')[1], 10) : 1);

    if (min === '*' && hour === '*' && day === '*' && month === '*' && dow === '*') return 'Every minute';
    if (hour === '*' && day === '*' && month === '*' && dow === '*') {
      if (isNum(min)) return `Every hour at :${min.padStart(2, '0')}`;
      if (min.startsWith('*/')) return `Every ${step(min)} minute(s)`;
      return s;
    }
    if (day === '*' && month === '*' && dow === '*') {
      if (hour.startsWith('*/') && min === '0') return `Every ${step(hour)} hour(s)`;
      if (isNum(hour) && isNum(min)) return `Daily at ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`;
      return s;
    }
    if (month === '*' && dow === '*') {
      if (isNum(day) && isNum(hour) && isNum(min))
        return `Monthly on day ${day} at ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`;
      return s;
    }
    return s;
  }

  async function loadScheduleStatus() {
    statusError = '';
    try {
      status = await getBackendStatus();
    } catch (e) {
      status = null;
      statusError = e instanceof Error ? e.message : 'Failed to load schedule';
    }
  }

  async function start() {
    starting = true;
    try {
      const r = await schedulerStart();
      if (r.ok) {
        await loadStatus();
        await loadScheduleStatus();
        onToast(r.message || 'Schedule started.');
      } else {
        onToast(r.error || 'Failed', 'error');
      }
    } catch (e) {
      onToast((e instanceof Error ? e.message : 'Failed to start schedule.'), 'error');
    } finally {
      starting = false;
    }
  }

  async function stop() {
    stopping = true;
    try {
      const r = await schedulerStop();
      if (r.ok) {
        await loadStatus();
        await loadScheduleStatus();
        onToast('Schedule stopped.');
      } else {
        onToast(r.error || 'Failed', 'error');
      }
    } catch (e) {
      onToast((e instanceof Error ? e.message : 'Failed to stop schedule.'), 'error');
    } finally {
      stopping = false;
    }
  }

  onMount(() => {
    loadScheduleStatus();
  });
</script>

<div class="card">
  <div class="card-header text-dark">Test schedule</div>
  <div class="card-body">
    {#if statusError}
      <p class="text-warning small mb-3">{statusError}</p>
    {:else if status}
      <dl class="row mb-3 small">
        <dt class="col-sm-3 text-muted">Status</dt>
        <dd class="col-sm-9">
          <span class="badge {status.scheduled ? 'bg-success' : 'bg-secondary'}">{status.scheduled ? 'Running' : 'Stopped'}</span>
        </dd>
        <dt class="col-sm-3 text-muted">Frequency</dt>
        <dd class="col-sm-9">{formatCronFrequency(status.cron_schedule)}</dd>
        <dt class="col-sm-3 text-muted">Cron expression</dt>
        <dd class="col-sm-9"><code class="small">{status.cron_schedule || '—'}</code></dd>
        {#if status.cron_line}
          <dt class="col-sm-3 text-muted">Current cron line</dt>
          <dd class="col-sm-9"><code class="small text-break">{status.cron_line}</code></dd>
        {/if}
      </dl>
      <p class="text-muted small mb-3">Results: <code class="small">/var/log/netperf/YYYYMMDD</code></p>
    {:else}
      <p class="text-muted small mb-3">Loading schedule…</p>
    {/if}
    <div class="d-flex flex-wrap gap-2">
      <button type="button" class="btn btn-success" on:click={start} disabled={starting}>
        <i class="bi bi-play-fill me-1"></i> {starting ? 'Starting…' : 'Start schedule'}
      </button>
      <button type="button" class="btn btn-outline-secondary" on:click={stop} disabled={stopping}>
        <i class="bi bi-stop-fill me-1"></i> {stopping ? 'Stopping…' : 'Stop schedule'}
      </button>
      {#if status}
        <button type="button" class="btn btn-outline-secondary btn-sm" on:click={loadScheduleStatus} disabled={!status}>
          <i class="bi bi-arrow-clockwise me-1"></i> Refresh
        </button>
      {/if}
    </div>
  </div>
</div>

<style>
  :global(.card) { border-radius: var(--radius-lg); }
  :global(.card-header) { font-weight: var(--font-weight-semibold); }
</style>
