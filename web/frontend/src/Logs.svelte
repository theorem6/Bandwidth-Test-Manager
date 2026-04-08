<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { getDiagnostics } from './lib/api';
  import type { DiagnosticCheck, DiagnosticLogLine, LogStreamId } from './lib/api';

  export let onToast: (msg: string, type?: 'success' | 'error') => void = () => {};

  const STORAGE_KEY = 'bwm_log_sources';
  const ALL_SOURCES: LogStreamId[] = ['app_buffer', 'app_events', 'run_now', 'speedtest_stderr'];

  const SOURCE_LABELS: Record<LogStreamId, string> = {
    app_buffer: 'App buffer (live)',
    app_events: 'app-events.log',
    run_now: 'run-now-last.log',
    speedtest_stderr: 'speedtest.stderr (latest day)',
  };

  let checks: DiagnosticCheck[] = [];
  let merged: Array<DiagnosticLogLine & { source: LogStreamId }> = [];
  let logFile = '';
  let healthIntervalMin = 5;
  let loading = true;
  let error = '';
  let pollId: ReturnType<typeof setInterval> | null = null;

  let enabled: Record<LogStreamId, boolean> = {
    app_buffer: true,
    app_events: true,
    run_now: true,
    speedtest_stderr: true,
  };

  function loadEnabledFromStorage(): void {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const o = JSON.parse(raw) as Record<string, boolean>;
      for (const id of ALL_SOURCES) {
        if (typeof o[id] === 'boolean') enabled[id] = o[id];
      }
    } catch {
      /* ignore */
    }
  }

  function persistEnabled(): void {
    try {
      const o: Record<string, boolean> = {};
      for (const id of ALL_SOURCES) o[id] = enabled[id];
      localStorage.setItem(STORAGE_KEY, JSON.stringify(o));
    } catch {
      /* ignore */
    }
  }

  function selectedSources(): LogStreamId[] {
    return ALL_SOURCES.filter((id) => enabled[id]);
  }

  async function load() {
    error = '';
    const src = selectedSources();
    if (src.length === 0) {
      merged = [];
      loading = false;
      return;
    }
    try {
      const r = await getDiagnostics(600, src);
      checks = r.checks || [];
      merged = (r.merged || []) as Array<DiagnosticLogLine & { source: LogStreamId }>;
      logFile = r.log_file || '';
      healthIntervalMin = r.health_interval_minutes ?? 5;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load diagnostics';
      onToast(error, 'error');
    } finally {
      loading = false;
    }
  }

  function setSource(id: LogStreamId, on: boolean): void {
    enabled = { ...enabled, [id]: on };
    persistEnabled();
    void load();
  }

  function onSourceChange(sid: LogStreamId, e: Event): void {
    const el = e.currentTarget as HTMLInputElement;
    setSource(sid, el.checked);
  }

  onMount(() => {
    loadEnabledFromStorage();
    void load();
    pollId = setInterval(() => void load(), 20000);
  });

  onDestroy(() => {
    if (pollId != null) clearInterval(pollId);
  });

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
    <div class="card-header d-flex flex-wrap align-items-center gap-3 justify-content-between">
      <span>Log output</span>
      <div class="d-flex flex-wrap gap-3 align-items-center small log-source-toggles">
        {#each ALL_SOURCES as sid}
          <label class="d-flex align-items-center gap-1 mb-0">
            <input type="checkbox" checked={enabled[sid]} on:change={(e) => onSourceChange(sid, e)} />
            <span>{SOURCE_LABELS[sid]}</span>
          </label>
        {/each}
      </div>
    </div>
    <div class="card-body p-0">
      <div class="bwm-log-plain font-monospace small" aria-label="Parsed log lines">
        {#if selectedSources().length === 0}
          <p class="bwm-log-plain__empty">Enable at least one log source.</p>
        {:else if loading && merged.length === 0}
          <p class="bwm-log-plain__empty">Loading…</p>
        {:else if merged.length === 0}
          <p class="bwm-log-plain__empty">No log lines for the selected sources.</p>
        {:else}
          {#each merged as line}
            <div class="bwm-log-plain__line">
              <span class="bwm-log-plain__src">[{line.source}]</span>
              {#if line.ts}
                <span class="bwm-log-plain__ts">{line.ts}</span>
              {/if}
              <span class="bwm-log-plain__lvl">{line.level}</span>
              <span class="bwm-log-plain__msg">{line.message}</span>
            </div>
          {/each}
        {/if}
      </div>
    </div>
  </div>
</div>

<style>
  /* Isolated from app theme: black on white only for the log body */
  .bwm-log-plain {
    max-height: min(70vh, 520px);
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-word;
    background: #fff !important;
    color: #000 !important;
    border-radius: 0 0 0.375rem 0.375rem;
    padding: 0.75rem 1rem;
    margin: 0;
  }
  .bwm-log-plain__empty {
    margin: 0;
    color: #000 !important;
    background: transparent !important;
  }
  .bwm-log-plain__line {
    margin-bottom: 0.35rem;
    color: #000 !important;
    background: transparent !important;
  }
  .bwm-log-plain__src {
    color: #000 !important;
    font-weight: 600;
    margin-right: 0.35rem;
  }
  .bwm-log-plain__ts {
    color: #000 !important;
    margin-right: 0.35rem;
  }
  .bwm-log-plain__lvl {
    color: #000 !important;
    margin-right: 0.35rem;
  }
  .bwm-log-plain__msg {
    color: #000 !important;
  }
</style>
