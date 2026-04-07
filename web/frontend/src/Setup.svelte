<script lang="ts">
  import { onMount } from 'svelte';
  import {
    getBackendStatus,
    installDeps,
    clearOldData,
    clearIperfData,
    getTimezone,
    getTimezones,
    setTimezone,
    ntpInstall,
    getAlerts,
    getUsers,
    setPassword,
    getConfig,
    putConfig,
    uploadBrandLogo,
  } from './lib/api';
  import type { BackendStatus, AlertItem, UserItem, Branding } from './lib/api';
  import { loadBranding } from './lib/branding';

  export let onToast: (msg: string, type?: 'success' | 'error') => void;

  function str(v: unknown): string {
    return v == null ? '' : String(v);
  }

  /** Branding fields applied from Setup (merged in config; full theme still in Settings). */
  let setupBrandTitle = '';
  let setupBrandTagline = '';
  let setupBrandLogoUrl = '';
  let setupBrandLogoAlt = '';
  let setupBrandPrimary = '';
  let setupBrandLogoBusy = false;
  let savingBrand = false;

  /** Only fields edited on Setup — merged with existing branding so Settings theme/CSS are preserved. */
  function setupBrandingPayload(): Partial<Branding> {
    return {
      app_title: str(setupBrandTitle).trim(),
      tagline: str(setupBrandTagline).trim(),
      logo_url: str(setupBrandLogoUrl).trim(),
      logo_alt: str(setupBrandLogoAlt).trim(),
      primary_color: str(setupBrandPrimary).trim(),
    };
  }

  function fillSetupBranding(b: Branding | undefined) {
    const x = b || {};
    setupBrandTitle = str(x.app_title);
    setupBrandTagline = str(x.tagline);
    setupBrandLogoUrl = str(x.logo_url);
    setupBrandLogoAlt = str(x.logo_alt);
    setupBrandPrimary = str(x.primary_color);
  }

  async function persistSetupBranding(): Promise<boolean> {
    try {
      await putConfig({ branding: setupBrandingPayload() as Branding });
      await loadBranding();
      return true;
    } catch (e) {
      onToast(e instanceof Error ? e.message : 'Could not save site branding', 'error');
      return false;
    }
  }

  async function onSetupBrandLogoFile(ev: Event) {
    const input = ev.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    setupBrandLogoBusy = true;
    try {
      const r = await uploadBrandLogo(file);
      if (r.ok && r.logo_url) {
        setupBrandLogoUrl = r.logo_url;
        onToast('Logo uploaded.', 'success');
        await loadBranding();
      } else {
        onToast(r.error || 'Logo upload failed.', 'error');
      }
    } finally {
      setupBrandLogoBusy = false;
      input.value = '';
    }
  }

  async function runSaveBranding() {
    savingBrand = true;
    try {
      if (await persistSetupBranding()) {
        onToast('Site branding saved.');
      }
    } finally {
      savingBrand = false;
    }
  }

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
  let alerts: AlertItem[] = [];
  let alertsLoading = false;
  let users: UserItem[] = [];
  let usersLoading = false;
  let usersError = '';
  let setPasswordUsername = '';
  let setPasswordPassword = '';
  let setPasswordRole = 'admin';
  let setPasswordLoading = false;
  let setPasswordMessage = '';

  async function loadAlerts() {
    alertsLoading = true;
    try {
      const r = await getAlerts(10);
      alerts = r.alerts || [];
    } catch {
      alerts = [];
    } finally {
      alertsLoading = false;
    }
  }

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
      const cfg = await getConfig();
      fillSetupBranding(cfg.branding);
    } catch {
      /* not logged in or config unavailable */
    }
    try {
      timezoneInfo = await getTimezone();
      if (timezoneInfo?.timezone && !selectedTimezone) selectedTimezone = timezoneInfo.timezone;
    } catch {
      timezoneInfo = null;
    }
    loadAlerts();
    loading = false;
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
      if (!(await persistSetupBranding())) {
        return;
      }
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
      const r = await clearOldData();
      if (r.ok) {
        onToast(r.message || `Purged ${r.deleted_dirs ?? 0} dir(s), ${(r.deleted_speedtest_rows ?? 0) + (r.deleted_iperf_rows ?? 0)} DB rows.`);
        await load();
      } else {
        onToast(r.error || 'Purge failed', 'error');
      }
    } catch (e) {
      onToast(e instanceof Error ? e.message : 'Purge failed', 'error');
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

  async function loadUsers() {
    usersLoading = true;
    usersError = '';
    try {
      const r = await getUsers();
      users = r.users || [];
    } catch (e) {
      users = [];
      usersError = e instanceof Error ? e.message : 'Failed to load (admin only)';
    } finally {
      usersLoading = false;
    }
  }

  async function runSetPassword() {
    if (!setPasswordUsername.trim()) {
      onToast('Enter username.', 'error');
      return;
    }
    if (!setPasswordPassword) {
      onToast('Enter password.', 'error');
      return;
    }
    setPasswordLoading = true;
    setPasswordMessage = '';
    try {
      const r = await setPassword(setPasswordUsername.trim(), setPasswordPassword, setPasswordRole);
      if (r.ok) {
        setPasswordMessage = r.message || 'Saved.';
        setPasswordPassword = '';
        onToast(setPasswordMessage);
        loadUsers();
      } else {
        setPasswordMessage = r.error || 'Failed';
        onToast(setPasswordMessage, 'error');
      }
    } catch (e) {
      setPasswordMessage = e instanceof Error ? e.message : 'Failed';
      onToast(setPasswordMessage, 'error');
    } finally {
      setPasswordLoading = false;
    }
  }

  onMount(() => {
    load();
    loadTimezones();
    loadUsers();
  });
</script>

<div class="card mb-4">
  <div class="card-header text-dark">Install software on server</div>
  <div class="card-body">
    <p class="text-muted small mb-4">
      Install <strong>Ookla Speedtest CLI</strong>, <strong>iperf3</strong>, jq, mtr, and netperf scripts on this server. After install, configure which servers and tests to run from <strong>Settings</strong> (Ookla servers, iperf3 servers, and test profiles). The web service must run as root for install. Use <strong>Scheduler</strong> to start or stop the hourly test cron.
    </p>

    <div class="border rounded p-3 mb-4 setup-branding">
      <h6 class="text-dark mb-2"><i class="bi bi-palette me-1"></i> Site branding (optional)</h6>
      <p class="small text-muted mb-3">
        Set the name, tagline, logo, and accent color for this install. Values are saved when you run <strong>Install / fix dependencies</strong>, or use <strong>Save branding</strong> to apply without reinstalling packages. Advanced colors and custom CSS remain under <strong>Settings</strong> → Appearance.
      </p>
      <div class="row g-2 align-items-end">
        <div class="col-12 col-md-6">
          <label class="form-label small mb-0" for="setup-brand-title">App title</label>
          <input
            id="setup-brand-title"
            type="text"
            class="form-control form-control-sm"
            bind:value={setupBrandTitle}
            placeholder="Shown in the navbar"
            disabled={loading}
            autocomplete="organization"
          />
        </div>
        <div class="col-12 col-md-6">
          <label class="form-label small mb-0" for="setup-brand-tagline">Tagline</label>
          <input
            id="setup-brand-tagline"
            type="text"
            class="form-control form-control-sm"
            bind:value={setupBrandTagline}
            placeholder="e.g. company.com"
            disabled={loading}
          />
        </div>
        <div class="col-12 col-md-6">
          <label class="form-label small mb-0" for="setup-brand-logo-alt">Logo alt text</label>
          <input
            id="setup-brand-logo-alt"
            type="text"
            class="form-control form-control-sm"
            bind:value={setupBrandLogoAlt}
            placeholder="Accessibility description"
            disabled={loading}
          />
        </div>
        <div class="col-12 col-md-6">
          <label class="form-label small mb-0" for="setup-brand-primary">Primary color (hex)</label>
          <input
            id="setup-brand-primary"
            type="text"
            class="form-control form-control-sm font-monospace"
            bind:value={setupBrandPrimary}
            placeholder="#00d9ff"
            disabled={loading}
          />
        </div>
        <div class="col-12">
          <label class="form-label small mb-0" for="setup-brand-logo-url">Logo URL</label>
          <input
            id="setup-brand-logo-url"
            type="text"
            class="form-control form-control-sm font-monospace mb-1"
            bind:value={setupBrandLogoUrl}
            placeholder="/netperf/static/uploads/brand-logo.png or https://…"
            disabled={loading}
          />
          <div class="d-flex flex-wrap align-items-center gap-2">
            <input
              id="setup-brand-logo-file"
              type="file"
              class="form-control form-control-sm"
              style="max-width: 220px"
              accept=".png,.jpg,.jpeg,.svg,.webp,.gif,.ico,image/*"
              on:change={onSetupBrandLogoFile}
              disabled={loading || setupBrandLogoBusy}
            />
            <span class="small text-muted">{setupBrandLogoBusy ? 'Uploading…' : 'Upload stores the file under static/uploads/'}</span>
          </div>
        </div>
      </div>
      <div class="mt-3">
        <button
          type="button"
          class="btn btn-outline-secondary btn-sm"
          on:click={runSaveBranding}
          disabled={loading || savingBrand || installing}
        >
          {#if savingBrand}
            <span class="spinner-border spinner-border-sm me-1" role="status"></span>
          {:else}
            <i class="bi bi-check2 me-1"></i>
          {/if}
          Save branding
        </button>
      </div>
    </div>

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
          title="Purge log dirs and DB rows older than retention_days (Settings). Default 30 if not set."
        >
          {#if clearing}
            <span class="spinner-border spinner-border-sm me-1" role="status"></span>
          {/if}
          Purge old data (retention policy)
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
  <div class="card-header text-dark">Users (configurable auth)</div>
  <div class="card-body">
    <p class="text-muted small mb-3">
      Add or update users; passwords are stored hashed in config. After adding <strong>auth_users</strong>, built-in users are no longer used.
    </p>
    {#if usersLoading}
      <p class="text-muted small mb-0">Loading…</p>
    {:else if usersError}
      <p class="small text-warning mb-0">{usersError}</p>
    {:else}
      {#if users.length > 0}
        <ul class="list-unstyled small mb-3">
          {#each users as u}
            <li><span class="badge bg-secondary me-1">{u.username}</span> {u.role}</li>
          {/each}
        </ul>
      {:else}
        <p class="text-muted small mb-3">No custom users yet. Set a password below to create config auth_users.</p>
      {/if}
    {/if}
    <form
      class="row g-2 align-items-end mb-2"
      aria-label="Set user password"
      on:submit|preventDefault={runSetPassword}
    >
      <div class="col-auto">
        <label for="setup-user-username" class="form-label small mb-0">Username</label>
        <input id="setup-user-username" type="text" class="form-control form-control-sm" style="width:10rem" bind:value={setPasswordUsername} placeholder="e.g. bwadmin" autocomplete="username" />
      </div>
      <div class="col-auto">
        <label for="setup-user-password" class="form-label small mb-0">Password</label>
        <input id="setup-user-password" type="password" class="form-control form-control-sm" style="width:10rem" bind:value={setPasswordPassword} placeholder="New password" autocomplete="new-password" />
      </div>
      <div class="col-auto">
        <label for="setup-user-role" class="form-label small mb-0">Role</label>
        <select id="setup-user-role" class="form-select form-select-sm" style="width:8rem" bind:value={setPasswordRole}>
          <option value="admin">admin</option>
          <option value="readonly">readonly</option>
        </select>
      </div>
      <div class="col-auto">
        <button type="submit" class="btn btn-outline-primary btn-sm" disabled={setPasswordLoading}>
          {#if setPasswordLoading}…{:else}Set password{/if}
        </button>
      </div>
    </form>
    {#if setPasswordMessage}
      <p class="small mb-0 {setPasswordMessage.includes('Failed') ? 'text-danger' : 'text-success'}">{setPasswordMessage}</p>
    {/if}
  </div>
</div>

<div class="card mb-4">
  <div class="card-header text-dark">Recent SLA alerts</div>
  <div class="card-body">
    <p class="text-muted small mb-3">
      Last SLA violations that triggered a webhook. Configure thresholds and webhook URL in <strong>Settings</strong> → SLA &amp; alerts.
    </p>
    {#if alertsLoading}
      <p class="text-muted small mb-0">Loading…</p>
    {:else if alerts.length === 0}
      <p class="text-muted small mb-0">No alerts recorded yet.</p>
    {:else}
      <ul class="list-unstyled mb-0">
        {#each alerts.slice(0, 10) as alert}
          <li class="small mb-2 pb-2 border-bottom border-light">
            <span class="text-secondary">{new Date(alert.created_at).toLocaleString()}</span>
            {#if alert.probe_id || alert.location_name}
              <span class="ms-1">({[alert.probe_id, alert.location_name].filter(Boolean).join(' — ')})</span>
            {/if}
            {#each alert.violations || [] as v}
              <div class="mt-1"><strong>{v.site}</strong>: {v.violations?.join('; ') ?? ''}</div>
            {/each}
          </li>
        {/each}
      </ul>
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
  :global(.card) { border-radius: var(--radius-lg); }
  :global(.card-header) { font-weight: var(--font-weight-semibold); }
</style>
