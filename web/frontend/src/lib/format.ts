export function formatValue(val: number | null | undefined, metric: string): string {
  if (val == null) return '—';
  if (metric === 'latency_ms') return Number(val).toFixed(1) + ' ms';
  if (metric === 'download_bps' || metric === 'upload_bps' || metric === 'bits_per_sec') {
    const mbps = Number(val) / 1e6;
    return mbps >= 1000 ? (mbps / 1000).toFixed(2) + ' Gbps' : mbps.toFixed(2) + ' Mbps';
  }
  return String(val);
}

/** YYYYMMDD -> "Mar 13, 2025" */
export function formatDate(ymd: string): string {
  if (!ymd || ymd.length < 8) return ymd;
  const y = ymd.slice(0, 4);
  const m = ymd.slice(4, 6);
  const d = ymd.slice(6, 8);
  const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const mi = parseInt(m, 10) - 1;
  const month = mi >= 0 && mi < 12 ? monthNames[mi] : m;
  return `${month} ${parseInt(d, 10) || d}, ${y}`;
}

/** YYYYMMDD -> "Mar 13" for compact labels */
export function formatDateShort(ymd: string): string {
  if (!ymd || ymd.length < 8) return ymd;
  const m = ymd.slice(4, 6);
  const d = ymd.slice(6, 8);
  const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const mi = parseInt(m, 10) - 1;
  const month = mi >= 0 && mi < 12 ? monthNames[mi] : m;
  return `${month} ${parseInt(d, 10) || d}`;
}

/** ISO timestamp -> "2:30 PM" (time only) */
export function formatTime(ts: string): string {
  if (!ts) return '—';
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts;
  return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', hour12: true });
}

/** ISO timestamp -> "Mar 14, 2:30 PM" for chart x-axis (date + time, compact) */
export function formatDateTimeShort(ts: string): string {
  if (!ts) return '—';
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts;
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

/** ISO or YYYY-MM-DDTHH:MM timestamp -> "Mar 13, 2025, 2:30 PM" */
export function formatDateTime(ts: string): string {
  if (!ts) return '—';
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts;
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}
