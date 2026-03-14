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
  id: number | 'auto';
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

export interface Config {
  site_url?: string;
  ssl_cert_path?: string;
  ssl_key_path?: string;
  speedtest_limit_mbps?: number | null;
  cron_schedule?: string;
  iperf_duration_seconds?: number;
  ookla_servers?: OoklaServer[];
  iperf_servers?: IperfServer[];
  iperf_tests?: IperfTest[];
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

export async function getDates(): Promise<{ dates: string[] }> {
  return fetchApi<{ dates: string[] }>('/api/dates');
}

export async function getStatus(): Promise<{ scheduled: boolean }> {
  return fetchApi<{ scheduled: boolean }>('/api/status');
}

export async function getData(date: string): Promise<DataResponse> {
  return fetchApi(`/api/data?date=${encodeURIComponent(date)}`, { cache: 'no-store' });
}

export interface SpeedtestPoint {
  timestamp: string;
  download_bps?: number;
  upload_bps?: number;
  latency_ms?: number;
}

export interface IperfPoint {
  bits_per_sec: number;
  timestamp?: string;
}

export interface DataResponse {
  speedtest: Record<string, SpeedtestPoint[]>;
  iperf: Record<string, IperfPoint[]>;
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

export async function getHistory(days?: number): Promise<HistoryResponse> {
  const q = days != null ? `?days=${days}` : '';
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

export async function clearOldData(days: number = 30): Promise<{ ok: boolean; deleted?: number; error?: string; message?: string }> {
  return fetchApi<{ ok: boolean; deleted?: number; error?: string; message?: string }>(
    `/api/clear-old-data?days=${Math.min(365, Math.max(1, days))}`,
    { method: 'POST' }
  );
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
  name: string;
  location: string;
}

export async function getSpeedtestServers(): Promise<{ servers: SpeedtestServerOption[]; error?: string }> {
  return fetchApi<{ servers: SpeedtestServerOption[]; error?: string }>('/api/speedtest-servers');
}
