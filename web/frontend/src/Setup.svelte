<script lang="ts">
  import { onMount } from 'svelte';
  import { getBackendStatus, installDeps, clearOldData, clearIperfData, getTimezone, getTimezones, setTimezone, ntpInstall } from './lib/api';
  import type { BackendStatus } from './lib/api';

  export let onToast: (msg: string, type?: 'success' | 'error') => void;

  let status: BackendStatus | null = null;
  let loading = true;
  let installing = false;
  let clearing = false;
  let clearingIperf = false;
  let error = '';
  let timezoneInfo: { timezone: string; local_time_iso: string; ntp_active: boolean } | null = null;
  let timezones: string[] = [];
  let selectedTimezone = '';
  let timezoneLoading = false;
  let settingTimezone = false;
  let installingNtp = false;

  async function load() {
    loading = true;
    error = '';
    try {
      status = await getBackendStatus();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load status';
      status = null;
    }
    try {
      timezoneInfo = await getTimezone();
      if (timezoneInfo?.timezone && !selectedTimezone) selectedTimezone = timezoneInfo.timezone;
    } catch {
      timezoneInfo = null;
    } finally {
      loading = false;
    }
  }

  async function loadTimezones() {
    timezoneLoading = true;
    try {
      const r = await getTimezones();
      timezones = r.timezones || [];
      if (timezoneInfo?.timezone && !selectedTimezone) selectedTimezone = timezoneInfo.timezone;
    } catch {
      timezones = [];
    } finally {
      timezoneLoading = false;
    }
  }

  async function runSetTimezone() {
    if (!selectedTimezone.trim()) {
      onToast('Select a timezone.', 'error');
      return;
    }
    settingTimezone = true;
    try {
      const r = await setTimezone(selectedTimezone.trim());
      if (r.ok) {
        onToast(r.message || 'Timezone set.');
        await load();
      } else {
        onToast(r.error || 'Failed to set timezone', 'error');
      }
    } catch (e) {
      onToast(e instanceof Error ? e.message : 'Failed', 'error');
    } finally {
      settingTimezone = false;
    }
  }

  async function runNtpInstall() {
    installingNtp = true;
    try {
      const r = await ntpInstall();
      if (r.ok) {
        onToast(r.message || 'NTP install/sync done.');
        await load();
      } else {
        onToast(r.error || 'NTP install failed', 'error');
      }
    } catch (e) {
      onToast(e instanceof Error ? e.message : 'Failed', 'error');
    } finally {
      installingNtp = false;
    }
  }

  function formatLocalTime(iso: string): string {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
    } catch {
      return iso;
    }
  }

  async function runInstall() {
    installing = true;
    error = '';
    try {
      const r = await installDeps();
      if (r.ok) {
        onToast(r.message || 'Dependencies installed. You can start the scheduler.');
        await load();
      } else {
        error = r.error || 'Install failed';
        onToast(error, 'error');
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Request failed';
      error = msg;
      onToast(msg, 'error');
    } finally {
      installing = false;
    }
  }

  async function runClearOld() {
    clearing = true;
    try {
      const r = await clearOldData(30);
      if (r.ok) {
        onToast(r.message || `Cleared ${r.deleted ?? 0} old day(s).`);
        await load();
      } else {
        onToast(r.error || 'Clear failed', 'error');
      }
    } catch (e) {
      onToast(e instanceof Error ? e.message : 'Clear failed', 'error');
    } finally {
      clearing = false;
    }
  }

  async function runClearIperf() {
    clearingIperf = true;
    try {
      const r = await clearIperfData();
      if (r.ok) {
        onToast(r.message || `Removed ${r.deleted ?? 0} iperf file(s).`);
        await load();
      } else {
        onToast(r.error || 'Clear failed', 'error');
      }
    } catch (e) {
      onToast(e instanceof Error ? e.message : 'Clear failed', 'error');
    } finally {
      clearingIperf = false;
    }
  }

  onMount(() => {
    load();
    loadTimezones();
  });
</script>

<div class="card mb-4">
  <div class="card-header text-dark">Install software on server</div>
  <div class="card-body">
    <p class="text-muted small mb-4">
      Install <strong>Ookla Speedtest CLI</strong>, <strong>iperf3</strong>, jq, mtr, and netperf scripts on this server. After install, configure which servers and tests to run from <strong>Settings</strong> (Ookla servers, iperf3 servers, and test profiles). The web service must run as root for install. Use <strong>Scheduler</strong> to start or stop the hourly test cron.
    </p>
    {#if loading}
      <p class="text-muted">Loading status…</p>
    {:else if error}
      <div class="alert alert-danger small">{error}</div>
    {:else if status}
      <ul class="list-unstyled mb-4">
        <li class="mb-2">
          <span class="badge {status.speedtest_installed ? 'bg-success' : 'bg-secondary'} me-2">Ookla Speedtest</span>
          {status.speedtest_installed ? 'Installed' : 'Not installed'}
        </li>
        <li class="mb-2">
          <span class="badge {status.iperf3_installed ? 'bg-success' : 'bg-secondary'} me-2">iperf3</span>
          {status.iperf3_installed ? 'Installed' : 'Not installed'}
        </li>
        <li class="mb-2">
          <span class="badge {status.jq_installed ? 'bg-success' : 'bg-secondary'} me-2">jq</span>
          {status.jq_installed ? 'Installed' : 'Not installed'}
        </li>
        <li class="mb-2">
          <span class="badge {status.config_exists ? 'bg-success' : 'bg-secondary'} me-2">Config</span>
          {status.config_exists ? status.config_path : 'Missing'}
        </li>
        <li class="mb-2">
          <span class="badge {status.scheduled ? 'bg-success' : 'bg-secondary'} me-2">Cron</span>
          {#if status.scheduled}
            {status.cron_schedule} {#if status.cron_line}<code class="small ms-1">{status.cron_line}</code>{/if}
          {:else}
            Not scheduled
          {/if}
        </li>
        <li class="mb-2">
          <span class="badge bg-info me-2">Ookla servers</span>
          {status.ookla_servers_count ?? 0} in config — add more in <strong>Settings</strong> to run multiple speedtests per cron run.
        </li>
        <li class="mb-2">
          <span class="badge {status.storage_exists ? 'bg-success' : 'bg-secondary'} me-2">Log dir</span>
          {status.storage_path}
        </li>
      </ul>
      <div class="d-flex flex-wrap gap-2 align-items-center">
        <button
          type="button"
          class="btn btn-primary"
          on:click={runInstall}
          disabled={installing}
        >
          {#if installing}
            <span class="spinner-border spinner-border-sm me-1" role="status"></span>
            Installing… (may take 2–5 min)
          {:else}
            <i class="bi bi-download me-1"></i> Install / fix dependencies
          {/if}
        </button>
        <button type="button" class="btn btn-outline-secondary btn-sm" on:click={load} disabled={loading}>
          Refresh status
        </button>
        <button
          type="button"
          class="btn btn-outline-warning btn-sm"
          on:click={runClearOld}
          disabled={clearing}
          title="Delete log folders older than 30 days"
        >
          {#if clearing}
            <span class="spinner-border spinner-border-sm me-1" role="status"></span>
          {/if}
          Clear old data (keep 30 days)
        </button>
        <button
          type="button"
          class="btn btn-outline-danger btn-sm"
          on:click={runClearIperf}
          disabled={clearingIperf}
          title="Remove all iperf3 logs; next cron or Run test now will create fresh data"
        >
          {#if clearingIperf}
            <span class="spinner-border spinner-border-sm me-1" role="status"></span>
          {/if}
          Clear iperf data (start fresh)
        </button>
      </div>
      <p class="form-text text-muted small mt-2 mb-0">
        Installs on this server: Ookla repo, speedtest, iperf3, mtr, jq. Copies netperf scripts to <code>/bin</code> and creates <code>/etc/netperf</code>, <code>/var/log/netperf</code>. The first run can take 2–5 minutes (apt update + install). All configuration is in <strong>Settings</strong>.
      </p>
    {/if}
  </div>
</div>

<div class="card mb-4">
  <div class="card-header text-dark">Time & NTP</div>
  <div class="card-body">
    <p class="text-muted small mb-4">
      Set the server timezone and install NTP so test timestamps (e.g. iperf3, Speedtest) are correct. After changing timezone or syncing time, run a test to see updated times.
    </p>
    {#if timezoneInfo}
      <ul class="list-unstyled mb-4">
        <li class="mb-2">
          <span class="badge bg-secondary me-2">Timezone</span>
          {timezoneInfo.timezone || '—'}
        </li>
        <li class="mb-2">
          <span class="badge bg-secondary me-2">Server time</span>
          {formatLocalTime(timezoneInfo.local_time_iso)}
        </li>
        <li class="mb-2">
          <span class="badge {timezoneInfo.ntp_active ? 'bg-success' : 'bg-warning text-dark'} me-2">NTP</span>
          {timezoneInfo.ntp_active ? 'Synced' : 'Not synced — install NTP below'}
        </li>
      </ul>
    {/if}
    <div class="d-flex flex-wrap align-items-end gap-2 mb-3">
      <div class="flex-grow-1" style="min-width: 200px;">
        <label for="setup-timezone" class="form-label small mb-1">Set timezone</label>
        <select
          id="setup-timezone"
          class="form-select form-select-sm"
          bind:value={selectedTimezone}
          disabled={timezoneLoading}
          on:focus={loadTimezones}
        >
          {#if timezoneLoading && timezones.length === 0}
            <option value="">Loading…</option>
          {:else}
            <option value="">Select timezone…</option>
            {#each timezones as tz}
              <option value={tz}>{tz}</option>
            {/each}
          {/if}
        </select>
      </div>
      <button
        type="button"
        class="btn btn-outline-primary btn-sm"
        on:click={runSetTimezone}
        disabled={settingTimezone || !selectedTimezone}
      >
        {#if settingTimezone}
          <span class="spinner-border spinner-border-sm me-1" role="status"></span>
        {/if}
        Set timezone
      </button>
    </div>
    <div>
      <button
        type="button"
        class="btn btn-outline-secondary btn-sm"
        on:click={runNtpInstall}
        disabled={installingNtp}
        title="Install NTP (ntp or chrony) and enable time sync"
      >
        {#if installingNtp}
          <span class="spinner-border spinner-border-sm me-1" role="status"></span>
          Installing / syncing…
        {:else}
          <i class="bi bi-clock me-1"></i>
          Install NTP & sync time
        {/if}
      </button>
    </div>
  </div>
</div>

<style>
  :global(.card) { border: none; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.08); }
  :global(.card-header) { background: #fff; border-bottom: 1px solid #eee; font-weight: 600; padding: 0.75rem 1rem; }
</style>
