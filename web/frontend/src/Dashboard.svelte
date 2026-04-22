<script lang="ts">
  import { onMount, onDestroy, tick } from 'svelte';
  import { Chart } from 'chart.js';
  import zoomPlugin from 'chartjs-plugin-zoom';
  import { getDates, getDataRange, getHealth, getBase, getRunStatus, getHistory, getExportCsvBlob, getSummaryCsvBlob, runTestNow } from './lib/api';

  Chart.register(zoomPlugin);
  import { formatValue, formatDate, formatDateShort, formatDateTimeShort } from './lib/format';
  import { loading } from './lib/stores';
  import type { SpeedtestPoint, IperfPoint, HistoryResponse, ChartSpan, DataRangeResponse } from './lib/api';

  export let onToast: (msg: string, type?: 'success' | 'error') => void = () => {};
  /** When false (landing page), hide Run test now and Download CSV. */
  export let showAdminActions = true;
  /** When set, show data for this remote node (probe_id) only. */
  export let probeId: string | undefined = undefined;

  let dates: string[] = [];
  let selectedDate = '';
  let speedtestData: Record<string, SpeedtestPoint[]> = {};
  let iperfData: Record<string, IperfPoint[]> = {};
  let connected = false;
  let connectionError = '';
  let datesLoading = true;
  let datesError = '';
  let runNowLoading = false;
  let runNowPollId: ReturnType<typeof setInterval> | null = null;
  let historyData: HistoryResponse = { speedtest: [], iperf: [] };
  let historyLoading = false;
  let historyDays = 30;
  /** Explains how trend charts are aggregated (daily / 6h / per-run). */
  let trendAggHint = '';
  /** Main charts: window ending at selectedDate. */
  let chartSpan: ChartSpan = 'day';
  let rangeMeta: DataRangeResponse['range'] = null;
  let timeRangeFilter: 'full' | '6h' | '12h' = 'full';
  let csvDownloading = false;
  let summaryDownloading = false;
  let trendDownloadCanvas: HTMLCanvasElement;
  let trendUploadCanvas: HTMLCanvasElement;
  let trendLatencyCanvas: HTMLCanvasElement;
  let trendIperfCanvas: HTMLCanvasElement;
  let trendDownloadChart: Chart | null = null;
  let trendUploadChart: Chart | null = null;
  let trendLatencyChart: Chart | null = null;
  let trendIperfChart: Chart | null = null;
  /* Modern palette: distinct, accessible colors for time-series (2–3px lines, gradient fill) */
  const COLORS = ['#2563eb', '#059669', '#7c3aed', '#dc2626', '#ea580c', '#0891b2', '#65a30d', '#4f46e5', '#be185d', '#0d9488'];

  /** Hex to rgba for gradient stops (e.g. #2563eb -> rgba(37,99,235,0.2)) */
  function hexToRgba(hex: string, alpha: number): string {
    const m = hex.match(/^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i);
    if (!m) return hex;
    const r = parseInt(m[1], 16);
    const g = parseInt(m[2], 16);
    const b = parseInt(m[3], 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }

  let downloadCanvas: HTMLCanvasElement;
  let uploadCanvas: HTMLCanvasElement;
  let latencyCanvas: HTMLCanvasElement;
  let iperfCanvas: HTMLCanvasElement;
  let downloadChartInst: Chart | null = null;
  let uploadChartInst: Chart | null = null;
  let latencyChartInst: Chart | null = null;
  let iperfChartInst: Chart | null = null;

  /** Today as YYYYMMDD for extend-to-now check */
  function todayYmd(): string {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}${m}${day}`;
  }

  function parseYmd(ymd: string): Date {
    return new Date(
      parseInt(ymd.slice(0, 4), 10),
      parseInt(ymd.slice(4, 6), 10) - 1,
      parseInt(ymd.slice(6, 8), 10)
    );
  }

  function toYmd(d: Date): string {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}${m}${day}`;
  }

  function addDaysYmd(ymd: string, deltaDays: number): string {
    const d = parseYmd(ymd);
    d.setDate(d.getDate() + deltaDays);
    return toYmd(d);
  }

  /** Inclusive list of YYYYMMDD from fromYmd through toYmd. */
  function enumerateYmdRange(fromYmd: string, toYmd: string): string[] {
    const out: string[] = [];
    const cur = parseYmd(fromYmd);
    const end = parseYmd(toYmd);
    while (cur <= end) {
      out.push(toYmd(cur));
      cur.setDate(cur.getDate() + 1);
    }
    return out;
  }

  function chartSpanStepDays(s: ChartSpan): number {
    if (s === 'day') return 1;
    if (s === 'week') return 7;
    if (s === 'month') return 30;
    return 365;
  }

  function avgNums(nums: number[]): number | null {
    if (!nums.length) return null;
    return nums.reduce((a, b) => a + b, 0) / nums.length;
  }

  /** Filter data to time window: full day, or last 6h/12h of selected day (or from now if today). */
  function filterByTimeRange<T extends { timestamp?: string | null }>(
    data: Record<string, T[]>,
    selectedDate: string,
    range: 'full' | '6h' | '12h'
  ): Record<string, T[]> {
    if (range === 'full') return data;
    const isToday = selectedDate === todayYmd();
    const now = Date.now();
    const ms = range === '6h' ? 6 * 60 * 60 * 1000 : 12 * 60 * 60 * 1000;
    let minMs: number;
    let maxMs: number;
    if (isToday) {
      maxMs = now;
      minMs = now - ms;
    } else {
      const [y, m, d] = [selectedDate.slice(0, 4), selectedDate.slice(4, 6), selectedDate.slice(6, 8)];
      const endOfDay = new Date(parseInt(y, 10), parseInt(m, 10) - 1, parseInt(d, 10), 23, 59, 59, 999).getTime();
      maxMs = endOfDay;
      minMs = endOfDay - ms;
    }
    const out: Record<string, T[]> = {};
    for (const site of Object.keys(data)) {
      const points = (data[site] || []).filter((p) => {
        const t = p.timestamp ? new Date(p.timestamp).getTime() : NaN;
        return !Number.isNaN(t) && t >= minMs && t <= maxMs;
      });
      if (points.length) out[site] = points;
    }
    return out;
  }

  /** Floor to local hour for bucketing frequent runs into readable slots. */
  function floorToLocalHourMs(ts: string): number | null {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return null;
    d.setMinutes(0, 0, 0);
    d.setSeconds(0, 0);
    d.setMilliseconds(0);
    return d.getTime();
  }

  /** Average multiple runs per hour so hourly cron does not produce 24 jaggy points. */
  function buildSpeedtestOverTimeHourly(
    data: Record<string, SpeedtestPoint[]>,
    key: 'download_bps' | 'upload_bps' | 'latency_ms',
    extendToNow: boolean
  ) {
    const sites = Object.keys(data).filter((site) => (data[site] || []).length > 0);
    const hourKeys = new Set<string>();
    sites.forEach((site) => {
      (data[site] || []).forEach((p) => {
        const ts = p.timestamp && String(p.timestamp).trim();
        if (!ts) return;
        const ms = floorToLocalHourMs(ts);
        if (ms != null) hourKeys.add(String(ms));
      });
    });
    if (extendToNow) {
      const nowMs = floorToLocalHourMs(new Date().toISOString());
      if (nowMs != null) hourKeys.add(String(nowMs));
    }
    const sorted = Array.from(hourKeys)
      .map((k) => Number(k))
      .filter((n) => !Number.isNaN(n))
      .sort((a, b) => a - b);
    const labels = sorted.map((ms) => formatDateTimeShort(new Date(ms).toISOString()));
    const datasets = sites.map((site, i) => {
      const sums: Record<string, { sum: number; n: number }> = {};
      (data[site] || []).forEach((p) => {
        const ts = p.timestamp && String(p.timestamp).trim();
        if (!ts) return;
        const ms = floorToLocalHourMs(ts);
        if (ms == null) return;
        const k = String(ms);
        const v = (p as unknown as Record<string, number>)[key];
        if (v == null || typeof v !== 'number') return;
        if (!sums[k]) sums[k] = { sum: 0, n: 0 };
        sums[k].sum += v;
        sums[k].n += 1;
      });
      let values = sorted.map((ms) => {
        const s = sums[String(ms)];
        return s && s.n > 0 ? s.sum / s.n : null;
      });
      if (extendToNow && values.length > 0) {
        const lastKnown = [...values].reverse().find((v) => v != null);
        if (lastKnown != null) values[values.length - 1] = lastKnown;
      }
      return {
        label: site,
        data: values,
        borderColor: COLORS[i % COLORS.length],
        backgroundColor: COLORS[i % COLORS.length] + '30',
        borderWidth: 3,
        fill: true,
        tension: 0.25,
        pointRadius: 0,
        pointHoverRadius: 6,
        showLine: true,
        spanGaps: true,
      };
    });
    return { labels, datasets };
  }

  /** Combined over time: all sites, x = sorted timestamps. If extendToNow (and viewing today), add current time so line holds last speed to now. */
  function buildSpeedtestOverTime(
    data: Record<string, SpeedtestPoint[]>,
    key: 'download_bps' | 'upload_bps' | 'latency_ms',
    extendToNow = false
  ) {
    const sites = Object.keys(data).filter((site) => (data[site] || []).length > 0);
    if (sites.length === 0) return { labels: [] as string[], datasets: [] };

    const allPoints = sites.flatMap((site) => (data[site] || []).map((p) => ({ ...p, site })));
    const hasTimestamps = allPoints.some((p) => p.timestamp && String(p.timestamp).trim());

    if (hasTimestamps) {
      const timeSet = new Set<string>();
      allPoints.forEach((p) => {
        if (p.timestamp && String(p.timestamp).trim()) timeSet.add(p.timestamp);
      });
      /* Many runs in one day (e.g. hourly cron): one point per local hour (average). */
      if (timeSet.size > 14 || allPoints.length > 14) {
        return buildSpeedtestOverTimeHourly(data, key, extendToNow);
      }
      if (extendToNow) timeSet.add(new Date().toISOString());
      const labels = Array.from(timeSet).sort();
      const displayLabels = labels.map(formatDateTimeShort);
      const datasets = sites.map((site, i) => {
        const valueByTime: Record<string, number> = {};
        (data[site] || []).forEach((p) => {
          const v = (p as unknown as Record<string, number>)[key];
          if (p.timestamp != null && v != null) valueByTime[p.timestamp] = v;
        });
        let values = labels.map((t) => valueByTime[t] ?? null);
        if (extendToNow && values.length > 0) {
          const lastKnown = [...values].reverse().find((v) => v != null);
          if (lastKnown != null) values[values.length - 1] = lastKnown;
        }
        return {
          label: site,
          data: values,
          borderColor: COLORS[i % COLORS.length],
          backgroundColor: COLORS[i % COLORS.length] + '30',
          borderWidth: 3,
          fill: true,
          tension: 0.2,
          pointRadius: 0,
          pointHoverRadius: 6,
          showLine: true,
          spanGaps: true,
        };
      });
      return { labels: displayLabels, datasets };
    }

    // No timestamps: use Run 1, Run 2, ... so graph still draws
    const maxLen = Math.max(0, ...sites.map((k) => (data[k] || []).length));
    const runLabels = Array.from({ length: maxLen }, (_, i) => `Run ${i + 1}`);
    const datasets = sites.map((site, i) => {
      const vals = (data[site] || []).map((p) => (p as unknown as Record<string, number>)[key]);
      const padded = [...vals, ...Array(maxLen - vals.length).fill(null)];
      return {
        label: site,
        data: padded,
        borderColor: COLORS[i % COLORS.length],
        backgroundColor: COLORS[i % COLORS.length] + '30',
        borderWidth: 3,
        fill: true,
        tension: 0,
        pointRadius: 0,
        pointHoverRadius: 6,
        showLine: true,
        spanGaps: true,
      };
    });
    return { labels: runLabels, datasets };
  }

  function buildIperfOverTimeHourly(data: Record<string, IperfPoint[]>, extendToNow: boolean) {
    const sites = Object.keys(data).filter((k) => (data[k] || []).length > 0);
    const hourKeys = new Set<string>();
    sites.forEach((site) => {
      (data[site] || []).forEach((p) => {
        const ts = p.timestamp && String(p.timestamp).trim();
        if (!ts) return;
        const ms = floorToLocalHourMs(ts);
        if (ms != null) hourKeys.add(String(ms));
      });
    });
    if (extendToNow) {
      const nowMs = floorToLocalHourMs(new Date().toISOString());
      if (nowMs != null) hourKeys.add(String(nowMs));
    }
    const sorted = Array.from(hourKeys)
      .map((k) => Number(k))
      .filter((n) => !Number.isNaN(n))
      .sort((a, b) => a - b);
    const labels = sorted.map((ms) => formatDateTimeShort(new Date(ms).toISOString()));
    const datasets = sites.map((site, i) => {
      const sums: Record<string, { sum: number; n: number }> = {};
      (data[site] || []).forEach((p) => {
        const ts = p.timestamp && String(p.timestamp).trim();
        if (!ts) return;
        const ms = floorToLocalHourMs(ts);
        if (ms == null) return;
        const k = String(ms);
        if (p.bits_per_sec == null) return;
        if (!sums[k]) sums[k] = { sum: 0, n: 0 };
        sums[k].sum += p.bits_per_sec;
        sums[k].n += 1;
      });
      let values = sorted.map((ms) => {
        const s = sums[String(ms)];
        return s && s.n > 0 ? s.sum / s.n : null;
      });
      if (extendToNow && values.length > 0) {
        const lastKnown = [...values].reverse().find((v) => v != null);
        if (lastKnown != null) values[values.length - 1] = lastKnown;
      }
      return {
        label: site,
        data: values,
        borderColor: COLORS[i % COLORS.length],
        backgroundColor: COLORS[i % COLORS.length] + '30',
        borderWidth: 3,
        fill: true,
        tension: 0.25,
        pointRadius: 0,
        pointHoverRadius: 6,
        showLine: true,
        spanGaps: true,
      };
    });
    return { labels, datasets };
  }

  /** Combined over time: all iperf series. If extendToNow (viewing today), line holds last value to now. */
  function buildIperfOverTime(data: Record<string, IperfPoint[]>, extendToNow = false) {
    const sites = Object.keys(data).filter((k) => (data[k] || []).length > 0);
    const allPoints = sites.flatMap((site) => (data[site] || []).map((p) => ({ ...p, site })));
    const hasTimestamps = allPoints.some((p) => p.timestamp);
    if (hasTimestamps) {
      const timeSet = new Set<string>();
      allPoints.forEach((p) => {
        if (p.timestamp) timeSet.add(p.timestamp);
      });
      if (timeSet.size > 14 || allPoints.length > 14) {
        return buildIperfOverTimeHourly(data, extendToNow);
      }
      if (extendToNow) timeSet.add(new Date().toISOString());
      const labels = Array.from(timeSet).sort();
      const displayLabels = labels.map(formatDateTimeShort);
      const datasets = sites.map((site, i) => {
        const valueByTime: Record<string, number> = {};
        (data[site] || []).forEach((p) => {
          if (p.timestamp != null && p.bits_per_sec != null) valueByTime[p.timestamp] = p.bits_per_sec;
        });
        let values = labels.map((t) => valueByTime[t] ?? null);
        if (extendToNow && values.length > 0) {
          const lastKnown = [...values].reverse().find((v) => v != null);
          if (lastKnown != null) values[values.length - 1] = lastKnown;
        }
        return {
          label: site,
          data: values,
          borderColor: COLORS[i % COLORS.length],
          backgroundColor: COLORS[i % COLORS.length] + '30',
          borderWidth: 3,
          fill: true,
          tension: 0.2,
          pointRadius: 0,
          pointHoverRadius: 6,
          showLine: true,
          spanGaps: true,
        };
      });
      return { labels: displayLabels, datasets };
    }
    const maxLen = Math.max(0, ...sites.map((k) => (data[k] || []).length));
    const runLabels = Array.from({ length: maxLen }, (_, i) => `Run ${i + 1}`);
    const datasets = sites.map((site, i) => {
      const vals = (data[site] || []).map((p) => p.bits_per_sec);
      const padded = [...vals, ...Array(maxLen - vals.length).fill(null)];
      return {
        label: site,
        data: padded,
        borderColor: COLORS[i % COLORS.length],
        backgroundColor: COLORS[i % COLORS.length] + '30',
        borderWidth: 3,
        fill: true,
        tension: 0,
        pointRadius: 0,
        pointHoverRadius: 6,
        showLine: true,
        spanGaps: true,
      };
    });
    return { labels: runLabels, datasets };
  }

  /** Main charts for week/month/year: one point per calendar day (mean of runs that day). */
  function buildMainChartDailySpeedtest(
    data: Record<string, SpeedtestPoint[]>,
    key: 'download_bps' | 'upload_bps' | 'latency_ms',
    fromYmd: string,
    toYmd: string
  ) {
    const sites = Object.keys(data).filter((site) => (data[site] || []).length > 0);
    if (!sites.length) return { labels: [] as string[], datasets: [] as ReturnType<typeof buildSpeedtestOverTime>['datasets'] };
    const allDays = enumerateYmdRange(fromYmd, toYmd);
    const labels = allDays.map(formatDateShort);
    const datasets = sites.map((site, i) => {
      const byDay: Record<string, number[]> = {};
      (data[site] || []).forEach((p) => {
        const ld = p.log_date;
        if (!ld || ld.length < 8) return;
        const v = (p as unknown as Record<string, number>)[key];
        if (v == null || typeof v !== 'number') return;
        if (!byDay[ld]) byDay[ld] = [];
        byDay[ld].push(v);
      });
      return {
        label: site,
        data: allDays.map((d) => {
          const arr = byDay[d];
          return arr?.length ? avgNums(arr) : null;
        }),
        borderColor: COLORS[i % COLORS.length],
        backgroundColor: COLORS[i % COLORS.length] + '30',
        borderWidth: 3,
        fill: true,
        tension: 0.35,
        pointRadius: chartSpan === 'year' ? 0 : 2,
        pointHoverRadius: 6,
        showLine: true,
        spanGaps: true,
      };
    });
    return { labels, datasets };
  }

  function buildMainChartDailyIperf(data: Record<string, IperfPoint[]>, fromYmd: string, toYmd: string) {
    const sites = Object.keys(data).filter((k) => (data[k] || []).length > 0);
    if (!sites.length) return { labels: [] as string[], datasets: [] as ReturnType<typeof buildIperfOverTime>['datasets'] };
    const allDays = enumerateYmdRange(fromYmd, toYmd);
    const labels = allDays.map(formatDateShort);
    const datasets = sites.map((site, i) => {
      const byDay: Record<string, number[]> = {};
      (data[site] || []).forEach((p) => {
        const ld = p.log_date;
        if (!ld || ld.length < 8 || p.bits_per_sec == null) return;
        if (!byDay[ld]) byDay[ld] = [];
        byDay[ld].push(p.bits_per_sec);
      });
      return {
        label: site,
        data: allDays.map((d) => {
          const arr = byDay[d];
          return arr?.length ? avgNums(arr) : null;
        }),
        borderColor: COLORS[i % COLORS.length],
        backgroundColor: COLORS[i % COLORS.length] + '30',
        borderWidth: 3,
        fill: true,
        tension: 0.35,
        pointRadius: chartSpan === 'year' ? 0 : 2,
        pointHoverRadius: 6,
        showLine: true,
        spanGaps: true,
      };
    });
    return { labels, datasets };
  }

  $: filteredSpeedtestData = selectedDate
    ? chartSpan === 'day'
      ? filterByTimeRange(speedtestData, selectedDate, timeRangeFilter)
      : speedtestData
    : speedtestData;
  $: filteredIperfData = selectedDate
    ? chartSpan === 'day'
      ? filterByTimeRange(iperfData, selectedDate, timeRangeFilter)
      : iperfData
    : iperfData;
  $: extendToNow = !!selectedDate && chartSpan === 'day' && selectedDate === todayYmd();
  $: speedtestSites = Object.keys(filteredSpeedtestData).filter((s) => (filteredSpeedtestData[s] || []).length > 0);
  $: iperfSites = Object.keys(filteredIperfData).filter((s) => (filteredIperfData[s] || []).length > 0);
  $: hasSpeedtest = speedtestSites.length > 0;
  $: hasIperf = iperfSites.length > 0;
  $: hasAnyData = hasSpeedtest || hasIperf;
  $: rangeSummary =
    rangeMeta && chartSpan !== 'day'
      ? `${formatDate(rangeMeta.from)} → ${formatDate(rangeMeta.to)}`
      : selectedDate
        ? formatDate(selectedDate)
        : '';
  $: mainChartFootnoteDay =
    'All sites on one timeline. Busy days use one average per local hour. Drag to pan, scroll to zoom.';
  $: mainChartFootnoteRange =
    'One point per calendar day (average of all runs that day). Drag to pan, scroll to zoom.';
  /** Raw points exist for the day, but 6h/12h window removed every point — show a specific message */
  $: speedtestSitesBeforeTimeFilter = selectedDate
    ? Object.keys(speedtestData).filter((s) => (speedtestData[s] || []).length > 0)
    : [];
  $: iperfSitesBeforeTimeFilter = selectedDate
    ? Object.keys(iperfData).filter((s) => (iperfData[s] || []).length > 0)
    : [];
  $: timeFilterExcludesAllSpeedtest =
    chartSpan === 'day' &&
    timeRangeFilter !== 'full' &&
    speedtestSitesBeforeTimeFilter.length > 0 &&
    !hasSpeedtest;
  $: timeFilterExcludesAllIperf =
    chartSpan === 'day' &&
    timeRangeFilter !== 'full' &&
    iperfSitesBeforeTimeFilter.length > 0 &&
    !hasIperf;

  function renderChart(
    canvas: HTMLCanvasElement | undefined,
    labels: string[],
    datasets: { label: string; data: (number | null)[]; borderColor: string; backgroundColor: string; fill: boolean; tension: number; pointRadius: number; pointHoverRadius: number; borderWidth?: number }[],
    metric: string,
    metricLabel: string,
    uiKind: 'day' | 'trend' = 'day'
  ): Chart | null {
    if (!canvas || !datasets.length) return null;
    /* Modern style: vertical gradient fill (line color → transparent), 3px line, no points by default */
    const datasetsWithGradient = datasets.map((ds) => ({
      ...ds,
      borderWidth: ds.borderWidth ?? 3,
      backgroundColor: (context: { chart: Chart }) => {
        const chart = context.chart;
        const { ctx } = chart;
        const ca = chart.chartArea;
        if (!ca) return ds.borderColor;
        const gradient = ctx.createLinearGradient(0, ca.top, 0, ca.bottom);
        gradient.addColorStop(0, hexToRgba(ds.borderColor, 0.22));
        gradient.addColorStop(1, hexToRgba(ds.borderColor, 0));
        return gradient;
      },
    }));
    return new Chart(canvas, {
      type: 'line',
      data: { labels, datasets: datasetsWithGradient },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        elements: { line: { spanGaps: true } },
        datasets: { line: { showLine: true } },
        interaction: { intersect: false, mode: 'index' },
        plugins: {
          legend: {
            position: 'top',
            labels: { font: { size: 13 }, padding: 14, usePointStyle: false },
            onClick(_e: unknown, legendItem: { datasetIndex?: number }, legend: { chart: Chart }) {
              const idx = legendItem.datasetIndex ?? 0;
              const meta = legend.chart.getDatasetMeta(idx);
              meta.hidden = meta.hidden !== true;
              legend.chart.update();
            },
          },
          tooltip: {
            callbacks: { label: (ctx: { dataset: { label?: string }; parsed: { y: number | null } }) => (ctx.dataset.label || '') + ': ' + formatValue(ctx.parsed.y, metric) },
          },
          zoom: {
            zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'x' },
            pan: { enabled: true, mode: 'x' },
            limits: { x: { min: 'original', max: 'original' } },
          },
        },
        scales: {
          x: {
            grid: { display: true, color: 'rgba(0,0,0,0.08)' },
            ticks: {
              maxRotation: uiKind === 'trend' ? 28 : 42,
              minRotation: uiKind === 'trend' ? 0 : 0,
              maxTicksLimit: uiKind === 'trend' ? 12 : 18,
              autoSkip: true,
              autoSkipPadding: 4,
              font: { size: uiKind === 'trend' ? 11 : 12 },
            },
          },
          y: {
            beginAtZero: metric !== 'latency_ms',
            title: { display: true, text: metricLabel, font: { size: 13 } },
            grid: { display: true, color: 'rgba(0,0,0,0.08)' },
            ticks: {
              font: { size: 12 },
              maxTicksLimit: metric === 'latency_ms' ? 8 : 7,
            },
          },
        },
      },
    });
  }

  function resetChartsZoom() {
    for (const ch of [downloadChartInst, uploadChartInst, latencyChartInst, iperfChartInst]) {
      if (ch && typeof (ch as Chart & { resetZoom?: () => void }).resetZoom === 'function') {
        (ch as Chart & { resetZoom: () => void }).resetZoom();
      }
    }
  }

  function doRenderCharts() {
    if (downloadChartInst) { downloadChartInst.destroy(); downloadChartInst = null; }
    if (uploadChartInst) { uploadChartInst.destroy(); uploadChartInst = null; }
    if (latencyChartInst) { latencyChartInst.destroy(); latencyChartInst = null; }
    if (iperfChartInst) { iperfChartInst.destroy(); iperfChartInst = null; }
    const stDay = Object.keys(filteredSpeedtestData).some((s) => (filteredSpeedtestData[s] || []).length > 0);
    const stRange = Object.keys(speedtestData).some((s) => (speedtestData[s] || []).length > 0);
    const ipDay = Object.keys(filteredIperfData).some((s) => (filteredIperfData[s] || []).length > 0);
    const ipRange = Object.keys(iperfData).some((s) => (iperfData[s] || []).length > 0);
    const hasSt = chartSpan === 'day' ? stDay : stRange;
    const hasIp = chartSpan === 'day' ? ipDay : ipRange;
    const chartUi: 'day' | 'trend' = chartSpan === 'day' ? 'day' : 'trend';

    if (downloadCanvas && hasSt) {
      const { labels, datasets } =
        chartSpan === 'day'
          ? buildSpeedtestOverTime(filteredSpeedtestData, 'download_bps', extendToNow)
          : rangeMeta
            ? buildMainChartDailySpeedtest(speedtestData, 'download_bps', rangeMeta.from, rangeMeta.to)
            : { labels: [], datasets: [] };
      if (labels.length && datasets.length) {
        downloadChartInst = renderChart(downloadCanvas, labels, datasets, 'download_bps', 'Download (Mbps)', chartUi);
      }
    }
    if (uploadCanvas && hasSt) {
      const { labels, datasets } =
        chartSpan === 'day'
          ? buildSpeedtestOverTime(filteredSpeedtestData, 'upload_bps', extendToNow)
          : rangeMeta
            ? buildMainChartDailySpeedtest(speedtestData, 'upload_bps', rangeMeta.from, rangeMeta.to)
            : { labels: [], datasets: [] };
      if (labels.length && datasets.length) {
        uploadChartInst = renderChart(uploadCanvas, labels, datasets, 'upload_bps', 'Upload (Mbps)', chartUi);
      }
    }
    if (latencyCanvas && hasSt) {
      const { labels, datasets } =
        chartSpan === 'day'
          ? buildSpeedtestOverTime(filteredSpeedtestData, 'latency_ms', extendToNow)
          : rangeMeta
            ? buildMainChartDailySpeedtest(speedtestData, 'latency_ms', rangeMeta.from, rangeMeta.to)
            : { labels: [], datasets: [] };
      if (labels.length && datasets.length) {
        latencyChartInst = renderChart(latencyCanvas, labels, datasets, 'latency_ms', 'Latency (ms)', chartUi);
      }
    }
    if (iperfCanvas && hasIp) {
      const { labels, datasets } =
        chartSpan === 'day'
          ? buildIperfOverTime(filteredIperfData, extendToNow)
          : rangeMeta
            ? buildMainChartDailyIperf(iperfData, rangeMeta.from, rangeMeta.to)
            : { labels: [], datasets: [] };
      if (labels.length && datasets.length) {
        iperfChartInst = renderChart(iperfCanvas, labels, datasets, 'bits_per_sec', 'Throughput (Mbps)', chartUi);
      }
    }
  }
  async function updateCharts() {
    await tick();
    // Double rAF: canvas must be mounted and laid out before Chart.js reads chartArea (gradients).
    // Avoid requestIdleCallback — it can be delayed indefinitely on a busy tab, leaving charts blank.
    return new Promise<void>((resolve) => {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          doRenderCharts();
          resolve();
        });
      });
    });
  }
  /* Redraw main charts when data, span, filter, or range changes. */
  $: if (selectedDate) {
    filteredSpeedtestData;
    filteredIperfData;
    extendToNow;
    chartSpan;
    rangeMeta;
    speedtestData;
    iperfData;
    void updateCharts();
  }

  async function checkConnection() {
    connectionError = '';
    try {
      const h = await getHealth();
      connected = !!h.ok;
      if (!h.ok) connectionError = h.error || 'Server error';
    } catch (e) {
      connected = false;
      connectionError = e instanceof Error ? e.message : 'Cannot reach server';
    }
  }

  async function loadDatesList(): Promise<string[]> {
    datesError = '';
    datesLoading = true;
    try {
      await checkConnection();
      const r = await getDates();
      dates = r.dates || [];
      if (dates.length && !selectedDate) selectedDate = dates[0];
      return dates;
    } catch (e) {
      dates = [];
      datesError = e instanceof Error ? e.message : 'Failed to load dates';
      return [];
    } finally {
      datesLoading = false;
    }
  }
  async function loadHistory() {
    historyLoading = true;
    try {
      const days = typeof historyDays === 'number' ? historyDays : Number(historyDays) || 30;
      historyData = await getHistory(days, probeId);
      await tick();
      // Double rAF so trend canvas elements are in DOM and laid out
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            renderTrendCharts();
            resolve();
          });
        });
      });
    } catch {
      historyData = { speedtest: [], iperf: [] };
    } finally {
      historyLoading = false;
    }
  }
  /** Sortable x-axis key for history API points (one sample per run, not one per calendar day). */
  function historyTrendSortKey(p: { date: string; timestamp?: string }): string {
    const t = (p.timestamp && String(p.timestamp).trim()) || '';
    if (t) return t;
    const d = p.date;
    if (d && d.length === 8) {
      return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}T12:00:00.000000Z`;
    }
    return d || '';
  }

  function trendMean(nums: number[]): number {
    if (!nums.length) return 0;
    return nums.reduce((a, b) => a + b, 0) / nums.length;
  }

  /** Local 6-hour bucket start (for dense single-day / short-window trends). */
  function sixHourFloorMsFromTrendPoint(p: { date: string; timestamp?: string }): number | null {
    const k = historyTrendSortKey(p);
    const d = new Date(k);
    if (Number.isNaN(d.getTime())) return null;
    const h = Math.floor(d.getHours() / 6) * 6;
    d.setHours(h, 0, 0, 0);
    d.setMinutes(0, 0, 0);
    d.setMilliseconds(0);
    return d.getTime();
  }

  function trendDatasetShell(i: number, tension: number, pointRadius: number) {
    return {
      borderColor: COLORS[i % COLORS.length],
      backgroundColor: COLORS[i % COLORS.length] + '30',
      borderWidth: 3,
      fill: true,
      tension,
      pointRadius,
      pointHoverRadius: 6,
      showLine: true,
      spanGaps: true,
    };
  }

  function renderTrendCharts() {
    trendAggHint = '';
    [trendDownloadChart, trendUploadChart, trendLatencyChart, trendIperfChart].forEach((c) => {
      if (c) c.destroy();
    });
    trendDownloadChart = trendUploadChart = trendLatencyChart = trendIperfChart = null;

    const st = historyData.speedtest;
    const ip = historyData.iperf;
    const hints: string[] = [];

    const speedtestSites = [...new Set(st.map((p) => p.site))];
    const distinctDaysSt = new Set(st.map((p) => p.date)).size;
    const nSt = st.length;

    if (speedtestSites.length && nSt && trendDownloadCanvas) {
      const useDaily = distinctDaysSt >= 2;
      const useSixHour = !useDaily && nSt >= 10;

      const buildDaily = (key: 'download_bps' | 'upload_bps' | 'latency_ms') => {
        const dates = [...new Set(st.map((p) => p.date))].sort();
        const labels = dates.map(formatDateShort);
        return speedtestSites.map((site, i) => {
          const byDay: Record<string, number[]> = {};
          st.filter((p) => p.site === site).forEach((p) => {
            const v = (p as unknown as Record<string, number>)[key];
            if (v != null && typeof v === 'number') {
              if (!byDay[p.date]) byDay[p.date] = [];
              byDay[p.date].push(v);
            }
          });
          return {
            label: site,
            data: dates.map((d) => {
              const arr = byDay[d];
              return arr?.length ? trendMean(arr) : null;
            }),
            ...trendDatasetShell(i, 0.35, 2),
          };
        });
      };

      const buildSixHour = (key: 'download_bps' | 'upload_bps' | 'latency_ms') => {
        const msList = [
          ...new Set(
            st
              .map((p) => sixHourFloorMsFromTrendPoint(p))
              .filter((x): x is number => x != null)
          ),
        ].sort((a, b) => a - b);
        const labels = msList.map((ms) => formatDateTimeShort(new Date(ms).toISOString()));
        const datasets = speedtestSites.map((site, i) => {
          const bucketVals: Record<string, number[]> = {};
          st.filter((p) => p.site === site).forEach((p) => {
            const ms = sixHourFloorMsFromTrendPoint(p);
            if (ms == null) return;
            const v = (p as unknown as Record<string, number>)[key];
            if (v == null || typeof v !== 'number') return;
            const k = String(ms);
            if (!bucketVals[k]) bucketVals[k] = [];
            bucketVals[k].push(v);
          });
          return {
            label: site,
            data: msList.map((ms) => {
              const arr = bucketVals[String(ms)];
              return arr?.length ? trendMean(arr) : null;
            }),
            ...trendDatasetShell(i, 0.3, 2),
          };
        });
        return { labels, datasets };
      };

      const buildPerRun = (key: 'download_bps' | 'upload_bps' | 'latency_ms') => {
        const sortKeys = [...new Set(st.map(historyTrendSortKey))].sort(
          (a, b) => new Date(a).getTime() - new Date(b).getTime()
        );
        const labels = sortKeys.map((k) => {
          const ms = new Date(k).getTime();
          return Number.isNaN(ms) ? k : formatDateTimeShort(k);
        });
        return speedtestSites.map((site, i) => {
          const byKey: Record<string, number> = {};
          st.filter((p) => p.site === site).forEach((p) => {
            const v = (p as unknown as Record<string, number>)[key];
            if (v != null && typeof v === 'number') byKey[historyTrendSortKey(p)] = v;
          });
          return {
            label: site,
            data: sortKeys.map((k) => (k in byKey ? byKey[k] : null)),
            ...trendDatasetShell(i, 0.22, 0),
          };
        });
      };

      let stLabels: string[] = [];
      let dl: ReturnType<typeof buildDaily>;
      let ul: ReturnType<typeof buildDaily>;
      let ll: ReturnType<typeof buildDaily>;

      if (useDaily) {
        stLabels = [...new Set(st.map((p) => p.date))].sort().map(formatDateShort);
        dl = buildDaily('download_bps');
        ul = buildDaily('upload_bps');
        ll = buildDaily('latency_ms');
        hints.push(
          `Speedtest: daily average across ${distinctDaysSt} day(s) (${nSt} run${nSt === 1 ? '' : 's'}).`
        );
      } else if (useSixHour) {
        const six = buildSixHour('download_bps');
        stLabels = six.labels;
        dl = buildSixHour('download_bps').datasets;
        ul = buildSixHour('upload_bps').datasets;
        ll = buildSixHour('latency_ms').datasets;
        hints.push(`Speedtest: 6-hour averages (${nSt} run${nSt === 1 ? '' : 's'} in this window).`);
      } else {
        const sortKeys = [...new Set(st.map(historyTrendSortKey))].sort(
          (a, b) => new Date(a).getTime() - new Date(b).getTime()
        );
        stLabels = sortKeys.map((k) => {
          const ms = new Date(k).getTime();
          return Number.isNaN(ms) ? k : formatDateTimeShort(k);
        });
        dl = buildPerRun('download_bps');
        ul = buildPerRun('upload_bps');
        ll = buildPerRun('latency_ms');
        if (nSt > 1) hints.push(`Speedtest: one point per run (${nSt} total).`);
      }

      trendDownloadChart = renderChart(trendDownloadCanvas, stLabels, dl, 'download_bps', 'Download (Mbps)', 'trend');
      if (trendUploadCanvas) trendUploadChart = renderChart(trendUploadCanvas, stLabels, ul, 'upload_bps', 'Upload (Mbps)', 'trend');
      if (trendLatencyCanvas) trendLatencyChart = renderChart(trendLatencyCanvas, stLabels, ll, 'latency_ms', 'Latency (ms)', 'trend');
    }

    const iperfSitesTr = [...new Set(ip.map((p) => p.site))];
    const distinctDaysIp = new Set(ip.map((p) => p.date)).size;
    const nIp = ip.length;

    if (iperfSitesTr.length && nIp && trendIperfCanvas) {
      const useDaily = distinctDaysIp >= 2;
      const useSixHour = !useDaily && nIp >= 10;

      if (useDaily) {
        const dates = [...new Set(ip.map((p) => p.date))].sort();
        const labels = dates.map(formatDateShort);
        const datasets = iperfSitesTr.map((site, i) => {
          const byDay: Record<string, number[]> = {};
          ip.filter((p) => p.site === site).forEach((p) => {
            if (p.bits_per_sec == null) return;
            if (!byDay[p.date]) byDay[p.date] = [];
            byDay[p.date].push(p.bits_per_sec);
          });
          return {
            label: site,
            data: dates.map((d) => {
              const arr = byDay[d];
              return arr?.length ? trendMean(arr) : null;
            }),
            ...trendDatasetShell(i, 0.35, 2),
          };
        });
        trendIperfChart = renderChart(trendIperfCanvas, labels, datasets, 'bits_per_sec', 'Throughput (Mbps)', 'trend');
        hints.push(
          `iperf3: daily average across ${distinctDaysIp} day(s) (${nIp} run${nIp === 1 ? '' : 's'}).`
        );
      } else if (useSixHour) {
        const msList = [
          ...new Set(
            ip
              .map((p) => sixHourFloorMsFromTrendPoint(p))
              .filter((x): x is number => x != null)
          ),
        ].sort((a, b) => a - b);
        const labels = msList.map((ms) => formatDateTimeShort(new Date(ms).toISOString()));
        const datasets = iperfSitesTr.map((site, i) => {
          const bucketVals: Record<string, number[]> = {};
          ip.filter((p) => p.site === site).forEach((p) => {
            const ms = sixHourFloorMsFromTrendPoint(p);
            if (ms == null || p.bits_per_sec == null) return;
            const k = String(ms);
            if (!bucketVals[k]) bucketVals[k] = [];
            bucketVals[k].push(p.bits_per_sec);
          });
          return {
            label: site,
            data: msList.map((ms) => {
              const arr = bucketVals[String(ms)];
              return arr?.length ? trendMean(arr) : null;
            }),
            ...trendDatasetShell(i, 0.3, 2),
          };
        });
        trendIperfChart = renderChart(trendIperfCanvas, labels, datasets, 'bits_per_sec', 'Throughput (Mbps)', 'trend');
        hints.push(`iperf3: 6-hour averages (${nIp} run${nIp === 1 ? '' : 's'}).`);
      } else {
        const sortKeys = [...new Set(ip.map(historyTrendSortKey))].sort(
          (a, b) => new Date(a).getTime() - new Date(b).getTime()
        );
        const labels = sortKeys.map((k) => {
          const ms = new Date(k).getTime();
          return Number.isNaN(ms) ? k : formatDateTimeShort(k);
        });
        const datasets = iperfSitesTr.map((site, i) => {
          const byKey: Record<string, number> = {};
          ip.filter((p) => p.site === site).forEach((p) => {
            if (p.bits_per_sec != null) byKey[historyTrendSortKey(p)] = p.bits_per_sec;
          });
          return {
            label: site,
            data: sortKeys.map((k) => (k in byKey ? byKey[k] : null)),
            ...trendDatasetShell(i, 0.22, 0),
          };
        });
        trendIperfChart = renderChart(trendIperfCanvas, labels, datasets, 'bits_per_sec', 'Throughput (Mbps)', 'trend');
        if (nIp > 1) hints.push(`iperf3: one point per run (${nIp} total).`);
      }
    }

    trendAggHint = hints.join(' ');
  }

  async function loadData() {
    if (!selectedDate) {
      speedtestData = {};
      iperfData = {};
      rangeMeta = null;
      return;
    }
    loading.set(true);
    try {
      const r = await getDataRange(selectedDate, chartSpan, probeId);
      speedtestData = r.speedtest || {};
      iperfData = r.iperf || {};
      rangeMeta = r.range;
    } catch {
      speedtestData = {};
      iperfData = {};
      rangeMeta = null;
    } finally {
      loading.set(false);
    }
  }

  function shiftChartWindow(direction: -1 | 1) {
    if (!selectedDate) return;
    selectedDate = addDaysYmd(selectedDate, chartSpanStepDays(chartSpan) * direction);
  }

  function stopRunNowPoll() {
    if (runNowPollId != null) {
      clearInterval(runNowPollId);
      runNowPollId = null;
    }
  }

  async function downloadCsv() {
    if (!selectedDate || csvDownloading) return;
    csvDownloading = true;
    try {
      const blob = await getExportCsvBlob(selectedDate);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `netperf-${selectedDate}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      onToast('CSV downloaded.');
    } catch (e) {
      onToast(e instanceof Error ? e.message : 'Download failed', 'error');
    } finally {
      csvDownloading = false;
    }
  }

  async function downloadSummaryCsv() {
    if (summaryDownloading) return;
    summaryDownloading = true;
    try {
      const to = new Date();
      const from = new Date(to);
      from.setDate(from.getDate() - 30);
      const pad = (n: number) => (n < 10 ? '0' + n : String(n));
      const fromStr = `${from.getFullYear()}${pad(from.getMonth() + 1)}${pad(from.getDate())}`;
      const toStr = `${to.getFullYear()}${pad(to.getMonth() + 1)}${pad(to.getDate())}`;
      const blob = await getSummaryCsvBlob(fromStr, toStr);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `netperf-summary-${fromStr}-${toStr}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      onToast('Summary CSV downloaded (last 30 days).');
    } catch (e) {
      onToast(e instanceof Error ? e.message : 'Download failed', 'error');
    } finally {
      summaryDownloading = false;
    }
  }

  async function handleRunNow() {
    if (runNowLoading) return;
    runNowLoading = true;
    stopRunNowPoll();
    try {
      const r = await runTestNow();
      if (!r.ok) {
        onToast(r.error || 'Run test now failed.', 'error');
        runNowLoading = false;
        return;
      }
    } catch (e) {
      onToast(e instanceof Error ? e.message : 'Run test now failed (login as admin, or check server logs).', 'error');
      runNowLoading = false;
      return;
    }
    let seenRunning = false;
    let pollCount = 0;
    const maxPolls = 90;
    runNowPollId = setInterval(async () => {
      pollCount += 1;
      try {
        const st = await getRunStatus();
        if (st.running) seenRunning = true;
        if (seenRunning && !st.running) {
          stopRunNowPoll();
          runNowLoading = false;
          onToast('Test finished. Refreshing data.');
          const latestDates = await loadDatesList();
          if (latestDates.length) selectedDate = latestDates[0];
          await loadData();
          loadHistory();
          return;
        }
        if (pollCount >= maxPolls) {
          stopRunNowPoll();
          runNowLoading = false;
          onToast(seenRunning ? 'Stopped polling.' : 'Run did not report progress. Check /var/log/netperf/run-now-last.log on the server (sudo / scripts).', seenRunning ? 'success' : 'error');
        }
      } catch {
        if (pollCount >= maxPolls) {
          stopRunNowPoll();
          runNowLoading = false;
        }
      }
    }, 2000);
  }

  /** Refetch when date, span, or node changes. */
  $: if (selectedDate) {
    chartSpan;
    probeId;
    void loadData();
  }
  /** Trends: reload when node or day range changes (historyDays may be string from the days select). */
  $: {
    probeId;
    historyDays;
    void loadHistory();
  }

  onMount(() => {
    loadDatesList();
  });
  onDestroy(() => {
    stopRunNowPoll();
    [downloadChartInst, uploadChartInst, latencyChartInst, iperfChartInst, trendDownloadChart, trendUploadChart, trendLatencyChart, trendIperfChart].forEach((c) => { if (c) c.destroy(); });
  });
</script>

<div class="dashboard">
  {#if connectionError}
    <div class="alert alert-danger d-flex align-items-center justify-content-between flex-wrap gap-2" role="alert">
      <span><strong>Not connected:</strong> {connectionError}. Check the server and URL (e.g. https://your-server/netperf/).</span>
      <button type="button" class="btn btn-sm btn-outline-danger" on:click={loadDatesList}>Retry</button>
    </div>
  {/if}

  <div class="date-bar card mb-3">
    <div class="card-body py-2">
      <div class="d-flex flex-wrap align-items-center gap-2">
        <label for="dashboard-span" class="form-label mb-0 small text-muted">View</label>
        <select
          id="dashboard-span"
          class="form-select form-select-sm"
          style="max-width: 100px"
          bind:value={chartSpan}
          disabled={datesLoading}
          title="Day = single calendar day. Week/Month/Year = window ending on the date below."
        >
          <option value="day">Day</option>
          <option value="week">Week</option>
          <option value="month">Month</option>
          <option value="year">Year</option>
        </select>
        <label for="dashboard-date" class="form-label mb-0 small text-muted ms-1">End date</label>
        <select id="dashboard-date" class="form-select form-select-sm" style="max-width:140px" bind:value={selectedDate} disabled={datesLoading}>
          <option value="">{datesLoading ? 'Loading…' : 'Select date…'}</option>
          {#each dates as d}
            <option value={d}>{formatDate(d)}</option>
          {/each}
        </select>
        {#if selectedDate}
          <div class="btn-group btn-group-sm" role="group" aria-label="Shift window">
            <button type="button" class="btn btn-outline-secondary" on:click={() => shiftChartWindow(-1)} title="Earlier">←</button>
            <button type="button" class="btn btn-outline-secondary" on:click={() => shiftChartWindow(1)} title="Later">→</button>
          </div>
          {#if rangeSummary}
            <span class="small text-muted text-nowrap" title="Current chart window">{rangeSummary}</span>
          {/if}
        {/if}
        {#if selectedDate && chartSpan === 'day'}
          <label for="dashboard-time-range" class="form-label mb-0 small text-muted ms-2">Slice</label>
          <select id="dashboard-time-range" class="form-select form-select-sm" style="max-width:120px" bind:value={timeRangeFilter}>
            <option value="full">Full day</option>
            <option value="12h">Last 12 hours</option>
            <option value="6h">Last 6 hours</option>
          </select>
          <button type="button" class="btn btn-sm btn-outline-secondary ms-1" on:click={resetChartsZoom} title="Reset pan/zoom to full view">Reset zoom</button>
        {/if}
        {#if showAdminActions}
          <button type="button" class="btn btn-sm btn-primary" on:click={handleRunNow} disabled={runNowLoading} title="Run all configured Speedtest and iperf3 tests now (results in 1–2 min)">
            {#if runNowLoading}
              <span class="spinner-border spinner-border-sm me-1" role="status"></span>
              Running…
            {:else}
              <i class="bi bi-play-fill me-1"></i>
              Run all tests now
            {/if}
          </button>
        {/if}
        <button type="button" class="btn btn-sm btn-outline-secondary" on:click={loadDatesList} disabled={datesLoading}>Refresh</button>
        {#if showAdminActions}
          <button type="button" class="btn btn-sm btn-outline-secondary" on:click={downloadCsv} disabled={!selectedDate || csvDownloading} title="Download full data (speedtest + iperf) as CSV">
            {#if csvDownloading}
              <span class="spinner-border spinner-border-sm me-1" role="status"></span>
            {:else}
              <i class="bi bi-download me-1"></i>
            {/if}
            Download CSV
          </button>
          <button type="button" class="btn btn-sm btn-outline-secondary" on:click={downloadSummaryCsv} disabled={summaryDownloading} title="Per-site min/max/avg for last 30 days">
            {#if summaryDownloading}
              <span class="spinner-border spinner-border-sm me-1" role="status"></span>
            {/if}
            Download summary (30d)
          </button>
        {/if}
        {#if selectedDate && hasAnyData}
          <span class="small text-muted ms-2">Speedtest: {speedtestSites.length} site(s) · iperf: {iperfSites.length} site(s)</span>
        {/if}
      </div>
      {#if selectedDate && hasAnyData && connected}
        <p class="small text-muted mb-0 mt-1">For hourly tests, start the <strong>Scheduler</strong> (Scheduler page).</p>
      {/if}
      {#if selectedDate && connected && speedtestSitesBeforeTimeFilter.length === 0 && iperfSitesBeforeTimeFilter.length > 0}
        <p class="small text-warning mb-0 mt-2" role="status">
          iperf3 has data for this day but Speedtest does not. Re-run <strong>install</strong> or <strong>Setup → Install dependencies</strong> so <code class="small">/usr/local/bin/speedtest</code> exists (install links it when the package only provides <code class="small">/usr/bin/speedtest</code>). Redeploy <code class="small">/bin/netperf-tester</code>, then check <code class="small">/var/log/netperf/&lt;date&gt;/speedtest.stderr.log</code> if it persists.
        </p>
      {/if}
      {#if datesError}
        <p class="small text-danger mb-0 mt-2">{datesError}</p>
      {:else if !datesLoading && dates.length === 0 && connected}
        <p class="small text-muted mb-0 mt-2">No test data yet. Click <strong>Run test now</strong> or enable the <strong>Scheduler</strong> to collect data.</p>
      {/if}
    </div>
  </div>

  <!-- Speedtest: 3 separate graphs -->
  <section class="card mb-4 speedtest-card">
    <div class="card-header text-dark">Speedtest: Download</div>
    <div class="card-body">
      {#if !selectedDate}
        <div class="chart-placeholder chart-fixed"><p class="text-muted mb-0">Select a date above to load graphs.</p></div>
      {:else if timeFilterExcludesAllSpeedtest}
        <div class="chart-placeholder chart-fixed"><p class="text-muted mb-0">No Speedtest points in this time window. Set <strong>Range</strong> to <strong>Full day</strong>, or choose last 6h/12h so it includes when tests ran.</p></div>
      {:else if !hasSpeedtest}
        <div class="chart-placeholder chart-fixed"><p class="text-muted mb-0">{chartSpan === 'day' ? 'No Speedtest data for this date.' : 'No Speedtest data in this window.'} Use <strong>Run test now</strong> or the <strong>Scheduler</strong> to run tests.</p></div>
      {:else}
        <div class="chart-wrap chart-fixed"><canvas bind:this={downloadCanvas}></canvas></div>
        <p class="small text-muted mt-2 mb-0">{chartSpan === 'day' ? mainChartFootnoteDay : mainChartFootnoteRange}</p>
      {/if}
    </div>
  </section>
  <section class="card mb-4 speedtest-card">
    <div class="card-header text-dark">Speedtest: Upload</div>
    <div class="card-body">
      {#if !selectedDate}
        <div class="chart-placeholder chart-fixed"><p class="text-muted mb-0">Select a date above to load graphs.</p></div>
      {:else if timeFilterExcludesAllSpeedtest}
        <div class="chart-placeholder chart-fixed"><p class="text-muted mb-0">No data in this time window — try <strong>Full day</strong>.</p></div>
      {:else if !hasSpeedtest}
        <div class="chart-placeholder chart-fixed"><p class="text-muted mb-0">{chartSpan === 'day' ? 'No Speedtest data for this date.' : 'No Speedtest data in this window.'}</p></div>
      {:else}
        <div class="chart-wrap chart-fixed"><canvas bind:this={uploadCanvas}></canvas></div>
        <p class="small text-muted mt-2 mb-0">{chartSpan === 'day' ? 'Same timeline as download — hourly smoothing when busy. Click legend to toggle.' : mainChartFootnoteRange}</p>
      {/if}
    </div>
  </section>
  <section class="card mb-4 speedtest-card">
    <div class="card-header text-dark">Speedtest: Latency</div>
    <div class="card-body">
      {#if !selectedDate}
        <div class="chart-placeholder chart-fixed"><p class="text-muted mb-0">Select a date above to load graphs.</p></div>
      {:else if timeFilterExcludesAllSpeedtest}
        <div class="chart-placeholder chart-fixed"><p class="text-muted mb-0">No data in this time window — try <strong>Full day</strong>.</p></div>
      {:else if !hasSpeedtest}
        <div class="chart-placeholder chart-fixed"><p class="text-muted mb-0">{chartSpan === 'day' ? 'No Speedtest data for this date.' : 'No Speedtest data in this window.'}</p></div>
      {:else}
        <div class="chart-wrap chart-fixed"><canvas bind:this={latencyCanvas}></canvas></div>
        <p class="small text-muted mt-2 mb-0">{chartSpan === 'day' ? 'Same timeline — hourly smoothing when busy. Click legend to toggle.' : mainChartFootnoteRange}</p>
      {/if}
    </div>
  </section>

  <!-- iperf3: always show section -->
  <section class="card mb-4">
    <div class="card-header text-dark">iperf3 throughput</div>
    <div class="card-body">
      <p class="small text-muted mb-2">
        End-of-test throughput per run.
        {#if chartSpan === 'day'}
          Busy days are averaged per local hour like Speedtest.
        {:else}
          Shown as one value per calendar day (daily mean).
        {/if}
        Use <strong>Download CSV</strong> for raw intervals.
      </p>
      {#if !selectedDate}
        <div class="chart-placeholder">
          <p class="text-muted mb-0">Select a date above to load graphs.</p>
        </div>
      {:else if timeFilterExcludesAllIperf}
        <div class="chart-placeholder">
          <p class="text-muted mb-0">No iperf3 points in this time window. Set <strong>Range</strong> to <strong>Full day</strong>.</p>
        </div>
      {:else if !hasIperf}
        <div class="chart-placeholder">
          <p class="text-muted mb-0">{chartSpan === 'day' ? 'No iperf3 data for this date.' : 'No iperf3 data in this window.'} Add servers in <strong>Settings</strong>, then <strong>Run test now</strong> or the <strong>Scheduler</strong>.</p>
        </div>
      {:else}
        <div class="chart-single">
          <div class="chart-wrap chart-wrap-lg">
            <canvas bind:this={iperfCanvas}></canvas>
          </div>
        </div>
        <p class="small text-muted mt-2 mb-0">All iperf series on one timeline. Click legend to toggle.</p>
      {/if}
    </div>
  </section>

  <!-- Trend over time: separate fixed cards per metric -->
  <div class="trend-controls card mb-3">
    <div class="card-body py-2 d-flex flex-wrap align-items-center justify-content-between gap-2">
      <div>
        <span class="fw-semibold text-dark">Long-term trend</span>
        <span class="d-block small text-muted">Daily / 6-hour roll-ups of stored tests — independent of the main chart window above.</span>
      </div>
      <div class="d-flex align-items-center gap-2">
        <label for="history-days" class="form-label mb-0 small text-muted">Days back</label>
        <select id="history-days" class="form-select form-select-sm" style="max-width:88px" bind:value={historyDays} on:change={() => loadHistory()}>
          <option value={7}>7</option>
          <option value={14}>14</option>
          <option value={30}>30</option>
          <option value={90}>90</option>
          <option value={180}>180</option>
          <option value={365}>365</option>
        </select>
        <button type="button" class="btn btn-sm btn-outline-secondary" on:click={loadHistory} disabled={historyLoading}>{historyLoading ? 'Loading…' : 'Refresh'}</button>
      </div>
    </div>
    {#if trendAggHint}
      <div class="card-body pt-0 pb-2 px-3 border-top border-light-subtle">
        <p class="small text-muted mb-0">{trendAggHint}</p>
      </div>
    {/if}
  </div>

  <section class="card mb-4 trend-card">
    <div class="card-header text-dark">Trend: Download</div>
    <div class="card-body">
      {#if historyLoading && historyData.speedtest.length === 0}
        <div class="chart-placeholder trend-chart-fixed"><p class="text-muted mb-0">Loading…</p></div>
      {:else if historyData.speedtest.length === 0}
        <div class="chart-placeholder trend-chart-fixed"><p class="text-muted mb-0">No Speedtest history. Run tests to build the trend.</p></div>
      {:else}
        <div class="chart-wrap trend-chart-fixed"><canvas bind:this={trendDownloadCanvas}></canvas></div>
      {/if}
    </div>
  </section>

  <section class="card mb-4 trend-card">
    <div class="card-header text-dark">Trend: Upload</div>
    <div class="card-body">
      {#if historyLoading && historyData.speedtest.length === 0}
        <div class="chart-placeholder trend-chart-fixed"><p class="text-muted mb-0">Loading…</p></div>
      {:else if historyData.speedtest.length === 0}
        <div class="chart-placeholder trend-chart-fixed"><p class="text-muted mb-0">No Speedtest history.</p></div>
      {:else}
        <div class="chart-wrap trend-chart-fixed"><canvas bind:this={trendUploadCanvas}></canvas></div>
      {/if}
    </div>
  </section>

  <section class="card mb-4 trend-card">
    <div class="card-header text-dark">Trend: Latency</div>
    <div class="card-body">
      {#if historyLoading && historyData.speedtest.length === 0}
        <div class="chart-placeholder trend-chart-fixed"><p class="text-muted mb-0">Loading…</p></div>
      {:else if historyData.speedtest.length === 0}
        <div class="chart-placeholder trend-chart-fixed"><p class="text-muted mb-0">No Speedtest history.</p></div>
      {:else}
        <div class="chart-wrap trend-chart-fixed"><canvas bind:this={trendLatencyCanvas}></canvas></div>
      {/if}
    </div>
  </section>

  <section class="card mb-4 trend-card">
    <div class="card-header text-dark">Trend: iperf3 throughput</div>
    <div class="card-body">
      {#if historyLoading && historyData.iperf.length === 0}
        <div class="chart-placeholder trend-chart-fixed"><p class="text-muted mb-0">Loading…</p></div>
      {:else if historyData.iperf.length === 0}
        <div class="chart-placeholder trend-chart-fixed"><p class="text-muted mb-0">No iperf3 history. Add servers in Settings and run tests.</p></div>
      {:else}
        <div class="chart-wrap trend-chart-fixed trend-chart-lg"><canvas bind:this={trendIperfCanvas}></canvas></div>
      {/if}
    </div>
  </section>

</div>

<style>
  .dashboard { padding-bottom: 1rem; }
  .date-bar :global(.card-body) { padding: 0.5rem 1rem; }
  .chart-wrap { position: relative; height: 260px; width: 100%; }
  .chart-wrap-lg { height: 320px; }
  .chart-single { width: 100%; }
  .chart-placeholder { min-height: 220px; display: flex; align-items: center; justify-content: center; }
  .chart-fixed { height: 280px; width: 100%; min-height: 280px; }
  .speedtest-card .chart-placeholder.chart-fixed { min-height: 280px; }
  .trend-chart-fixed { height: 280px; width: 100%; min-height: 280px; }
  .trend-chart-fixed.trend-chart-lg { height: 320px; min-height: 320px; }
  .trend-card .chart-placeholder.trend-chart-fixed { min-height: 280px; }
  :global(.card) { border-radius: var(--radius-lg); }
  :global(.card-header) { font-weight: var(--font-weight-semibold); }
</style>
