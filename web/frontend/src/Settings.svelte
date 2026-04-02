<script lang="ts">
  import { onMount } from 'svelte';
  import { getConfig, putConfig, getSpeedtestServers, checkSla } from './lib/api';
  import type { Config, OoklaServer, IperfServer, IperfTest, SpeedtestServerOption } from './lib/api';
  import { themeMode, setTheme, type ThemeMode } from './lib/theme';

  const themeOptions: { value: ThemeMode; label: string; icon: string }[] = [
    { value: 'light', label: 'Light', icon: 'bi-sun' },
    { value: 'dark', label: 'Dark', icon: 'bi-moon' },
    { value: 'system', label: 'System', icon: 'bi-circle-half' },
  ];

  export let onToast: (msg: string, type?: 'success' | 'error') => void;

  let siteUrl = '';
  let sslCertPath = '';
  let sslKeyPath = '';
  let limitMbps = '';
  let cronSchedule = '5 * * * *';
  let iperfDurationSeconds = 10;
  let ooklaServers: { id: string; label: string }[] = [];
  let iperfServers: { host: string; label: string }[] = [];
  let iperfTests: { name: string; args: string }[] = [];
  let message = '';
  let messageType: 'success' | 'danger' = 'success';
  let ooklaServerOptions: SpeedtestServerOption[] = [];
  let ooklaOptionsLoading = false;
  let ooklaOptionsError = '';
  let probeId = '';
  let locationName = '';
  let region = '';
  let tier = '';
  let slaMinDownloadMbps = '';
  let slaMinUploadMbps = '';
  let slaMaxLatencyMs = '';
  let webhookUrl = '';
  let webhookSecret = '';
  let checkSlaLoading = false;
  let retentionDays = '';
  let ooklaLocalPatternsText = '';
  let ooklaLocalAutoIsp = true;

  function ooklaToForm(raw: OoklaServer[]): { id: string; label: string }[] {
    if (!Array.isArray(raw)) return [];
    return raw.map((s) => ({
      id: s.id === 'auto' ? 'auto' : s.id === 'local' ? 'local' : String(s.id),
      label: s.label ?? '',
    }));
  }
  function formToOokla(form: { id: string; label: string }[]): OoklaServer[] {
    return form.map((s) => {
      const idStr = (s.id ?? '').trim().toLowerCase();
      if (idStr === 'auto' || idStr === '') {
        return { id: 'auto', label: (s.label ?? '').trim() || 'Auto' };
      }
      if (idStr === 'local') {
        return { id: 'local', label: (s.label ?? '').trim() || 'Local ISP' };
      }
      const num = parseInt(String(s.id).trim(), 10);
      if (!Number.isNaN(num) && num > 0) {
        return { id: num, label: (s.label ?? '').trim() || 'Server' };
      }
      return { id: 'auto', label: (s.label ?? '').trim() || 'Auto' };
    });
  }
  function parseOoklaPatterns(text: string): string[] {
    return text
      .split(/[\n,]+/)
      .map((p) => p.trim())
      .filter(Boolean);
  }
  function iperfServerToForm(raw: IperfServer[]): { host: string; label: string }[] {
    if (!Array.isArray(raw)) return [];
    return raw.map((s) => ({ host: s.host ?? '', label: s.label ?? '' }));
  }
  function iperfTestToForm(raw: IperfTest[]): { name: string; args: string }[] {
    if (!Array.isArray(raw)) return [];
    return raw.map((t) => ({ name: t.name ?? '', args: t.args ?? '' }));
  }

  async function loadOoklaOptions() {
    ooklaOptionsLoading = true;
    ooklaOptionsError = '';
    try {
      const r = await getSpeedtestServers();
      ooklaServerOptions = r.servers || [];
      if (r.error) ooklaOptionsError = r.error;
    } catch (e) {
      ooklaServerOptions = [];
      ooklaOptionsError = e instanceof Error ? e.message : 'Failed to load server list';
    } finally {
      ooklaOptionsLoading = false;
    }
  }

  /** Public iperf3 servers from https://iperf.fr/iperf-servers.php */
  const IPERF_PRESET_SERVERS: { host: string; label: string; portHint?: string }[] = [
    { host: 'ping.online.net', label: 'Online.net (France, 100 Gbit/s)' },
    { host: 'iperf3.moji.fr', label: 'Moji (France Île-de-France, 100 Gbit/s)' },
    { host: 'speedtest.milkywan.fr', label: 'MilkyWan (France, 40 Gbit/s)', portHint: '-p 9200' },
    { host: 'iperf.par2.as49434.net', label: 'Harmony (France)', portHint: '-p 9200' },
    { host: 'paris.bbr.iperf.bytel.fr', label: 'Bouygues Paris BBR (10 Gbit/s)', portHint: '-p 9200' },
    { host: 'paris.cubic.iperf.bytel.fr', label: 'Bouygues Paris Cubic (10 Gbit/s)', portHint: '-p 9200' },
    { host: 'speedtest.serverius.net', label: 'Serverius (Netherlands, 10 Gbit/s)', portHint: '-p 5002' },
    { host: 'nl.iperf.014.fr', label: '014.fr Netherlands (1 Gbit/s)', portHint: '-p 10415' },
    { host: 'ch.iperf.014.fr', label: '014.fr Switzerland (3 Gbit/s)', portHint: '-p 15315' },
    { host: 'iperf.eenet.ee', label: 'EENet (Estonia)' },
    { host: 'iperf.astra.in.ua', label: 'Astra (Ukraine Lviv, 10 Gbit/s)' },
    { host: 'iperf.volia.net', label: 'Volia (Ukraine Kiev)' },
    { host: 'iperf.angolacables.co.ao', label: 'Angola Cables (Luanda, 10 Gbit/s)', portHint: '-p 9200' },
    { host: 'speedtest.uztelecom.uz', label: 'Uztelecom (Uzbekistan Tashkent, 10 Gbit/s)' },
    { host: 'iperf.biznetnetworks.com', label: 'Biznet (Indonesia)' },
    { host: 'speedtest-iperf-akl.vetta.online', label: 'Vetta (New Zealand Auckland)' },
    { host: 'iperf.he.net', label: 'Hurricane Electric (USA Fremont CA)' },
  ];

  /** Full display name: provider + location (e.g. "Synthesis Health — Council Bluffs, IA") */
  function fullServerName(srv: SpeedtestServerOption): string {
    const parts = [srv.name, srv.location].filter(Boolean).map((s) => String(s).trim());
    return parts.length ? parts.join(' — ') : String(srv.id);
  }

  function onOoklaServerSelect(i: number, value: string) {
    const opt = value === 'auto' || value === 'local' ? null : ooklaServerOptions.find((s) => String(s.id) === value);
    let newLabel = ooklaServers[i]?.label || '';
    if (value === 'auto') {
      newLabel = newLabel || 'Auto';
    } else if (value === 'local') {
      newLabel = newLabel || 'Local ISP';
    } else if (opt) {
      newLabel = fullServerName(opt);
    }
    ooklaServers = ooklaServers.map((row, j) => (j === i ? { id: value, label: newLabel } : row));
  }

  onMount(async () => {
    try {
      const c = await getConfig();
      siteUrl = c.site_url || '';
      sslCertPath = c.ssl_cert_path || '';
      sslKeyPath = c.ssl_key_path || '';
      limitMbps = c.speedtest_limit_mbps != null ? String(c.speedtest_limit_mbps) : '';
      cronSchedule = (c.cron_schedule || '5 * * * *').trim();
      const d = Number(c.iperf_duration_seconds);
      iperfDurationSeconds = (!Number.isNaN(d) && d >= 1 && d <= 300) ? d : 10;
      ooklaServers = ooklaToForm((c.ookla_servers as OoklaServer[]) || []);
      iperfServers = iperfServerToForm((c.iperf_servers as IperfServer[]) || []);
      iperfTests = iperfTestToForm((c.iperf_tests as IperfTest[]) || []);
      if (iperfTests.length === 0) iperfTests = [{ name: 'single', args: '-P 1' }];
      probeId = c.probe_id ?? '';
      locationName = c.location_name ?? '';
      region = c.region ?? '';
      tier = c.tier ?? '';
      const sla = c.sla_thresholds ?? {};
      slaMinDownloadMbps = sla.min_download_mbps != null ? String(sla.min_download_mbps) : '';
      slaMinUploadMbps = sla.min_upload_mbps != null ? String(sla.min_upload_mbps) : '';
      slaMaxLatencyMs = sla.max_latency_ms != null ? String(sla.max_latency_ms) : '';
      webhookUrl = c.webhook_url ?? '';
      webhookSecret = c.webhook_secret ?? '';
      retentionDays = c.retention_days != null ? String(c.retention_days) : '';
      ooklaLocalPatternsText = Array.isArray(c.ookla_local_patterns) ? c.ookla_local_patterns.join('\n') : '';
      ooklaLocalAutoIsp = c.ookla_local_auto_isp !== false;
      loadOoklaOptions();
    } catch {
      message = 'Failed to load config';
      messageType = 'danger';
    }
  });

  function addOokla() {
    ooklaServers = [...ooklaServers, { id: 'local', label: 'Local ISP' }];
  }
  function removeOokla(i: number) {
    ooklaServers = ooklaServers.filter((_, idx) => idx !== i);
  }
  function addIperfServer() {
    iperfServers = [...iperfServers, { host: '', label: '' }];
  }
  function addIperfServerFromPreset(preset: { host: string; label: string; portHint?: string }) {
    iperfServers = [...iperfServers, { host: preset.host, label: preset.label }];
    if (preset.portHint) {
      onToast(`Added ${preset.label}. For this server add an iperf3 test with args: ${preset.portHint}`, 'success');
    }
  }
  let iperfPresetSelectEl: HTMLSelectElement;
  function onIperfPresetSelect() {
    const val = iperfPresetSelectEl?.value;
    if (val !== '') {
      const idx = parseInt(val, 10);
      const preset = IPERF_PRESET_SERVERS[idx];
      if (preset) addIperfServerFromPreset(preset);
      if (iperfPresetSelectEl) iperfPresetSelectEl.value = '';
    }
  }
  function removeIperfServer(i: number) {
    iperfServers = iperfServers.filter((_, idx) => idx !== i);
  }
  function addIperfTest() {
    iperfTests = [...iperfTests, { name: '', args: '-P 1' }];
  }
  function removeIperfTest(i: number) {
    iperfTests = iperfTests.filter((_, idx) => idx !== i);
  }

  /** Coerce to string before trim (inputs can be number from type="number" or bindings). */
  function str(v: unknown): string {
    return typeof v === 'string' ? v : (v != null ? String(v) : '');
  }
  async function save() {
    message = '';
    const limitVal = str(limitMbps).trim();
    const limit = limitVal === '' ? null : parseInt(limitVal, 10);
    if (limitVal !== '' && (isNaN(limit!) || limit! < 1)) {
      message = 'Speed limit must be a positive number or empty.';
      messageType = 'danger';
      return;
    }
    try {
      const duration = Math.max(1, Math.min(300, parseInt(String(iperfDurationSeconds), 10) || 10));
      const slaMinD = str(slaMinDownloadMbps).trim() ? parseInt(String(slaMinDownloadMbps), 10) : null;
      const slaMinU = str(slaMinUploadMbps).trim() ? parseInt(String(slaMinUploadMbps), 10) : null;
      const slaMaxL = str(slaMaxLatencyMs).trim() ? parseInt(String(slaMaxLatencyMs), 10) : null;
      const r = await putConfig({
        site_url: str(siteUrl).trim(),
        ssl_cert_path: str(sslCertPath).trim(),
        ssl_key_path: str(sslKeyPath).trim(),
        speedtest_limit_mbps: limit,
        cron_schedule: str(cronSchedule).trim() || '5 * * * *',
        iperf_duration_seconds: duration,
        ookla_servers: formToOokla(ooklaServers),
        ookla_local_patterns: parseOoklaPatterns(ooklaLocalPatternsText),
        ookla_local_auto_isp: ooklaLocalAutoIsp,
        iperf_servers: iperfServers.map((s) => ({ host: str(s.host).trim() || 'localhost', label: str(s.label).trim() || 'Server' })),
        iperf_tests: iperfTests.map((t) => ({ name: str(t.name || 'test').trim(), args: str(t.args || '').trim() })),
        probe_id: str(probeId).trim(),
        location_name: str(locationName).trim(),
        region: str(region).trim(),
        tier: str(tier).trim(),
        sla_thresholds: { min_download_mbps: slaMinD, min_upload_mbps: slaMinU, max_latency_ms: slaMaxL },
        webhook_url: str(webhookUrl).trim(),
        webhook_secret: str(webhookSecret).trim(),
        retention_days: str(retentionDays).trim() ? parseInt(String(retentionDays), 10) || null : null,
      });
      if (r.ok) {
        message = 'Saved.';
        messageType = 'success';
        onToast('Configuration saved.');
      } else {
        message = r.error || 'Error';
        messageType = 'danger';
      }
    } catch {
      message = 'Request failed.';
      messageType = 'danger';
      onToast('Failed to save configuration.', 'error');
    }
  }

  async function checkSlaNow() {
    checkSlaLoading = true;
    message = '';
    try {
      const r = await checkSla();
      if (r.ok) {
        message = r.message || 'SLA check completed.';
        messageType = 'success';
        onToast('SLA check completed.');
      } else {
        message = r.error || 'SLA check failed.';
        messageType = 'danger';
      }
    } catch (e) {
      message = e instanceof Error ? e.message : 'Request failed.';
      messageType = 'danger';
    } finally {
      checkSlaLoading = false;
    }
  }
