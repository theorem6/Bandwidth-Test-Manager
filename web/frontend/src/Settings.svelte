<script lang="ts">
  import { onMount } from 'svelte';
  import { getConfig, putConfig, getSpeedtestServers } from './lib/api';
  import type { Config, OoklaServer, IperfServer, IperfTest, SpeedtestServerOption } from './lib/api';

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

  function ooklaToForm(raw: OoklaServer[]): { id: string; label: string }[] {
    if (!Array.isArray(raw)) return [];
    return raw.map((s) => ({
      id: s.id === 'auto' ? 'auto' : String(s.id),
      label: s.label ?? '',
    }));
  }
  function formToOokla(form: { id: string; label: string }[]): OoklaServer[] {
    return form.map((s) => {
      const idStr = (s.id ?? '').trim().toLowerCase();
      return {
        id: idStr === 'auto' || idStr === '' ? 'auto' : (parseInt(idStr, 10) || 0),
        label: (s.label ?? '').trim() || 'Server',
      };
    });
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
    const opt = value === 'auto' ? null : ooklaServerOptions.find((s) => String(s.id) === value);
    const newLabel = value === 'auto' ? (ooklaServers[i]?.label || 'Auto') : (opt ? fullServerName(opt) : ooklaServers[i]?.label || '');
    ooklaServers = ooklaServers.map((row, j) => j === i ? { id: value, label: newLabel } : row);
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
      loadOoklaOptions();
    } catch {
      message = 'Failed to load config';
      messageType = 'danger';
    }
  });

  function addOokla() {
    ooklaServers = [...ooklaServers, { id: 'auto', label: '' }];
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

  async function save() {
    message = '';
    const limitVal = limitMbps.trim();
    const limit = limitVal === '' ? null : parseInt(limitVal, 10);
    if (limitVal !== '' && (isNaN(limit!) || limit! < 1)) {
      message = 'Speed limit must be a positive number or empty.';
      messageType = 'danger';
      return;
    }
    try {
      const duration = Math.max(1, Math.min(300, parseInt(String(iperfDurationSeconds), 10) || 10));
      const r = await putConfig({
        site_url: siteUrl.trim(),
        ssl_cert_path: sslCertPath.trim(),
        ssl_key_path: sslKeyPath.trim(),
        speedtest_limit_mbps: limit,
        cron_schedule: cronSchedule.trim() || '5 * * * *',
        iperf_duration_seconds: duration,
        ookla_servers: formToOokla(ooklaServers),
        iperf_servers: iperfServers.map((s) => ({ host: s.host.trim() || 'localhost', label: s.label.trim() || 'Server' })),
        iperf_tests: iperfTests.map((t) => ({ name: (t.name || 'test').trim(), args: (t.args || '').trim() })),
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
</script>

<div class="card">
  <div class="card-header text-dark">Configuration</div>
  <div class="card-body">
    <p class="text-muted small mb-4">All settings are configured from this page. Use <strong>Setup</strong> to install Ookla and iperf3 on the server, then configure servers and tests here.</p>

    <div class="mb-3">
      <label class="form-label" for="site-url">Site URL (HTTPS)</label>
      <p class="form-text text-muted small">URL only, no port (e.g. https://host.example.com/netperf/).</p>
      <input id="site-url" type="url" class="form-control form-control-sm" bind:value={siteUrl} placeholder="https://hss.wisptools.io/netperf/" />
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
    <h2 class="h6 mb-3">Ookla Speedtest servers</h2>
    <p class="form-text text-muted small mb-2">Add servers to test. Choose <strong>Auto</strong> or pick from all available Ookla servers.</p>
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
                <option value="auto">Auto (nearest)</option>
                {#each ooklaServerOptions as srv}
                  <option value={srv.id}>{fullServerName(srv)}</option>
                {/each}
              </select>
            {:else}
              <input type="text" class="form-control form-control-sm" placeholder="auto or server ID" bind:value={row.id} />
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

    <div class="d-flex flex-wrap align-items-center gap-2">
      <button type="button" class="btn btn-primary" on:click={save}>
        <i class="bi bi-check-lg me-1"></i> Save configuration
      </button>
      <span class="small" class:text-success={messageType === 'success'} class:text-danger={messageType === 'danger'}>{message}</span>
    </div>
  </div>
</div>

<style>
  :global(.card) { border: none; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.08); }
  :global(.card-header) { background: #fff; border-bottom: 1px solid #eee; font-weight: 600; padding: 0.75rem 1rem; }
</style>
