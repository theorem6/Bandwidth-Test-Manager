import { get } from 'svelte/store';
import { auth, type AuthUser } from './auth';

const FETCH_TIMEOUT_MS = 15000;
/** Install-deps runs apt-get and can take several minutes */
const INSTALL_DEPS_TIMEOUT_MS = 300000; // 5 minutes

export function getBase(): string {
  if (typeof window === 'undefined') return '';
  const p = window.location.pathname;
  return p.startsWith('/netperf') ? '/netperf' : '';
}

export function authHeaders(): Record<string, string> {
  const u = get(auth);
  if (!u?.token) return {};
  return { Authorization: 'Basic ' + u.token };
}

export async function fetchApi<T>(url: string, opts: RequestInit = {}, timeoutMs: number = FETCH_TIMEOUT_MS): Promise<T> {
  const base = getBase();
  const headers = { ...authHeaders(), ...((opts.headers as Record<string, string>) || {}) };
  const ctrl = new AbortController();
  const id = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(base + url, { ...opts, signal: ctrl.signal, headers: { ...headers, ...opts.headers } });
    clearTimeout(id);
    const body = await r.json().catch(() => ({}));
    if (r.status === 401) {
      auth.logout();
      throw new Error('Login required');
    }
    if (!r.ok) {
      const b = body as { error?: string; detail?: string };
      const msg = typeof b?.error === 'string' ? b.error : typeof b?.detail === 'string' ? b.detail : r.statusText;
      throw new Error(msg);
    }
    return body as T;
  } catch (e) {
    clearTimeout(id);
    if (e instanceof Error && e.name === 'AbortError') throw new Error('Request timeout');
    throw e;
  }
}

/** Call GET /api/me with given credentials. Returns user or throws. Used for login. */
export async function loginWithCredentials(username: string, password: string): Promise<AuthUser> {
  const token = btoa(unescape(encodeURIComponent(username + ':' + password)));
  const base = getBase();
  const r = await fetch(base + '/api/me', {
    headers: { Authorization: 'Basic ' + token },
  });
  const body = await r.json().catch(() => ({}));
  if (r.status === 401) {
    throw new Error(body?.detail || 'Invalid credentials');
  }
  if (!r.ok) {
    throw new Error((body?.detail as string) || body?.error || r.statusText);
  }
  const data = body as { username: string; role: string };
  return {
    username: data.username,
    role: data.role === 'admin' ? 'admin' : 'readonly',
    token,
  };
}

export interface OoklaServer {
  id: number | 'auto' | 'local';
  label: string;
}

export interface IperfServer {
  host: string;
  label: string;
}

export interface IperfTest {
  name: string;
  args: string;
}

export interface SlaThresholds {
  min_download_mbps?: number | null;
  min_upload_mbps?: number | null;
  max_latency_ms?: number | null;
}

export interface Branding {
  app_title?: string;
  tagline?: string;
  logo_url?: string;
  logo_alt?: string;
  primary_color?: string;
  primary_hover_color?: string;
  navbar_gradient_start?: string;
  navbar_gradient_end?: string;
  navbar_bg_start?: string;
  navbar_bg_end?: string;
  custom_css?: string;
}

export interface Config {
  branding?: Branding;
  site_url?: string;
  ssl_cert_path?: string;
  ssl_key_path?: string;
  speedtest_limit_mbps?: number | null;
  cron_schedule?: string;
  iperf_duration_seconds?: number;
  ookla_servers?: OoklaServer[];
  /** Substrings to match your Ookla-hosted server name/location (see Settings). Used with id \"local\". */
  ookla_local_patterns?: string[];
  /** When true and patterns are empty, infer ISP from a cached speedtest probe to pick a matching server. */
  ookla_local_auto_isp?: boolean;
  iperf_servers?: IperfServer[];
  iperf_tests?: IperfTest[];
  probe_id?: string;
  location_name?: string;
  region?: string;
  tier?: string;
  sla_thresholds?: SlaThresholds;
  webhook_url?: string;
  webhook_secret?: string;
  retention_days?: number | null;
}

