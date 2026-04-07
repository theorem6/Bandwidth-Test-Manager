<script lang="ts">
  import { onMount } from 'svelte';
  import { getBackendStatus, schedulerStart, schedulerStop } from './lib/api';
  import type { BackendStatus } from './lib/api';
  import { describeCronSchedule } from './lib/schedule';

  export let loadStatus: () => Promise<void>;
  export let onToast: (msg: string, type?: 'success' | 'error') => void;

  let starting = false;
  let stopping = false;
  let status: BackendStatus | null = null;
  let statusError = '';

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
        <dd class="col-sm-9">{describeCronSchedule(status.cron_schedule)}</dd>
        <dt class="col-sm-3 text-muted">Cron (internal)</dt>
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
