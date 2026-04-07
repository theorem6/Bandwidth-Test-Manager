<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { getConfig, putConfig, getSpeedtestServers, checkSla, uploadBrandLogo } from './lib/api';
  import type { Config, OoklaServer, IperfServer, IperfTest, SpeedtestServerOption, Branding } from './lib/api';
  import { loadBranding } from './lib/branding';
  import { themeMode, setTheme, type ThemeMode } from './lib/theme';
  import { CRON_PRESETS, normalizeCronToPreset } from './lib/schedule';

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
  /** Ookla server list filter (trim on Search / Enter). ooklaFilterEpoch forces select DOM refresh. */
  let ooklaSearchQuery = '';
  let ooklaFilterEpoch = 0;
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

  let brandAppTitle = '';
  let brandTagline = '';
  let brandLogoUrl = '';
  let brandLogoAlt = '';
  let brandPrimary = '';
  let brandPrimaryHover = '';
  let brandGradStart = '';
  let brandGradEnd = '';
  let brandNavBgStart = '';
  let brandNavBgEnd = '';
  let brandCustomCss = '';
  let brandLogoBusy = false;

  function brandingPayload(): Branding {
    return {
      app_title: str(brandAppTitle).trim(),
      tagline: str(brandTagline).trim(),
      logo_url: str(brandLogoUrl).trim(),
      logo_alt: str(brandLogoAlt).trim(),
      primary_color: str(brandPrimary).trim(),
      primary_hover_color: str(brandPrimaryHover).trim(),
      navbar_gradient_start: str(brandGradStart).trim(),
      navbar_gradient_end: str(brandGradEnd).trim(),
      navbar_bg_start: str(brandNavBgStart).trim(),
      navbar_bg_end: str(brandNavBgEnd).trim(),
      custom_css: brandCustomCss,
    };
  }

  function loadBrandingForm(br: Branding | undefined) {
    const b = br || {};
    brandAppTitle = str(b.app_title);
    brandTagline = str(b.tagline);
    brandLogoUrl = str(b.logo_url);
    brandLogoAlt = str(b.logo_alt);
    brandPrimary = str(b.primary_color);
    brandPrimaryHover = str(b.primary_hover_color);
    brandGradStart = str(b.navbar_gradient_start);
    brandGradEnd = str(b.navbar_gradient_end);
    brandNavBgStart = str(b.navbar_bg_start);
    brandNavBgEnd = str(b.navbar_bg_end);
    brandCustomCss = typeof b.custom_css === 'string' ? b.custom_css : '';
  }

  async function onBrandLogoFile(ev: Event) {
    const input = ev.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    brandLogoBusy = true;
    try {
      const r = await uploadBrandLogo(file);
      if (r.ok && r.logo_url) {
        brandLogoUrl = r.logo_url;
        onToast('Logo uploaded.', 'success');
        await loadBranding();
      } else {
        onToast(r.error || 'Logo upload failed.', 'error');
      }
    } finally {
      brandLogoBusy = false;
      input.value = '';
    }
  }

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
      ooklaFilterEpoch += 1;
    } catch (e) {
      ooklaServerOptions = [];
      ooklaOptionsError = e instanceof Error ? e.message : 'Failed to load server list';
    } finally {
      ooklaOptionsLoading = false;
    }
  }

  async function applyOoklaSearch() {
    const t = ooklaSearchQuery.trim();
    ooklaSearchQuery = t;
    ooklaFilterEpoch += 1;
    await tick();
    if (ooklaServerOptions.length > 400 && !t) {
      onToast('Large server list: type a city, country, or provider, then press Search.', 'error');
    }
  }

  function onOoklaSearchKeydown(ev: KeyboardEvent) {
    if (ev.key === 'Enter') {
      ev.preventDefault();
      void applyOoklaSearch();
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

  function groupOoklaByCountry(list: SpeedtestServerOption[]): { country: string; servers: SpeedtestServerOption[] }[] {
    const m = new Map<string, SpeedtestServerOption[]>();
    for (const s of list) {
      const c = (s.country || '').trim() || 'Other';
      if (!m.has(c)) m.set(c, []);
      m.get(c)!.push(s);
    }
    return Array.from(m.entries())
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([country, servers]) => ({
        country,
        servers: servers.sort((a, b) => fullServerName(a).localeCompare(fullServerName(b))),
      }));
  }

  $: ooklaFiltered = (() => {
    const q = ooklaSearchQuery.trim().toLowerCase();
    let arr = ooklaServerOptions;
    if (q) {
      arr = arr.filter((s) => {
        const hay = `${fullServerName(s)} ${s.id} ${s.country || ''}`.toLowerCase();
        return hay.includes(q);
      });
    }
    return arr.slice(0, 600);
  })();

  /** Include epoch so grouping recomputes after Search forces trim + key bump */
  $: ooklaGrouped = (ooklaFilterEpoch, groupOoklaByCountry(ooklaFiltered));

  /** Large catalog: require a non-empty search before filling the dropdown */
  $: ooklaNeedsFilter = ooklaServerOptions.length > 400 && !ooklaSearchQuery.trim();

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
      cronSchedule = normalizeCronToPreset((c.cron_schedule || '5 * * * *').trim());
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
      loadBrandingForm(c.branding);
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
        cron_schedule: normalizeCronToPreset(str(cronSchedule).trim() || '5 * * * *'),
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
        branding: brandingPayload(),
      });
      if (r.ok) {
        message = 'Saved.';
        messageType = 'success';
        onToast('Configuration saved.');
        await loadBranding();
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

<!-- Branding (admin): logo, text, colors, custom CSS -->
<div class="card mb-4">
  <div class="card-header">Branding</div>
  <div class="card-body">
    <p class="text-muted small mb-3">
      Customize the navbar logo, title, tagline, and theme colors. Empty fields keep built-in defaults (except tagline: leave empty to hide it once other branding is set).
      Logo file is stored on the server under <code class="small">static/uploads/</code>.
    </p>
    <div class="row g-2 mb-3">
      <div class="col-md-4">
        <label class="form-label small" for="brand-app-title">App title</label>
        <input id="brand-app-title" type="text" class="form-control form-control-sm" bind:value={brandAppTitle} placeholder="Bandwidth Test Manager" />
      </div>
      <div class="col-md-4">
        <label class="form-label small" for="brand-tagline">Tagline (under title)</label>
        <input id="brand-tagline" type="text" class="form-control form-control-sm" bind:value={brandTagline} placeholder="e.g. yourcompany.com" />
      </div>
      <div class="col-md-4">
        <label class="form-label small" for="brand-logo-alt">Logo alt text</label>
        <input id="brand-logo-alt" type="text" class="form-control form-control-sm" bind:value={brandLogoAlt} placeholder="Company name" />
      </div>
    </div>
    <div class="mb-3">
      <label class="form-label small" for="brand-logo-url">Logo URL or path</label>
      <input id="brand-logo-url" type="text" class="form-control form-control-sm font-monospace" bind:value={brandLogoUrl} placeholder="/static/uploads/brand-logo.png or https://..." />
      <div class="d-flex flex-wrap align-items-center gap-2 mt-2">
        <input id="brand-logo-file" type="file" class="form-control form-control-sm" style="max-width:220px" accept=".png,.jpg,.jpeg,.svg,.webp,.gif,.ico,image/*" on:change={onBrandLogoFile} disabled={brandLogoBusy} />
        <span class="small text-muted">{brandLogoBusy ? 'Uploading…' : 'Upload replaces file at uploads/brand-logo.*'}</span>
      </div>
    </div>
    <p class="small text-muted mb-2">Colors: 3- or 6-digit hex (e.g. <code>#00d9ff</code>). Leave empty for theme defaults.</p>
    <div class="row g-2 mb-3">
      <div class="col-6 col-md-2">
        <label class="form-label small" for="brand-primary">Primary</label>
        <input id="brand-primary" type="text" class="form-control form-control-sm font-monospace" bind:value={brandPrimary} placeholder="#00d9ff" />
      </div>
      <div class="col-6 col-md-2">
        <label class="form-label small" for="brand-primary-h">Primary hover</label>
        <input id="brand-primary-h" type="text" class="form-control form-control-sm font-monospace" bind:value={brandPrimaryHover} placeholder="#00f2fe" />
      </div>
      <div class="col-6 col-md-2">
        <label class="form-label small" for="brand-g1">Title gradient A</label>
        <input id="brand-g1" type="text" class="form-control form-control-sm font-monospace" bind:value={brandGradStart} placeholder="#00f2fe" />
      </div>
      <div class="col-6 col-md-2">
        <label class="form-label small" for="brand-g2">Title gradient B</label>
        <input id="brand-g2" type="text" class="form-control form-control-sm font-monospace" bind:value={brandGradEnd} placeholder="#4facfe" />
      </div>
      <div class="col-6 col-md-2">
        <label class="form-label small" for="brand-n1">Navbar bg A (dark)</label>
        <input id="brand-n1" type="text" class="form-control form-control-sm font-monospace" bind:value={brandNavBgStart} placeholder="#1a2332" />
      </div>
      <div class="col-6 col-md-2">
        <label class="form-label small" for="brand-n2">Navbar bg B (dark)</label>
        <input id="brand-n2" type="text" class="form-control form-control-sm font-monospace" bind:value={brandNavBgEnd} placeholder="#1e3a4f" />
      </div>
    </div>
    <div class="mb-0">
      <label class="form-label small" for="brand-css">Custom CSS (optional)</label>
      <textarea id="brand-css" class="form-control form-control-sm font-monospace" rows="6" bind:value={brandCustomCss} placeholder="/* Injected into page head. No script tags. */"></textarea>
    </div>
  </div>
</div>

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

<form on:submit|preventDefault={save} aria-label="Configuration form">
<div class="card mb-4">
  <div class="card-header">Site &amp; HTTPS</div>
  <div class="card-body">
    <p class="text-muted small mb-3">Public URL and certificate paths for reverse proxy / TLS (optional if you only use IP:port).</p>
    <div class="mb-3">
      <label class="form-label" for="site-url">Public site URL</label>
      <p class="form-text text-muted small mb-1">HTTPS URL visitors use, no port (example: <code>https://monitor.example.com/netperf/</code>).</p>
      <input id="site-url" type="url" class="form-control form-control-sm" bind:value={siteUrl} placeholder="https://example.com/netperf/" />
    </div>
    <div class="mb-3">
      <label class="form-label" for="ssl-cert">TLS certificate file</label>
      <p class="form-text text-muted small mb-1">Full path to PEM bundle (often Let’s Encrypt <code>fullchain.pem</code>).</p>
      <input id="ssl-cert" type="text" class="form-control form-control-sm font-monospace" bind:value={sslCertPath} placeholder="/etc/letsencrypt/live/domain/fullchain.pem" />
    </div>
    <div class="mb-0">
      <label class="form-label" for="ssl-key">TLS private key file</label>
      <p class="form-text text-muted small mb-1">Full path to PEM key (often <code>privkey.pem</code>).</p>
      <input id="ssl-key" type="text" class="form-control form-control-sm font-monospace" bind:value={sslKeyPath} placeholder="/etc/letsencrypt/live/domain/privkey.pem" />
    </div>
  </div>
</div>

<div class="card mb-4">
  <div class="card-header">Scheduled tests</div>
  <div class="card-body">
    <p class="text-muted small mb-3">
      How often automated runs happen when you start the schedule on the <strong>Scheduler</strong> page. Times use the server’s clock.
    </p>
    <div class="mb-0">
      <label class="form-label" for="cron-preset">Run frequency</label>
      <select id="cron-preset" class="form-select form-select-sm" style="max-width:28rem" bind:value={cronSchedule}>
        {#each CRON_PRESETS as p}
          <option value={p.cron}>{p.label} — {p.detail}</option>
        {/each}
      </select>
    </div>
  </div>
</div>

<div class="card mb-4">
  <div class="card-header">Speedtest (Ookla)</div>
  <div class="card-body">
    <div class="mb-4">
      <label class="form-label" for="limit-mbps">Cap download speed (Mbps)</label>
      <p class="form-text text-muted small mb-1">Optional. Uses <code>trickle</code> when installed so tests don’t saturate the link. Leave empty for full speed.</p>
      <input id="limit-mbps" type="number" class="form-control form-control-sm" style="max-width:120px" min="1" bind:value={limitMbps} placeholder="No cap" />
    </div>

    <h2 class="h6 mb-2">Which Speedtest servers to use</h2>
    <p class="form-text text-muted small mb-3">
      <strong>Local (ISP)</strong> picks a nearby server that matches your provider when possible.
      <strong>Auto</strong> lets Ookla choose (good for comparison). You can add specific servers from the list below (search by city, country, or provider).
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
      <p class="small text-warning mb-2">{ooklaOptionsError} You can type a numeric server ID in the box if the list fails.</p>
    {/if}
    <div class="mb-2">
      <label class="form-label small" for="ookla-filter">Search servers</label>
      <div class="input-group input-group-sm mb-1" style="max-width: 36rem">
        <input
          id="ookla-filter"
          type="search"
          class="form-control"
          placeholder="City, country, provider, or server ID…"
          bind:value={ooklaSearchQuery}
          on:keydown={onOoklaSearchKeydown}
          autocomplete="off"
          disabled={ooklaOptionsLoading}
        />
        <button
          type="button"
          class="btn btn-primary"
          on:click|preventDefault|stopPropagation={() => void applyOoklaSearch()}
          disabled={ooklaOptionsLoading}
          title="Trim text and refresh the server dropdowns"
        >
          Search
        </button>
      </div>
      <p class="form-text text-muted small mb-2">
        {#if ooklaServerOptions.length > 0}
          {#if ooklaNeedsFilter}
            Large list — enter a term above and click <strong>Search</strong> (or press Enter) to fill the dropdowns.
          {:else}
            Showing {ooklaFiltered.length} of {ooklaServerOptions.length} servers matching “{ooklaSearchQuery || '(all)'}”.
          {/if}
        {:else}
          List loads from Ookla on this machine (and Speedtest.net when online).
        {/if}
      </p>
    </div>
    <div class="ookla-list mb-3">
      {#each ooklaServers as row, i}
        <div class="row g-2 align-items-center mb-2">
          <div class="col-md-5">
            {#if ooklaOptionsLoading}
              <select class="form-select form-select-sm" disabled><option>Loading servers…</option></select>
            {:else if ooklaServerOptions.length > 0}
              {#if ooklaNeedsFilter}
                <select class="form-select form-select-sm" disabled aria-disabled="true">
                  <option>Enter a search above, then click Search…</option>
                </select>
              {:else}
                {#key ooklaFilterEpoch}
                  <select
                    class="form-select form-select-sm"
                    value={row.id}
                    on:change={(e) => onOoklaServerSelect(i, e.currentTarget.value)}
                  >
                    <option value="local">Local (ISP / nearest match)</option>
                    <option value="auto">Auto (Ookla default)</option>
                    {#each ooklaGrouped as g}
                      <optgroup label={g.country}>
                        {#each g.servers as srv}
                          <option value={String(srv.id)}>{fullServerName(srv)}</option>
                        {/each}
                      </optgroup>
                    {/each}
                  </select>
                {/key}
              {/if}
            {:else}
              <input type="text" class="form-control form-control-sm" placeholder="local, auto, or numeric server ID" bind:value={row.id} />
            {/if}
          </div>
          <div class="col-md-4">
            <input type="text" class="form-control form-control-sm" placeholder="Label shown in graphs" bind:value={row.label} />
          </div>
          <div class="col-auto">
            <button type="button" class="btn btn-outline-danger btn-sm" on:click={() => removeOokla(i)} title="Remove"><i class="bi bi-dash-lg"></i></button>
          </div>
        </div>
      {/each}
      <button type="button" class="btn btn-outline-primary btn-sm" on:click={addOokla}><i class="bi bi-plus-lg me-1"></i> Add row</button>
      {#if ooklaServerOptions.length > 0 && !ooklaOptionsLoading}
        <button type="button" class="btn btn-link btn-sm ms-2" on:click={loadOoklaOptions}>Reload server list</button>
      {/if}
    </div>
  </div>
</div>

<div class="card mb-4">
  <div class="card-header">Probe identity</div>
  <div class="card-body">
    <p class="text-muted small mb-3">Labels this installation in reports and multi-site views. All optional.</p>
    <div class="row g-2">
      <div class="col-md-3">
        <label class="form-label small" for="probe-id">Probe ID</label>
        <input id="probe-id" type="text" class="form-control form-control-sm" bind:value={probeId} placeholder="e.g. pop-chicago-1" />
      </div>
      <div class="col-md-3">
        <label class="form-label small" for="location-name">Site / location name</label>
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
  </div>
</div>

<div class="card mb-4">
  <div class="card-header">iperf3</div>
  <div class="card-body">
    <p class="text-muted small mb-3">Throughput tests to remote iperf3 hosts (separate from Ookla).</p>
    <h2 class="h6 mb-2">Test length</h2>
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
    <h2 class="h6 mb-2">Remote hosts</h2>
    <p class="form-text text-muted small mb-2">Enter hostname or IP, or pick a public host from the list (sourced from <a href="https://iperf.fr/iperf-servers.php" target="_blank" rel="noopener noreferrer">iperf.fr</a>).</p>
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
    <h2 class="h6 mb-2">Test profiles</h2>
    <p class="form-text text-muted small mb-2">Each profile is one iperf3 run. “Args” are passed to the iperf3 client (examples: <code>-P 4</code> parallel streams, <code>-u -b 500M</code> UDP).</p>
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
  </div>
</div>

<div class="card mb-4">
  <div class="card-header">SLA &amp; alerts</div>
  <div class="card-body">
    <p class="text-muted small mb-3">Alert when measured speed or latency crosses these limits. Sends a POST to your webhook (at most once every 15 minutes).</p>
    <div class="row g-2 mb-3">
      <div class="col-auto">
        <label class="form-label small mb-0" for="sla-min-down">Minimum download (Mbps)</label>
        <input id="sla-min-down" type="number" min="0" class="form-control form-control-sm" style="width:6rem" bind:value={slaMinDownloadMbps} placeholder="—" />
      </div>
      <div class="col-auto">
        <label class="form-label small mb-0" for="sla-min-up">Minimum upload (Mbps)</label>
        <input id="sla-min-up" type="number" min="0" class="form-control form-control-sm" style="width:6rem" bind:value={slaMinUploadMbps} placeholder="—" />
      </div>
      <div class="col-auto">
        <label class="form-label small mb-0" for="sla-max-lat">Maximum latency (ms)</label>
        <input id="sla-max-lat" type="number" min="0" class="form-control form-control-sm" style="width:6rem" bind:value={slaMaxLatencyMs} placeholder="—" />
      </div>
    </div>
    <div class="mb-2">
      <label class="form-label small" for="webhook-url">Webhook URL</label>
      <input id="webhook-url" type="url" class="form-control form-control-sm font-monospace" bind:value={webhookUrl} placeholder="https://your-automation.example/hooks/netperf" />
    </div>
    <div class="mb-3">
      <label class="form-label small" for="webhook-secret">Shared secret (optional)</label>
      <input id="webhook-secret" type="password" class="form-control form-control-sm font-monospace" style="max-width:280px" bind:value={webhookSecret} placeholder="Verifies requests (X-Webhook-Secret header)" autocomplete="off" />
    </div>
    <button type="button" class="btn btn-outline-secondary btn-sm" on:click={checkSlaNow} disabled={checkSlaLoading} title="Evaluate latest results against thresholds now">
      {checkSlaLoading ? 'Checking…' : 'Run SLA check now'}
    </button>
  </div>
</div>

<div class="card mb-4">
  <div class="card-header">Data retention</div>
  <div class="card-body">
    <p class="text-muted small mb-3">How long to keep raw results. <strong>Purge old data</strong> in Setup uses this when no custom day count is entered (empty here defaults to 30 days in the purge action).</p>
    <div class="mb-0">
      <label class="form-label small" for="retention-days">Keep data (days)</label>
      <input id="retention-days" type="number" min="1" max="365" class="form-control form-control-sm" style="width:6rem" bind:value={retentionDays} placeholder="e.g. 90" />
    </div>
  </div>
</div>

<div class="d-flex flex-wrap align-items-center gap-2 mb-4">
  <button type="submit" class="btn btn-primary">
    <i class="bi bi-check-lg me-1"></i> Save configuration
  </button>
  <span class="small" class:text-success={messageType === 'success'} class:text-danger={messageType === 'danger'}>{message}</span>
</div>
</form>

<style>
  :global(.card) { border-radius: var(--radius-lg); }
  :global(.card-header) { font-weight: var(--font-weight-semibold); }
</style>