export async function checkSla(): Promise<{ ok: boolean; error?: string; message?: string }> {
  return fetchApi<{ ok: boolean; error?: string; message?: string }>('/api/check-sla', { method: 'POST' });
}

export interface AlertItem {
  id: number;
  created_at: string;
  probe_id: string;
  location_name: string;
  violations: Array<{ site: string; violations: string[] }>;
  webhook_fired: boolean;
}

export async function getAlerts(limit: number = 10): Promise<{ alerts: AlertItem[] }> {
  return fetchApi<{ alerts: AlertItem[] }>(`/api/alerts?limit=${Math.min(200, Math.max(1, limit))}`);
}

export interface UserItem {
  username: string;
  role: string;
}

export async function getUsers(): Promise<{ users: UserItem[] }> {
  return fetchApi<{ users: UserItem[] }>('/api/users');
}

export async function setPassword(username: string, password: string, role: string): Promise<{ ok: boolean; error?: string; message?: string }> {
  return fetchApi<{ ok: boolean; error?: string; message?: string }>('/api/users/set-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, role }),
  });
}

export async function getConfig(): Promise<Config> {
  return fetchApi<Config>('/api/config');
}

export async function putConfig(data: Partial<Config>): Promise<{ ok: boolean; error?: string }> {
  return fetchApi<{ ok: boolean; error?: string }>('/api/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

/** Upload logo image (admin). Sets branding.logo_url on the server. */
export async function uploadBrandLogo(file: File): Promise<{ ok: boolean; logo_url?: string; error?: string }> {
  const base = getBase();
  const fd = new FormData();
  fd.append('file', file);
  const headers = { ...authHeaders() };
  const r = await fetch(base + '/api/branding/logo', { method: 'POST', headers, body: fd });
  const body = (await r.json().catch(() => ({}))) as { ok?: boolean; logo_url?: string; error?: string };
  if (!r.ok) {
    return { ok: false, error: typeof body.error === 'string' ? body.error : r.statusText };
  }
  return { ok: !!body.ok, logo_url: body.logo_url, error: body.error };
}

export async function getDates(): Promise<{ dates: string[] }> {
  return fetchApi<{ dates: string[] }>('/api/dates');
}

export async function getStatus(): Promise<{ scheduled: boolean }> {
  return fetchApi<{ scheduled: boolean }>('/api/status');
}

export async function getData(date: string, probeId?: string): Promise<DataResponse> {
  let url = `/api/data?date=${encodeURIComponent(date)}`;
  if (probeId?.trim()) url += `&probe_id=${encodeURIComponent(probeId.trim())}`;
  return fetchApi(url, { cache: 'no-store' });
}

/** Main dashboard charts: window ending at **end** (YYYYMMDD). Imports each day in range into SQLite. */
export async function getDataRange(end: string, span: ChartSpan, probeId?: string): Promise<DataRangeResponse> {
  const q = new URLSearchParams({ end, span });
  if (probeId?.trim()) q.set('probe_id', probeId.trim());
  return fetchApi<DataRangeResponse>(`/api/data-range?${q.toString()}`, { cache: 'no-store' });
}

export interface SpeedtestPoint {
  timestamp: string;
  /** Log folder date YYYYMMDD (set for range queries and single-day API). */
  log_date?: string;
  download_bps?: number;
  upload_bps?: number;
  latency_ms?: number;
}

export interface IperfPoint {
  bits_per_sec: number;
  timestamp?: string;
  log_date?: string;
}

export interface DataResponse {
  speedtest: Record<string, SpeedtestPoint[]>;
  iperf: Record<string, IperfPoint[]>;
}

export type ChartSpan = 'day' | 'week' | 'month' | 'year';

export interface DataRangeResponse extends DataResponse {
  range: { from: string; to: string; span: ChartSpan; end: string } | null;
}

export interface HistorySpeedtestPoint {
  date: string;
  timestamp: string;
  site: string;
  download_bps?: number;
  upload_bps?: number;
  latency_ms?: number;
}

export interface HistoryIperfPoint {
  date: string;
  timestamp?: string;
  site: string;
  bits_per_sec?: number;
}

export interface HistoryResponse {
  speedtest: HistorySpeedtestPoint[];
  iperf: HistoryIperfPoint[];
}

export async function getHistory(days?: number, probeId?: string): Promise<HistoryResponse> {
  const params = new URLSearchParams();
  if (days != null) params.set('days', String(Math.min(366, Math.max(1, days))));
  if (probeId?.trim()) params.set('probe_id', probeId.trim());
  const q = params.toString() ? `?${params.toString()}` : '';
  return fetchApi<HistoryResponse>(`/api/history${q}`);
}

export async function schedulerStart(): Promise<{ ok: boolean; error?: string; message?: string }> {
  return fetchApi('/api/scheduler/start', { method: 'POST' });
}

export async function schedulerStop(): Promise<{ ok: boolean; error?: string; message?: string }> {
  return fetchApi('/api/scheduler/stop', { method: 'POST' });
}

export interface BackendStatus {
  speedtest_installed: boolean;
  iperf3_installed: boolean;
  jq_installed: boolean;
  config_path: string;
  config_exists: boolean;
  scheduled: boolean;
  cron_schedule: string;
  cron_line?: string;
  ookla_servers_count?: number;
  iperf_servers_count?: number;
  storage_path: string;
  storage_exists: boolean;
}

export async function getBackendStatus(): Promise<BackendStatus> {
  return fetchApi<BackendStatus>('/api/backend-status');
}

export async function installDeps(): Promise<{ ok: boolean; error?: string; message?: string }> {
  return fetchApi<{ ok: boolean; error?: string; message?: string }>(
    '/api/install-deps',
    { method: 'POST' },
    INSTALL_DEPS_TIMEOUT_MS
  );
}

export async function clearOldData(days?: number): Promise<{ ok: boolean; deleted_dirs?: number; deleted_speedtest_rows?: number; deleted_iperf_rows?: number; error?: string; message?: string }> {
  const url = days != null
    ? `/api/clear-old-data?days=${Math.min(365, Math.max(1, days))}`
    : '/api/clear-old-data';
  return fetchApi<{ ok: boolean; deleted_dirs?: number; deleted_speedtest_rows?: number; deleted_iperf_rows?: number; error?: string; message?: string }>(
    url,
    { method: 'POST' }
  );
}

export interface SummaryRow {
  site: string;
  count: number;
  download_bps_min: number | null;
  download_bps_max: number | null;
  download_bps_avg: number | null;
  upload_bps_min: number | null;
  upload_bps_max: number | null;
  upload_bps_avg: number | null;
  latency_ms_min: number | null;
  latency_ms_max: number | null;
  latency_ms_avg: number | null;
}

export async function getSummary(fromDate: string, toDate: string, probeId?: string): Promise<{ from: string; to: string; summary: SummaryRow[] }> {
  let url = `/api/summary?from_date=${encodeURIComponent(fromDate)}&to_date=${encodeURIComponent(toDate)}`;
  if (probeId?.trim()) url += `&probe_id=${encodeURIComponent(probeId.trim())}`;
  return fetchApi<{ from: string; to: string; summary: SummaryRow[] }>(url);
}

export async function getSummaryCsvBlob(fromDate: string, toDate: string, probeId?: string): Promise<Blob> {
  const base = getBase();
  let url = `${base}/api/export/summary?from_date=${encodeURIComponent(fromDate)}&to_date=${encodeURIComponent(toDate)}`;
  if (probeId?.trim()) url += `&probe_id=${encodeURIComponent(probeId.trim())}`;
  const r = await fetch(url, { headers: authHeaders() });
  if (r.status === 401) {
    auth.logout();
    throw new Error('Login required');
  }
  if (!r.ok) throw new Error(r.statusText);
  return r.blob();
}

export async function clearIperfData(): Promise<{ ok: boolean; deleted?: number; error?: string; message?: string }> {
  return fetchApi<{ ok: boolean; deleted?: number; error?: string; message?: string }>(
    '/api/clear-iperf-data',
    { method: 'POST' }
  );
}

export interface TimezoneResponse {
  timezone: string;
  local_time_iso: string;
  ntp_active: boolean;
}

export async function getTimezone(): Promise<TimezoneResponse> {
  return fetchApi<TimezoneResponse>('/api/timezone');
}

export async function getTimezones(): Promise<{ timezones: string[] }> {
  return fetchApi<{ timezones: string[] }>('/api/timezones');
}

export async function setTimezone(timezone: string): Promise<{ ok: boolean; error?: string; message?: string }> {
  return fetchApi<{ ok: boolean; error?: string; message?: string }>(
    '/api/timezone',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ timezone }) }
  );
}

