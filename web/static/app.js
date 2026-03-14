(function () {
  const API = "";
  const views = { dashboard: "Dashboard", scheduler: "Scheduler", settings: "Settings" };
  const pageTitleEl = document.getElementById("page-title");
  const viewSections = {
    dashboard: document.getElementById("view-dashboard"),
    scheduler: document.getElementById("view-scheduler"),
    settings: document.getElementById("view-settings"),
  };
  const dateSelect = document.getElementById("date-select");
  const metricSelect = document.getElementById("metric-select");
  const chartMasterEl = document.getElementById("chart-master");
  const chartMasterEmpty = document.getElementById("chart-master-empty");
  const perSiteChartsEl = document.getElementById("per-site-charts");
  const perSiteEmpty = document.getElementById("per-site-empty");
  const schedulerStatusEl = document.getElementById("scheduler-status");
  const schedulerBadge = document.getElementById("scheduler-badge");
  const schedulerBadgeText = document.getElementById("scheduler-badge-text");
  const btnSchedulerStart = document.getElementById("btn-scheduler-start");
  const btnSchedulerStop = document.getElementById("btn-scheduler-stop");
  const configLimitMbps = document.getElementById("config-limit-mbps");
  const configOokla = document.getElementById("config-ookla");
  const configIperfServers = document.getElementById("config-iperf-servers");
  const configIperfTests = document.getElementById("config-iperf-tests");
  const btnSaveConfig = document.getElementById("btn-save-config");
  const configMessage = document.getElementById("config-message");
  const toastEl = document.getElementById("toast");
  const loadingEl = document.getElementById("loading-overlay");

  let currentView = "dashboard";
  let masterChart = null;
  let perSiteCharts = [];

  const COLORS = [
    "#6366f1", "#22c55e", "#a78bfa", "#f59e0b", "#ef4444",
    "#818cf8", "#4ade80", "#c084fc", "#fbbf24", "#f87171",
  ];

  function showView(name) {
    currentView = name;
    Object.keys(viewSections).forEach((key) => {
      viewSections[key].classList.toggle("view-active", key === name);
    });
    document.querySelectorAll(".nav-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.view === name);
    });
    if (pageTitleEl) pageTitleEl.textContent = views[name] || name;
    if (name === "settings") {
      fetchJson("/api/config").then((config) => {
        configLimitMbps.value = config.speedtest_limit_mbps != null && config.speedtest_limit_mbps !== "" ? String(config.speedtest_limit_mbps) : "";
        configOokla.value = JSON.stringify(config.ookla_servers || [], null, 2);
        configIperfServers.value = JSON.stringify(config.iperf_servers || [], null, 2);
        configIperfTests.value = JSON.stringify(config.iperf_tests || [], null, 2);
      });
    }
  }

  function showToast(message, type) {
    toastEl.textContent = message;
    toastEl.className = "toast " + (type || "success");
    toastEl.classList.remove("hidden");
    setTimeout(() => toastEl.classList.add("hidden"), 3500);
  }

  function setLoading(on) {
    loadingEl.classList.toggle("hidden", !on);
  }

  function formatValue(val, metric) {
    if (val == null || val === undefined) return "—";
    if (metric === "latency_ms") return Number(val).toFixed(1) + " ms";
    if (metric === "download_bps" || metric === "upload_bps") {
      const mbps = Number(val) / 1e6;
      return mbps >= 1000 ? (mbps / 1000).toFixed(2) + " Gbps" : mbps.toFixed(2) + " Mbps";
    }
    return String(val);
  }

  function fetchJson(url, opts = {}) {
    return fetch(API + url, { headers: { Accept: "application/json", ...(opts.headers || {}) }, ...opts }).then((r) => {
      if (!r.ok) throw new Error(r.statusText);
      return r.json();
    });
  }

  function loadDates() {
    return fetchJson("/api/dates").then((data) => {
      dateSelect.innerHTML = '<option value="">Select date…</option>';
      (data.dates || []).forEach((d) => {
        const opt = document.createElement("option");
        opt.value = d;
        opt.textContent = d;
        dateSelect.appendChild(opt);
      });
    });
  }

  function loadStatus() {
    return fetchJson("/api/status")
      .then((data) => {
        const running = !!data.scheduled;
        schedulerBadgeText.textContent = running ? "Running" : "Stopped";
        schedulerBadge.classList.toggle("is-active", running);
        if (schedulerStatusEl) {
          schedulerStatusEl.textContent = running ? "Running" : "Stopped";
          schedulerStatusEl.className = "status-value " + (running ? "active" : "inactive");
        }
      })
      .catch(() => {
        schedulerBadgeText.textContent = "—";
        schedulerBadge.classList.remove("is-active");
        if (schedulerStatusEl) schedulerStatusEl.textContent = "—";
      });
  }

  function buildSeries(speedtestData, metric) {
    const series = {};
    const labelKey = metric === "latency_ms" ? "latency_ms" : metric;
    Object.keys(speedtestData).forEach((site) => {
      const points = (speedtestData[site] || [])
        .map((r) => ({ t: r.timestamp, y: r[labelKey] != null ? r[labelKey] : null }))
        .filter((p) => p.y != null);
      if (points.length) series[site] = points;
    });
    return series;
  }

  function destroyPerSiteCharts() {
    perSiteCharts.forEach((c) => c.destroy());
    perSiteCharts = [];
  }

  const chartGridOptions = {
    color: "rgba(156, 163, 180, 0.4)",
    drawTicks: true,
  };
  const chartFont = { family: "'DM Sans', system-ui, sans-serif", size: 11 };

  function renderCharts(speedtestData, metric) {
    const series = buildSeries(speedtestData, metric);
    const sites = Object.keys(series);
    const allTimes = new Set();
    sites.forEach((s) => series[s].forEach((p) => allTimes.add(p.t)));
    const sortedTimes = Array.from(allTimes).sort();
    const metricLabel = metric === "download_bps" ? "Download" : metric === "upload_bps" ? "Upload" : "Latency (ms)";

    const hasData = sites.length > 0;
    if (chartMasterEmpty) {
      chartMasterEmpty.classList.toggle("hidden", hasData);
    }
    if (perSiteEmpty) {
      perSiteEmpty.classList.toggle("hidden", hasData);
    }

    if (masterChart) masterChart.destroy();
    if (!hasData) {
      masterChart = null;
      destroyPerSiteCharts();
      perSiteChartsEl.innerHTML = "";
      return;
    }

    const labels = sortedTimes;
    const masterDatasets = sites.map((site, i) => {
      const byTime = {};
      series[site].forEach((p) => {
        byTime[p.t] = p.y;
      });
      return {
        label: site,
        data: labels.map((t) => byTime[t] ?? null),
        borderColor: COLORS[i % COLORS.length],
        backgroundColor: COLORS[i % COLORS.length] + "25",
        fill: false,
        tension: 0.25,
        pointRadius: 3,
        pointHoverRadius: 5,
      };
    });

    masterChart = new Chart(chartMasterEl, {
      type: "line",
      data: { labels, datasets: masterDatasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { intersect: false, mode: "index" },
        plugins: {
          legend: {
            position: "top",
            labels: { usePointStyle: true, padding: 16, font: chartFont },
            onClick(e, legendItem, legend) {
              const idx = legendItem.datasetIndex;
              const meta = legend.chart.getDatasetMeta(idx);
              meta.hidden = meta.hidden === null ? !legend.chart.data.datasets[idx].hidden : null;
              legend.chart.update();
            },
          },
          tooltip: {
            backgroundColor: "rgba(26, 31, 40, 0.95)",
            titleFont: chartFont,
            bodyFont: chartFont,
            callbacks: {
              label(ctx) {
                return ctx.dataset.label + ": " + formatValue(ctx.parsed.y, metric);
              },
            },
          },
        },
        scales: {
          x: {
            grid: chartGridOptions,
            ticks: { maxRotation: 45, maxTicksLimit: 12, font: chartFont },
          },
          y: {
            grid: chartGridOptions,
            beginAtZero: metric !== "latency_ms",
            ticks: { font: chartFont },
            title: { display: true, text: metricLabel, font: chartFont },
          },
        },
      },
    });

    destroyPerSiteCharts();
    perSiteChartsEl.innerHTML = "";
    sites.forEach((site, i) => {
      const card = document.createElement("div");
      card.className = "per-site-card";
      const title = document.createElement("h2");
      title.className = "card-title";
      title.textContent = site;
      const wrap = document.createElement("div");
      wrap.className = "per-site-chart-wrap";
      const canvas = document.createElement("canvas");
      wrap.appendChild(canvas);
      card.appendChild(title);
      card.appendChild(wrap);
      perSiteChartsEl.appendChild(card);

      const chart = new Chart(canvas, {
        type: "line",
        data: {
          labels: series[site].map((p) => p.t),
          datasets: [
            {
              label: metricLabel,
              data: series[site].map((p) => p.y),
              borderColor: COLORS[i % COLORS.length],
              backgroundColor: COLORS[i % COLORS.length] + "30",
              fill: true,
              tension: 0.25,
              pointRadius: 2,
              pointHoverRadius: 4,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: "rgba(26, 31, 40, 0.95)",
              bodyFont: chartFont,
              callbacks: { label: (ctx) => formatValue(ctx.parsed.y, metric) },
            },
          },
          scales: {
            x: { grid: chartGridOptions, ticks: { maxTicksLimit: 8, maxRotation: 45, font: chartFont } },
            y: { grid: chartGridOptions, beginAtZero: metric !== "latency_ms", ticks: { font: chartFont } },
          },
        },
      });
      perSiteCharts.push(chart);
    });
  }

  function loadDataForDate(date) {
    if (chartMasterEmpty) chartMasterEmpty.textContent = "Select a date above to load data.";
    if (!date) {
      if (masterChart) {
        masterChart.destroy();
        masterChart = null;
      }
      destroyPerSiteCharts();
      perSiteChartsEl.innerHTML = "";
      if (chartMasterEmpty) chartMasterEmpty.classList.remove("hidden");
      if (perSiteEmpty) perSiteEmpty.classList.remove("hidden");
      return;
    }
    setLoading(true);
    fetchJson("/api/data?date=" + encodeURIComponent(date))
      .then((data) => {
        const metric = metricSelect.value;
        renderCharts(data.speedtest || {}, metric);
      })
      .catch(() => {
        if (masterChart) masterChart.destroy();
        destroyPerSiteCharts();
        perSiteChartsEl.innerHTML = "";
        if (chartMasterEmpty) {
          chartMasterEmpty.textContent = "Failed to load data for this date.";
          chartMasterEmpty.classList.remove("hidden");
        }
        if (perSiteEmpty) perSiteEmpty.classList.remove("hidden");
      })
      .finally(() => setLoading(false));
  }

  document.querySelectorAll(".nav-item").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      const view = el.dataset.view;
      if (view) showView(view);
    });
  });

  dateSelect.addEventListener("change", () => loadDataForDate(dateSelect.value));
  metricSelect.addEventListener("change", () => {
    if (dateSelect.value) loadDataForDate(dateSelect.value);
  });

  btnSchedulerStart.addEventListener("click", () => {
    btnSchedulerStart.disabled = true;
    fetch(API + "/api/scheduler/start", { method: "POST" })
      .then((r) => r.json())
      .then(() => {
        loadStatus();
        showToast("Schedule started. Tests will run at :05 every hour.");
      })
      .catch(() => showToast("Failed to start schedule.", "error"))
      .finally(() => (btnSchedulerStart.disabled = false));
  });

  btnSchedulerStop.addEventListener("click", () => {
    btnSchedulerStop.disabled = true;
    fetch(API + "/api/scheduler/stop", { method: "POST" })
      .then((r) => r.json())
      .then(() => {
        loadStatus();
        showToast("Schedule stopped.");
      })
      .catch(() => showToast("Failed to stop schedule.", "error"))
      .finally(() => (btnSchedulerStop.disabled = false));
  });

  btnSaveConfig.addEventListener("click", () => {
    configMessage.classList.add("hidden");
    let ookla, iperfServers, iperfTests;
    try {
      ookla = JSON.parse(configOokla.value);
      iperfServers = JSON.parse(configIperfServers.value);
      iperfTests = JSON.parse(configIperfTests.value);
    } catch (e) {
      configMessage.textContent = "Invalid JSON: " + e.message;
      configMessage.classList.remove("hidden", "success");
      configMessage.classList.add("error");
      return;
    }
    const limitVal = configLimitMbps.value.trim();
    const limitMbps = limitVal === "" ? null : parseInt(limitVal, 10);
    if (limitVal !== "" && (isNaN(limitMbps) || limitMbps < 1)) {
      configMessage.textContent = "Speed limit must be a positive number or empty.";
      configMessage.classList.remove("hidden", "success");
      configMessage.classList.add("error");
      return;
    }
    fetch(API + "/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        speedtest_limit_mbps: limitMbps,
        ookla_servers: ookla,
        iperf_servers: iperfServers,
        iperf_tests: iperfTests,
      }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.ok) {
          configMessage.textContent = "Configuration saved.";
          configMessage.classList.remove("hidden", "error");
          configMessage.classList.add("success");
          showToast("Configuration saved.");
        } else {
          configMessage.textContent = data.error || "Error";
          configMessage.classList.remove("hidden", "success");
          configMessage.classList.add("error");
        }
      })
      .catch(() => {
        configMessage.textContent = "Request failed.";
        configMessage.classList.remove("hidden", "success");
        configMessage.classList.add("error");
        showToast("Failed to save configuration.", "error");
      });
  });

  showView("dashboard");
  loadDates().then(() => loadStatus());
  setInterval(loadStatus, 30000);

})();
