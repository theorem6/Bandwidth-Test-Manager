<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { getDiagnostics } from './lib/api';
  import type { DiagnosticCheck, DiagnosticLogLine } from './lib/api';

  export let onToast: (msg: string, type?: 'success' | 'error') => void = () => {};

  let checks: DiagnosticCheck[] = [];
  let logs: DiagnosticLogLine[] = [];
  let logFile = '';
  let healthIntervalMin = 5;
  let loading = true;
  let error = '';
  let pollId: ReturnType<typeof setInterval> | null = null;

  async function load() {
    error = '';
    try {
      const r = await getDiagnostics(600);
      checks = r.checks || [];
      logs = r.logs || [];
      logFile = r.log_file || '';
      healthIntervalMin = r.health_interval_minutes ?? 5;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load diagnostics';
      onToast(error, 'error');
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    void load();
    pollId = setInterval(() => void load(), 20000);
  });

  onDestroy(() => {
    if (pollId != null) clearInterval(pollId);
  });

  function levelClass(level: string): string {
    const u = (level || '').toUpperCase();
    if (u === 'ERROR' || u === 'CRITICAL') return 'text-danger';
    if (u === 'WARNING') return 'text-warning';
    if (u === 'INFO') return 'text-info';
    return 'text-muted';
  }

  function checkLabel(name: string): string {
    const m: Record<string, string> = {
      config_file_exists: 'Config file',
      storage_dir_exists: 'Storage directory',
      storage_writable: 'Storage writable',
      script_netperf_tester: 'Script netperf-tester',
      script_netperf_cron_run: 'Script netperf-cron-run',
      ookla_speedtest_cli: 'Ookla speedtest CLI',
      database_file: 'SQLite database',
      cron_netperf_job: 'Cron netperf job',
    };
    return m[name] || name.replace(/_/g, ' ');
  }
</script>

<div class="logs-page">
  <p class="text-muted small mb-3">
    Health checks run about every <strong>{healthIntervalMin}</strong> minutes and on each refresh. Failures are logged below and in
    <code class="small">{logFile || '…/app-events.log'}</code> on the server (rotating files).
  </p>

  {#if loading && checks.length === 0}
    <p class="text-muted">Loading…</p>
  {:else if error && checks.length === 0}
    <p class="text-danger">{error}</p>
  {/if}

  <div class="card mb-4">
    <div class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
      <span>System checks</span>
      <button type="button" class="btn btn-sm btn-outline-primary" on:click={() => void load()} disabled={loading}>
        Refresh now
      </button>
    </div>
    <div class="card-body py-2">
      <ul class="list-group list-group-flush small mb-0">
        {#each checks as c}
          <li class="list-group-item d-flex flex-wrap align-items-start gap-2 px-0">
            <span class="badge {c.ok ? 'bg-success' : 'bg-danger'}">{c.ok ? 'OK' : 'FAIL'}</span>
            <span class="fw-medium">{checkLabel(c.name)}</span>
            {#if c.detail}
              <span class="text-muted font-monospace" style="font-size:0.8rem">{c.detail}</span>
            {/if}
          </li>
        {/each}
      </ul>
    </div>
  </div>

  <div class="card">
    <div class="card-header">Recent log lines (newest last)</div>
    <div class="card-body p-0">
      <div class="log-scroll font-monospace small p-3 mb-0">
        {#if logs.length === 0}
          <p class="text-muted mb-0">No log lines yet.</p>
        {:else}
          {#each logs as line}
            <div class="log-line mb-1">
              <span class="text-muted">{line.ts}</span>
              <span class={levelClass(line.level)}> [{line.level}]</span>
              <span class="log-msg">{line.message}</span>
            </div>
          {/each}
        {/if}
      </div>
    </div>
  </div>
</div>

<style>
  .log-scroll {
    max-height: min(70vh, 520px);
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-word;
    background: var(--bs-tertiary-bg, #f8f9fa);
    border-radius: 0 0 0.375rem 0.375rem;
  }
  .log-line .log-msg {
    color: var(--bs-body-color);
  }
</style>