export async function ntpInstall(): Promise<{ ok: boolean; error?: string; message?: string }> {
  return fetchApi<{ ok: boolean; error?: string; message?: string }>(
    '/api/ntp-install',
    { method: 'POST' },
    INSTALL_DEPS_TIMEOUT_MS
  );
}

export interface HealthResponse {
  ok: boolean;
  storage?: string;
  dates_count?: number;
  latest_date?: string | null;
  error?: string;
}

export async function getHealth(): Promise<HealthResponse> {
  return fetchApi<HealthResponse>('/api/health');
}

export interface DiagnosticCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface DiagnosticLogLine {
  ts: string;
  level: string;
  message: string;
  raw?: string;
}

export type LogStreamId = 'app_buffer' | 'app_events' | 'run_now' | 'speedtest_stderr';

export interface DiagnosticStreamMeta {
  path: string | null;
  lines: DiagnosticLogLine[];
}

export interface DiagnosticsResponse {
  checks: DiagnosticCheck[];
  logs: DiagnosticLogLine[];
  /** Parsed streams keyed by id (subset if filtered by `sources`). */
  streams?: Record<string, DiagnosticStreamMeta>;
  /** Concatenated lines from enabled streams in fixed order. */
  merged?: Array<DiagnosticLogLine & { source: LogStreamId }>;
  stream_order?: LogStreamId[];
  log_file: string;
  health_interval_minutes: number;
}