</script>

<!-- Appearance: light / dark / system -->
<div class="card mb-4">
  <div class="card-header">Appearance</div>
  <div class="card-body">
    <p class="text-muted small mb-3">Choose how the interface looks. System follows your device’s light/dark preference.</p>
    <div class="d-flex flex-wrap gap-3 align-items-center">
      {#each themeOptions as opt}
        <label class="d-flex align-items-center gap-2 cursor-pointer mb-0">
          <input type="radio" name="theme-mode" value={opt.value} checked={$themeMode === opt.value} on:change={() => setTheme(opt.value)} />
          <i class="bi {opt.icon}"></i>
          <span>{opt.label}</span>
        </label>
      {/each}
    </div>
  </div>
</div>

<div class="card">
  <div class="card-header">Configuration</div>
  <div class="card-body">
    <form on:submit|preventDefault={save} aria-label="Configuration form">
    <p class="text-muted small mb-4">All settings are configured from this page. Use <strong>Setup</strong> to install Ookla and iperf3 on the server, then configure servers and tests here.</p>

    <div class="mb-3">
      <label class="form-label" for="site-url">Site URL (HTTPS)</label>
      <p class="form-text text-muted small">URL only, no port (e.g. https://host.example.com/netperf/).</p>
      <input id="site-url" type="url" class="form-control form-control-sm" bind:value={siteUrl} placeholder="https://hyperionsolutionsgroup.com/netperf/" />
    </div>
    <div class="mb-3">
      <label class="form-label" for="ssl-cert">SSL certificate path</label>
      <input id="ssl-cert" type="text" class="form-control form-control-sm font-monospace" bind:value={sslCertPath} placeholder="/etc/letsencrypt/live/domain/fullchain.pem" />
    </div>
    <div class="mb-3">
      <label class="form-label" for="ssl-key">SSL key path</label>
      <input id="ssl-key" type="text" class="form-control form-control-sm font-monospace" bind:value={sslKeyPath} placeholder="/etc/letsencrypt/live/domain/privkey.pem" />
    </div>
    <div class="mb-3">
      <label class="form-label" for="limit-mbps">Speedtest limit (Mbps)</label>
      <p class="form-text text-muted small">Optional. Leave empty for no limit.</p>
      <input id="limit-mbps" type="number" class="form-control form-control-sm" style="max-width:120px" min="1" bind:value={limitMbps} placeholder="No limit" />
    </div>
    <div class="mb-3">
      <label class="form-label" for="cron">Cron schedule</label>
      <p class="form-text text-muted small">When the scheduler is started, tests run at this time (e.g. <code>5 * * * *</code> = 5 min past every hour).</p>
      <input id="cron" type="text" class="form-control form-control-sm font-monospace" style="max-width:200px" bind:value={cronSchedule} placeholder="5 * * * *" />
    </div>

    <hr class="my-4" />
    <h2 class="h6 mb-3">Probe identity (ISP / multi-site)</h2>
    <p class="form-text text-muted small mb-2">Identify this probe for aggregation and reporting. Optional.</p>
    <div class="row g-2 mb-3">
      <div class="col-md-3">
        <label class="form-label small" for="probe-id">Probe ID</label>
        <input id="probe-id" type="text" class="form-control form-control-sm" bind:value={probeId} placeholder="e.g. pop-chicago-1" />
      </div>
      <div class="col-md-3">
        <label class="form-label small" for="location-name">Location name</label>
        <input id="location-name" type="text" class="form-control form-control-sm" bind:value={locationName} placeholder="e.g. Chicago POP" />
      </div>
      <div class="col-md-2">
        <label class="form-label small" for="region">Region</label>
        <input id="region" type="text" class="form-control form-control-sm" bind:value={region} placeholder="e.g. Midwest" />
      </div>
      <div class="col-md-2">
        <label class="form-label small" for="tier">Tier</label>
        <input id="tier" type="text" class="form-control form-control-sm" bind:value={tier} placeholder="e.g. 1G" />
      </div>
    </div>

    <hr class="my-4" />
    <h2 class="h6 mb-3">Ookla Speedtest servers</h2>
    <p class="form-text text-muted small mb-2">
      <strong>Local (ISP)</strong> is the default for ISPs: no patterns required. It uses Ookla's server list, optionally matches your line's ISP name (auto-detected, cached 7 days), then picks the smallest distance (km).
      <strong>Auto</strong> is a second run using Ookla's built-in server choice (good as a cross-check). Add more rows for specific server IDs if you want.
    </p>
    <div class="form-check mb-3">
      <input class="form-check-input" type="checkbox" id="ookla-auto-isp" bind:checked={ooklaLocalAutoIsp} />
      <label class="form-check-label small" for="ookla-auto-isp">Auto-detect ISP when patterns are empty</label>
      <p class="form-text text-muted small mb-0">Runs one Speedtest every 7 days (cached under <code class="small">$NETPERF_STORAGE</code> or <code class="small">/var/log/netperf/.ookla_isp_cache.json</code>) to learn your ISP name, then matches that to servers in the list. Turn off to use distance-only (nearest server in the list).</p>
    </div>
    <div class="mb-3">
      <label class="form-label small" for="ookla-local-patterns">Extra name patterns (optional)</label>
      <textarea
        id="ookla-local-patterns"
        class="form-control form-control-sm font-monospace"
        rows="2"
        placeholder="Only if auto-detect is not enough — one per line or comma-separated"
        bind:value={ooklaLocalPatternsText}
      ></textarea>
      <p class="form-text text-muted small mb-0">If set, <strong>only</strong> these substrings are used for <strong>Local (ISP)</strong> rows (auto-detect is skipped). Matches name, location, host, or sponsor.</p>
    </div>
    {#if ooklaOptionsError}
      <p class="small text-warning mb-2">Server list: {ooklaOptionsError}. You can still enter a server ID manually below.</p>
    {/if}
    <div class="ookla-list mb-4">
      {#each ooklaServers as row, i}
        <div class="row g-2 align-items-center mb-2">
          <div class="col-md-5">
            {#if ooklaOptionsLoading}
              <select class="form-select form-select-sm" disabled><option>Loading servers…</option></select>
            {:else if ooklaServerOptions.length > 0}
              <select
                class="form-select form-select-sm"
                value={row.id}
                on:change={(e) => onOoklaServerSelect(i, e.currentTarget.value)}
              >
                <option value="local">Local (ISP / nearest match)</option>
                <option value="auto">Auto (Ookla default)</option>
                {#each ooklaServerOptions as srv}
                  <option value={srv.id}>{fullServerName(srv)}</option>
                {/each}
              </select>
            {:else}
              <input type="text" class="form-control form-control-sm" placeholder="local, auto, or server ID" bind:value={row.id} />
            {/if}
          </div>
          <div class="col-md-4">
            <input type="text" class="form-control form-control-sm" placeholder="Label" bind:value={row.label} />
          </div>
          <div class="col-auto">
            <button type="button" class="btn btn-outline-danger btn-sm" on:click={() => removeOokla(i)} title="Remove"><i class="bi bi-dash-lg"></i></button>
          </div>
        </div>
      {/each}
      <button type="button" class="btn btn-outline-primary btn-sm" on:click={addOokla}><i class="bi bi-plus-lg me-1"></i> Add server</button>
      {#if ooklaServerOptions.length > 0 && !ooklaOptionsLoading}
        <button type="button" class="btn btn-link btn-sm ms-2" on:click={loadOoklaOptions}>Refresh server list</button>
      {/if}
    </div>

    <hr class="my-4" />
    <h2 class="h6 mb-3">iperf3</h2>
    <div class="row g-2 align-items-center mb-3">
      <div class="col-auto">
        <label for="iperf-duration" class="form-label small mb-0">Test duration (seconds)</label>
      </div>
      <div class="col-auto">
        <input id="iperf-duration" type="number" min="1" max="300" class="form-control form-control-sm" style="width:5rem" bind:value={iperfDurationSeconds} />
      </div>
      <div class="col-auto">
        <span class="small text-muted">1–300. Each iperf3 run will last this long.</span>
      </div>
    </div>
    <h2 class="h6 mb-3">iperf3 servers</h2>
    <p class="form-text text-muted small mb-2">Hostname or IP of iperf3 servers to test against. Add from public presets (from <a href="https://iperf.fr/iperf-servers.php" target="_blank" rel="noopener noreferrer">iperf.fr</a>) or enter your own.</p>
    <div class="iperf-servers-list mb-4">
      {#each iperfServers as row, i}
        <div class="row g-2 align-items-center mb-2">
          <div class="col-md-4">
            <input type="text" class="form-control form-control-sm font-monospace" placeholder="hostname or IP" bind:value={row.host} />
          </div>
          <div class="col-md-4">
            <input type="text" class="form-control form-control-sm" placeholder="Label" bind:value={row.label} />
          </div>
          <div class="col-auto">
            <button type="button" class="btn btn-outline-danger btn-sm" on:click={() => removeIperfServer(i)} title="Remove"><i class="bi bi-dash-lg"></i></button>
          </div>
        </div>
      {/each}
      <div class="d-flex flex-wrap align-items-center gap-2 mt-2">
        <button type="button" class="btn btn-outline-primary btn-sm" on:click={addIperfServer}><i class="bi bi-plus-lg me-1"></i> Add server</button>
        <select
          class="form-select form-select-sm w-auto"
          bind:this={iperfPresetSelectEl}
          on:change={onIperfPresetSelect}
          aria-label="Add iperf3 server from preset"
        >
          <option value="">Add from preset (iperf.fr)…</option>
          {#each IPERF_PRESET_SERVERS as preset, idx}
            <option value={idx}>{preset.label}</option>
          {/each}
        </select>
      </div>
    </div>

    <hr class="my-4" />
    <h2 class="h6 mb-3">iperf3 tests</h2>
    <p class="form-text text-muted small mb-2">Test profiles: name and iperf3 client args (e.g. <code>-P 1</code>, <code>-u -b 1G</code>).</p>
    <div class="iperf-tests-list mb-4">
      {#each iperfTests as row, i}
        <div class="row g-2 align-items-center mb-2">
          <div class="col-md-3">
            <input type="text" class="form-control form-control-sm" placeholder="Name" bind:value={row.name} />
          </div>
          <div class="col-md-5">
            <input type="text" class="form-control form-control-sm font-monospace" placeholder="e.g. -P 1 or -u -b 1G" bind:value={row.args} />
          </div>
          <div class="col-auto">
            <button type="button" class="btn btn-outline-danger btn-sm" on:click={() => removeIperfTest(i)} title="Remove"><i class="bi bi-dash-lg"></i></button>
          </div>
        </div>
      {/each}
      <button type="button" class="btn btn-outline-primary btn-sm" on:click={addIperfTest}><i class="bi bi-plus-lg me-1"></i> Add test</button>
    </div>

    <hr class="my-4" />
    <h2 class="h6 mb-3">SLA &amp; alerts</h2>
    <p class="form-text text-muted small mb-2">When results fall below these thresholds, a webhook is fired (15 min cooldown). Leave empty to disable.</p>
    <div class="row g-2 mb-2">
      <div class="col-auto">
        <label class="form-label small mb-0" for="sla-min-down">Min download (Mbps)</label>
        <input id="sla-min-down" type="number" min="0" class="form-control form-control-sm" style="width:6rem" bind:value={slaMinDownloadMbps} placeholder="—" />
      </div>
      <div class="col-auto">
        <label class="form-label small mb-0" for="sla-min-up">Min upload (Mbps)</label>
        <input id="sla-min-up" type="number" min="0" class="form-control form-control-sm" style="width:6rem" bind:value={slaMinUploadMbps} placeholder="—" />
      </div>
      <div class="col-auto">
        <label class="form-label small mb-0" for="sla-max-lat">Max latency (ms)</label>
        <input id="sla-max-lat" type="number" min="0" class="form-control form-control-sm" style="width:6rem" bind:value={slaMaxLatencyMs} placeholder="—" />
      </div>
    </div>
    <div class="mb-2">
      <label class="form-label small" for="webhook-url">Webhook URL</label>
      <input id="webhook-url" type="url" class="form-control form-control-sm font-monospace" bind:value={webhookUrl} placeholder="https://…" />
    </div>
    <div class="mb-3">
      <label class="form-label small" for="webhook-secret">Webhook secret (optional)</label>
      <input id="webhook-secret" type="password" class="form-control form-control-sm font-monospace" style="max-width:280px" bind:value={webhookSecret} placeholder="Sent as X-Webhook-Secret header" autocomplete="off" />
    </div>
    <div class="mb-3">
      <button type="button" class="btn btn-outline-secondary btn-sm" on:click={checkSlaNow} disabled={checkSlaLoading} title="Run SLA evaluation now (compare latest results to thresholds, fire webhook if violated)">
        {checkSlaLoading ? 'Checking…' : 'Check SLA now'}
      </button>
    </div>

    <hr class="my-4" />
    <h2 class="h6 mb-3">Data retention</h2>
    <p class="form-text text-muted small mb-2">Keep data for this many days. When using <strong>Purge old data</strong> in Setup without a custom days value, this is used (empty = 30).</p>
    <div class="mb-3">
      <label class="form-label small" for="retention-days">Retention (days)</label>
      <input id="retention-days" type="number" min="1" max="365" class="form-control form-control-sm" style="width:6rem" bind:value={retentionDays} placeholder="e.g. 90 or empty" />
    </div>

    <div class="d-flex flex-wrap align-items-center gap-2">
      <button type="submit" class="btn btn-primary">
        <i class="bi bi-check-lg me-1"></i> Save configuration
      </button>
      <span class="small" class:text-success={messageType === 'success'} class:text-danger={messageType === 'danger'}>{message}</span>
    </div>
    </form>
  </div>
</div>

<style>
  :global(.card) { border-radius: var(--radius-lg); }
  :global(.card-header) { font-weight: var(--font-weight-semibold); }
</style>
