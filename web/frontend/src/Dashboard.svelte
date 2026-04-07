<script lang="ts">
  import { onMount, onDestroy, tick } from 'svelte';
  import { Chart } from 'chart.js';
  import zoomPlugin from 'chartjs-plugin-zoom';
  import { getDates, getData, getHealth, getBase, getRunStatus, getHistory, getExportCsvBlob, getSummaryCsvBlob, runTestNow } from './lib/api';

  Chart.register(zoomPlugin);
  import { formatValue, formatDate, formatDateShort, formatDateTimeShort } from './lib/format';
  import { loading } from './lib/stores';
  import type { SpeedtestPoint, IperfPoint, DataResponse, HistoryResponse } from './lib/api';

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
          tension: 0,
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
          tension: 0,
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

  $: filteredSpeedtestData = selectedDate ? filterByTimeRange(speedtestData, selectedDate, timeRangeFilter) : speedtestData;
  $: filteredIperfData = selectedDate ? filterByTimeRange(iperfData, selectedDate, timeRangeFilter) : iperfData;
  $: extendToNow = !!selectedDate && selectedDate === todayYmd();
  $: speedtestSites = Object.keys(filteredSpeedtestData).filter((s) => (filteredSpeedtestData[s] || []).length > 0);
  $: iperfSites = Object.keys(filteredIperfData).filter((s) => (filteredIperfData[s] || []).length > 0);
  $: hasSpeedtest = speedtestSites.length > 0;
  $: hasIperf = iperfSites.length > 0;
  $: hasAnyData = hasSpeedtest || hasIperf;
  /** Raw points exist for the day, but 6h/12h window removed every point — show a specific message */
  $: speedtestSitesBeforeTimeFilter = selectedDate
    ? Object.keys(speedtestData).filter((s) => (speedtestData[s] || []).length > 0)
    : [];
  $: iperfSitesBeforeTimeFilter = selectedDate
    ? Object.keys(iperfData).filter((s) => (iperfData[s] || []).length > 0)
    : [];
  $: timeFilterExcludesAllSpeedtest =
    timeRangeFilter !== 'full' && speedtestSitesBeforeTimeFilter.length > 0 && !hasSpeedtest;
  $: timeFilterExcludesAllIperf =
    timeRangeFilter !== 'full' && iperfSitesBeforeTimeFilter.length > 0 && !hasIperf;

  function renderChart(
    canvas: HTMLCanvasElement | undefined,
    labels: string[],
    datasets: { label: string; data: (number | null)[]; borderColor: string; backgroundColor: string; fill: boolean; tension: number; pointRadius: number; pointHoverRadius: number; borderWidth?: number }[],
    metric: string,
    metricLabel: string
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
            ticks: { maxRotation: 45, maxTicksLimit: 14, font: { size: 12 } },
          },
          y: {
            beginAtZero: metric !== 'latency_ms',
            title: { display: true, text: metricLabel, font: { size: 13 } },
            grid: { display: true, color: 'rgba(0,0,0,0.08)' },
            ticks: { font: { size: 12 } },
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
    /* Derive from filtered data here — do not use $: hasSpeedtest/hasIperf; those can lag one tick behind
     * raw speedtestData in Svelte’s reactive order, so charts were skipped while iperf sometimes still drew. */
    const hasSt = Object.keys(filteredSpeedtestData).some((s) => (filteredSpeedtestData[s] || []).length > 0);
    const hasIp = Object.keys(filteredIperfData).some((s) => (filteredIperfData[s] || []).length > 0);
    if (downloadCanvas && hasSt) {
      const { labels, datasets } = buildSpeedtestOverTime(filteredSpeedtestData, 'download_bps', extendToNow);
      if (labels.length && datasets.length) {
        downloadChartInst = renderChart(downloadCanvas, labels, datasets, 'download_bps', 'Download (Mbps)');
      }
    }
    if (uploadCanvas && hasSt) {
      const { labels, datasets } = buildSpeedtestOverTime(filteredSpeedtestData, 'upload_bps', extendToNow);
      if (labels.length && datasets.length) {
        uploadChartInst = renderChart(uploadCanvas, labels, datasets, 'upload_bps', 'Upload (Mbps)');
      }
    }
    if (latencyCanvas && hasSt) {
      const { labels, datasets } = buildSpeedtestOverTime(filteredSpeedtestData, 'latency_ms', extendToNow);
      if (labels.length && datasets.length) {
        latencyChartInst = renderChart(latencyCanvas, labels, datasets, 'latency_ms', 'Latency (ms)');
      }
    }
    if (iperfCanvas && hasIp) {
      const { labels, datasets } = buildIperfOverTime(filteredIperfData, extendToNow);
      if (labels.length && datasets.length) {
        iperfChartInst = renderChart(iperfCanvas, labels, datasets, 'bits_per_sec', 'Throughput (Mbps)');
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
  /* Depend on filtered series + extendToNow so we run after filter reactives (avoids stale hasSpeedtest). */
  $: if (selectedDate) {
    filteredSpeedtestData;
    filteredIperfData;
    extendToNow;
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
  function renderTrendCharts() {
    [trendDownloadChart, trendUploadChart, trendLatencyChart, trendIperfChart].forEach((c) => { if (c) c.destroy(); });
    trendDownloadChart = trendUploadChart = trendLatencyChart = trendIperfChart = null;
    const sites = [...new Set(historyData.speedtest.map((p) => p.site))];
    if (sites.length && historyData.speedtest.length && trendDownloadCanvas) {
      const labels = [...new Set(historyData.speedtest.map((p) => p.date))].sort();
      const displayLabels = labels.map(formatDateShort);
      const bySite = (key: 'download_bps' | 'upload_bps' | 'latency_ms') => {
        return sites.map((site, i) => {
          const byDate: Record<string, number[]> = {};
          historyData.speedtest.filter((p) => p.site === site).forEach((p) => {
            const v = (p as unknown as Record<string, unknown>)[key];
            if (v != null && typeof v === 'number') {
              if (!byDate[p.date]) byDate[p.date] = [];
              byDate[p.date].push(v);
            }
          });
          const avg = (arr: number[]) => arr.reduce((a, b) => a + b, 0) / arr.length;
          return {
            label: site,
            data: labels.map((d) => (byDate[d]?.length ? avg(byDate[d]) : null)),
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
      };
      trendDownloadChart = renderChart(trendDownloadCanvas, displayLabels, bySite('download_bps'), 'download_bps', 'Download (Mbps)');
      if (trendUploadCanvas) trendUploadChart = renderChart(trendUploadCanvas, displayLabels, bySite('upload_bps'), 'upload_bps', 'Upload (Mbps)');
      if (trendLatencyCanvas) trendLatencyChart = renderChart(trendLatencyCanvas, displayLabels, bySite('latency_ms'), 'latency_ms', 'Latency (ms)');
    }
    const iperfSites = [...new Set(historyData.iperf.map((p) => p.site))];
    if (iperfSites.length && historyData.iperf.length && trendIperfCanvas) {
      const labels = [...new Set(historyData.iperf.map((p) => p.date))].sort();
      const displayLabels = labels.map(formatDateShort);
      const datasets = iperfSites.map((site, i) => {
        const byDate: Record<string, number> = {};
        historyData.iperf.filter((p) => p.site === site).forEach((p) => {
          if (p.bits_per_sec != null) byDate[p.date] = p.bits_per_sec;
        });
        return {
          label: site,
          data: labels.map((d) => byDate[d] ?? null),
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
      trendIperfChart = renderChart(trendIperfCanvas, displayLabels, datasets, 'bits_per_sec', 'Throughput (Mbps)');
    }
  }

  async function loadData() {
    if (!selectedDate) {
      speedtestData = {};
      iperfData = {};
      return;
    }
    loading.set(true);
    try {
      const r: DataResponse = await getData(selectedDate, probeId);
      speedtestData = r.speedtest || {};
      iperfData = r.iperf || {};
      // Force chart redraw with new data (speedtest/iperf day-view graphs)
      await updateCharts();
    } catch {
      speedtestData = {};
      iperfData = {};
    } finally {
      loading.set(false);
    }
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

  /** Include probeId so node dashboard refetches when switching nodes; loadData reads probeId inside. */
  $: if (selectedDate) {
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
        <label for="dashboard-date" class="form-label mb-0 small text-muted">Date</label>
        <select id="dashboard-date" class="form-select form-select-sm" style="max-width:140px" bind:value={selectedDate} disabled={datesLoading}>
          <option value="">{datesLoading ? 'Loading…' : 'Select date…'}</option>
          {#each dates as d}
            <option value={d}>{formatDate(d)}</option>
          {/each}
        </select>
        {#if selectedDate}
          <label for="dashboard-time-range" class="form-label mb-0 small text-muted ms-2">Range</label>
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
        <div class="chart-placeholder chart-fixed"><p class="text-muted mb-0">No Speedtest data for this date. Use <strong>Run test now</strong> or the <strong>Scheduler</strong> to run tests.</p></div>
      {:else}
        <div class="chart-wrap chart-fixed"><canvas bind:this={downloadCanvas}></canvas></div>
        <p class="small text-muted mt-2 mb-0">All sites over time. Drag to pan, scroll to zoom. Click legend to toggle.</p>
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
        <div class="chart-placeholder chart-fixed"><p class="text-muted mb-0">No Speedtest data for this date.</p></div>
      {:else}
        <div class="chart-wrap chart-fixed"><canvas bind:this={uploadCanvas}></canvas></div>
        <p class="small text-muted mt-2 mb-0">All sites over time. Click legend to toggle.</p>
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
        <div class="chart-placeholder chart-fixed"><p class="text-muted mb-0">No Speedtest data for this date.</p></div>
      {:else}
        <div class="chart-wrap chart-fixed"><canvas bind:this={latencyCanvas}></canvas></div>
        <p class="small text-muted mt-2 mb-0">All sites over time. Click legend to toggle.</p>
      {/if}
    </div>
  </section>

  <!-- iperf3: always show section -->
  <section class="card mb-4">
    <div class="card-header text-dark">iperf3 throughput</div>
    <div class="card-body">
      <p class="small text-muted mb-2">Chart shows combined (end-of-test) result per run. Use <strong>Download CSV</strong> above for full interval data.</p>
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
          <p class="text-muted mb-0">No iperf3 data for this date. Add iperf servers in <strong>Settings</strong>, then use <strong>Run test now</strong> or the <strong>Scheduler</strong> to run real tests.</p>
        </div>
      {:else}
        <div class="chart-single">
          <div class="chart-wrap chart-wrap-lg">
            <canvas bind:this={iperfCanvas}></canvas>
          </div>
        </div>
        <p class="small text-muted mt-2 mb-0">Combined graph over time — all iperf series. Click legend to toggle.</p>
      {/if}
    </div>
  </section>

  <!-- Trend over time: separate fixed cards per metric -->
  <div class="trend-controls card mb-3">
    <div class="card-body py-2 d-flex flex-wrap align-items-center justify-content-between gap-2">
      <span class="fw-semibold text-dark">Trend over time</span>
      <div class="d-flex align-items-center gap-2">
        <label for="history-days" class="form-label mb-0 small text-muted">Days</label>
        <select id="history-days" class="form-select form-select-sm" style="max-width:80px" bind:value={historyDays} on:change={() => loadHistory()}>
          <option value={7}>7</option>
          <option value={14}>14</option>
          <option value={30}>30</option>
          <option value={90}>90</option>
        </select>
        <button type="button" class="btn btn-sm btn-outline-secondary" on:click={loadHistory} disabled={historyLoading}>{historyLoading ? 'Loading…' : 'Refresh'}</button>
      </div>
    </div>
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