const LOG_SOURCE_IDS: LogStreamId[] = ['app_buffer', 'app_events', 'run_now', 'speedtest_stderr'];

/** Admin only: health checks + parsed log streams (buffer, files). */
export async function getDiagnostics(
  limit = 500,
  sources: LogStreamId[] | 'all' = 'all',
): Promise<DiagnosticsResponse> {
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  if (sources !== 'all' && sources.length > 0) {
    const want = sources.filter((s) => LOG_SOURCE_IDS.includes(s));
    if (want.length > 0) {
      params.set('sources', want.join(','));
    }
  }
  return fetchApi<DiagnosticsResponse>(`/api/admin/diagnostics?${params.toString()}`);
}

/** Fetch CSV export for a date (full speedtest + iperf data). Returns blob for download. */
export async function getExportCsvBlob(date: string): Promise<Blob> {
  const base = getBase();
  const headers = authHeaders();
  const r = await fetch(`${base}/api/export/csv?date=${encodeURIComponent(date)}`, { headers });
  if (r.status === 401) {
    auth.logout();
    throw new Error('Login required');
  }
  if (!r.ok) throw new Error(r.status === 404 ? 'No data for this date' : r.statusText);
  return r.blob();
}

export async function runTestNow(): Promise<{ ok: boolean; message?: string; error?: string }> {
  return fetchApi<{ ok: boolean; message?: string; error?: string }>('/api/run-now', { method: 'POST' });
}

export interface RunStatusResponse {
  running: boolean;
  started_at?: number;
}

