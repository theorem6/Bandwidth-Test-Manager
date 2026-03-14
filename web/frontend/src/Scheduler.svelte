<script lang="ts">
  import { schedulerStart, schedulerStop } from './lib/api';

  export let loadStatus: () => Promise<void>;
  export let onToast: (msg: string, type?: 'success' | 'error') => void;

  let starting = false;
  let stopping = false;

  async function start() {
    starting = true;
    try {
      const r = await schedulerStart();
      if (r.ok) {
        await loadStatus();
        onToast(r.message || 'Schedule started. Tests will run at :05 every hour.');
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
</script>

<div class="card">
  <div class="card-header text-dark">Hourly test schedule</div>
  <div class="card-body">
    <p class="text-muted small">Tests run at minute 5 of every hour. Results: <code class="small">/var/log/netperf/YYYYMMDD</code></p>
    <div class="mb-3">
      <span class="text-muted me-2">Status:</span>
      <strong>See navbar</strong>
    </div>
    <div class="d-flex flex-wrap gap-2">
      <button type="button" class="btn btn-success" on:click={start} disabled={starting}>
        <i class="bi bi-play-fill me-1"></i> {starting ? 'Starting…' : 'Start schedule'}
      </button>
      <button type="button" class="btn btn-outline-secondary" on:click={stop} disabled={stopping}>
        <i class="bi bi-stop-fill me-1"></i> {stopping ? 'Stopping…' : 'Stop schedule'}
      </button>
    </div>
  </div>
</div>

<style>
  :global(.card) { border: none; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.08); }
  :global(.card-header) { background: #fff; border-bottom: 1px solid #eee; font-weight: 600; padding: 0.75rem 1rem; }
</style>
