<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { Chart } from 'chart.js';
  import { formatValue } from './lib/format';

  export let site = '';
  export let data: { t: string; y: number }[] = [];
  export let metric = 'download_bps';
  export let metricLabel = 'Download';
  export let color = '#6366f1';

  let canvas: HTMLCanvasElement;
  let chart: Chart | null = null;

  $: if (canvas && data.length > 0) {
    if (chart) chart.destroy();
    chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: data.map((p) => p.t),
        datasets: [{
          label: metricLabel,
          data: data.map((p) => p.y),
          borderColor: color,
          backgroundColor: color + '30',
          fill: true,
          tension: 0.25,
          pointRadius: 2,
          pointHoverRadius: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (ctx) => formatValue(ctx.parsed.y, metric) } },
        },
        scales: {
          x: { ticks: { maxTicksLimit: 8, maxRotation: 45 } },
          y: { beginAtZero: metric !== 'latency_ms' },
        },
      },
    });
  } else if (chart) {
    chart.destroy();
    chart = null;
  }

  onDestroy(() => chart?.destroy());
</script>

<div class="per-site-chart">
  <canvas bind:this={canvas}></canvas>
</div>

<style>
  .per-site-chart { height: 200px; min-height: 160px; width: 100%; }
</style>