export async function getRunStatus(): Promise<RunStatusResponse> {
  return fetchApi<RunStatusResponse>('/api/run-status');
}

export interface SpeedtestServerOption {
  id: number;
  /** May be missing if the CLI/API returns sparse rows. */
  name?: string;
  location?: string;
  /** Country name when list comes from Speedtest.net API (used for grouping). */
  country?: string;
  /** Some Ookla JSON rows use sponsor vs name — backend may send either. */
  sponsor?: string;
  host?: string;
  /** ISO country code from Speedtest.net catalog (e.g. US). */
  cc?: string;
}

export async function getSpeedtestServers(
  search?: string,
  limit = 100
): Promise<{ servers: SpeedtestServerOption[]; error?: string }> {
  const p = new URLSearchParams();
  const s = search?.trim();
  if (s) {
    p.set('search', s);
    p.set('limit', String(Math.min(100, Math.max(1, limit))));
  }
  const q = p.toString();
  return fetchApi<{ servers: SpeedtestServerOption[]; error?: string }>(
    `/api/speedtest-servers${q ? `?${q}` : ''}`
  );
}

// --- Remote nodes (probes that report back to this server) ---

export interface RemoteNode {
  node_id: string;
  name: string;
  location: string;
  address: string;
  created_at: string;
  last_seen_at: string;
}

export async function getRemoteNodes(): Promise<{ nodes: RemoteNode[] }> {
  return fetchApi<{ nodes: RemoteNode[] }>('/api/remote/nodes');
}

export async function createRemoteNode(name: string, location: string, address?: string): Promise<{
  ok: boolean;
  node?: RemoteNode & { token: string };
  error?: string;
  message?: string;
}> {
  return fetchApi('/api/remote/nodes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: name.trim(),
      location: location.trim(),
      address: (address || '').trim(),
    }),
  });
}

export async function getRemoteNode(nodeId: string): Promise<RemoteNode | null> {
  try {
    return await fetchApi<RemoteNode>(`/api/remote/nodes/${encodeURIComponent(nodeId)}`);
  } catch {
    return null;
  }
}

export async function updateRemoteNode(
  nodeId: string,
  data: { name?: string; location?: string; address?: string }
): Promise<{ ok: boolean; node?: RemoteNode; error?: string }> {
  return fetchApi(`/api/remote/nodes/${encodeURIComponent(nodeId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function deleteRemoteNode(nodeId: string): Promise<{ ok: boolean; error?: string }> {
  return fetchApi(`/api/remote/nodes/${encodeURIComponent(nodeId)}`, { method: 'DELETE' });
}

/** Download the remote agent script (uses auth). Returns script text; caller can trigger save. */
export async function getRemoteScript(nodeId: string): Promise<string> {
  const base = getBase();
  const r = await fetch(`${base}/api/remote/script/${encodeURIComponent(nodeId)}`, {
    headers: authHeaders(),
  });
  if (r.status === 401) {
    auth.logout();
    throw new Error('Login required');
  }
  if (!r.ok) throw new Error('Failed to download script');
  return r.text();
}

/** Voice / SIP domain schema from GET /api/voice/schema */
export interface VoiceBoundContext {
  id: string;
  label: string;
  entities: string[];
}

export interface VoiceCarrierRow {
  dimension: string;
  bandwidth: string;
  telnyx: string;
  twilio: string;
}

export interface VoiceDomainSchema {
  bounded_contexts: VoiceBoundContext[];
  entities: Record<string, string>;
  state_machines: Record<string, string[]>;
  carrier_comparison: VoiceCarrierRow[];
  pragmatic_recommendation: string;
  arcgis: { note: string; uses: string[] };
  phased_rollout: { phase: number; scope: string }[];
  first_build_in_code: string[];
  enums: Record<string, string[]>;
}

export async function fetchVoiceSchema(): Promise<VoiceDomainSchema> {
  return fetchApi<VoiceDomainSchema>('/api/voice/schema');
}
