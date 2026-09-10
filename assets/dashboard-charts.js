// SPDX-FileCopyrightText: 2026 Pulse contributors
// SPDX-License-Identifier: GPL-3.0-only
    const ROLL_LABELS = { 1: 'Live', 60: '1m', 300: '5m', 600: '10m' };
    const SENSOR_GROUPS = {
      Temperatures: s => s.kind === 'temp',
      'GPU & clocks': s => /gpu|igpu|gfx|vram/i.test(`${s.id} ${s.label}`) && s.kind !== 'temp',
      'Memory & pressure': s => /psi|swap|pgfault|pgmaj|dram|ram_avail/i.test(`${s.id} ${s.label}`),
      'Storage & drives': s => /^nvme|disk_use/i.test(s.id),
      Network: s => /^nic_|^wifi/.test(s.id),
      System: s => /load|uptime|procs|threads|ctx|intr|fan|pwr|mhz|clk/i.test(`${s.id} ${s.label}`),
      Other: () => true,
    };
    let globalRollup = 1, rawHistory = [], metricsBootstrapped = false;
    const CHART_VIEW_OPTS = [60, 300, 600, 3600];
    const CHART_VIEW_LABELS = { 60: '1 min', 300: '5 min', 600: '10 min', 3600: '60 min' };
    function loadChartView() {
      try {
        const n = +sessionStorage.getItem('pulse-chart-view');
        if (CHART_VIEW_OPTS.includes(n)) return n;
      } catch (_) { /* ignore */ }
      return 300;
    }
    let chartViewSec = loadChartView();
    let spanSec = chartViewSec;
    function persistChartView() {
      try { sessionStorage.setItem('pulse-chart-view', String(chartViewSec)); } catch (_) { /* ignore */ }
    }
    /** Frozen sample after suspend/resume: same ts for N polls or server sampler.ok=false. */
    let lastSampleTs = null;
    let sameTsStreak = 0;
    let lastSamplerGeneration = null;
    let lastResumeEpoch = null;
    let lastWallSec = Date.now() / 1000;
    let lastPerfSec = (typeof performance !== 'undefined' ? performance.now() : 0) / 1000;
    const STALE_AGE_SEC = 5;
    const REBOOTSTRAP_STALE_SEC = 12;
    const SAME_TS_STALE = 3;
    const SAME_TS_REBOOTSTRAP = 8;
    const CLIENT_WALL_JUMP_SEC = 2.5;
    const chartRollup = { util: null, bw: null, io: null };
    const DEFAULT_ENABLED = {
      util: { cpu: true, gpu: true, ram: true, swap: false, gameCpu: true },
      bw: { vramBw: true, dramBw: true, gtt: true },
      io: { netDn: true, netUp: true, diskR: true, diskW: true },
    };
    const enabled = {
      util: { ...DEFAULT_ENABLED.util },
      bw: { ...DEFAULT_ENABLED.bw },
      io: { ...DEFAULT_ENABLED.io },
    };
    let enabledBeforeFocus = null;
    let lastStatic = null;
    let lastLatest = null;
    let lastComparison = null;
    const HW_FOCUS_PARTS = ['cpu', 'gpu', 'memory', 'storage'];
    const HW_FOCUS_LABELS = { cpu: 'CPU', gpu: 'GPU', memory: 'Memory', storage: 'Storage' };

    function loadHwFocusSet() {
      const raw = sessionStorage.getItem('pulse-hw-focus') || '';
      const parts = raw.split(/[+,]/).map(s => s.trim()).filter(p => HW_FOCUS_PARTS.includes(p));
      return new Set(parts);
    }
    /** Active hardware filters (multi-select). Empty = full rig. */
    let hwFocusSet = loadHwFocusSet();
    function anyHwFocus() { return hwFocusSet.size > 0; }
    function hwFocusHas(part) { return hwFocusSet.has(part); }
    /** Single selection only — null when none or multi (callers use default/composite). */
    function soleHwFocus() {
      return hwFocusSet.size === 1 ? [...hwFocusSet][0] : null;
    }
    function hwFocusKey() {
      return anyHwFocus() ? [...hwFocusSet].sort().join('+') : 'all';
    }
    function hwFocusLabelList() {
      return [...hwFocusSet].map(p => HW_FOCUS_LABELS[p]).filter(Boolean);
    }
    function hwFocusLabelText() {
      const labs = hwFocusLabelList();
      if (!labs.length) return '';
      if (labs.length === 1) return labs[0];
      if (labs.length === 2) return `${labs[0]} + ${labs[1]}`;
      return labs.slice(0, -1).join(', ') + ' + ' + labs[labs.length - 1];
    }
    function persistHwFocus() {
      if (!anyHwFocus()) sessionStorage.removeItem('pulse-hw-focus');
      else sessionStorage.setItem('pulse-hw-focus', [...hwFocusSet].sort().join(','));
    }
    const INDEX_STATUS_SUBS = {
      default: 'How much of your build is in play',
      cpu: 'CPU load vs your tier',
      gpu: 'GPU load vs your tier',
      memory: 'Memory pressure vs your tier',
    };

    const HW_FOCUS_SUM_CELLS = { cpu: 'sumCpuCell', gpu: 'sumGpuCell', memory: 'sumMemCell' };
    const VIZ_BLOCK_TITLES = {
      'viz-area-rig': {
        default: 'Rig snapshot',
        cpu: 'Rig snapshot · CPU focus',
        gpu: 'Rig snapshot · GPU focus',
        memory: 'Rig snapshot · memory focus',
        storage: 'Rig snapshot · storage I/O',
      },
      'viz-area-index': {
        default: 'Pulse Index · session load',
        cpu: 'Pulse Index · CPU load',
        gpu: 'Pulse Index · GPU load',
        memory: 'Pulse Index · memory pressure',
      },
      'viz-area-stutter': {
        default: 'Stutter estimate',
        cpu: 'Stutter estimate · CPU & memory',
        gpu: 'Stutter estimate · system hitches',
        memory: 'Stutter estimate · memory pressure',
        storage: 'Stutter estimate · I/O contention',
      },
    };
    const VIZ_BLOCK_ICONS = {
      'viz-area-rig': { default: 'activity', cpu: 'cpu', gpu: 'gpu', memory: 'mem', storage: 'storage' },
      'viz-area-index': { default: 'league', cpu: 'cpu', gpu: 'gpu', memory: 'mem', storage: 'storage' },
      'viz-area-stutter': { default: 'stutter', cpu: 'stutter', gpu: 'stutter', memory: 'stutter', storage: 'stutter' },
    };
    const VIZ_ICON_BOX_CLS = {
      cpu: 'cpu', gpu: 'gpu', mem: 'mem', temp: 'temp', storage: 'storage', league: 'league',
      activity: 'game', fan: 'gpu', stutter: 'stutter',
    };
    const HW_FILTER_HIDE_MS = 350;
    const hwFilterHideHandlers = new WeakMap();
    let nocEmptyTimer = null;
    const HINT_HW_MAP = {
      'cpu-governor-powersave': ['cpu'],
      'vm-swappiness-high': ['memory'],
      'ram-expo-verify': ['memory'],
      'gpu-thermal-ceiling': ['gpu'],
      'gpu-thermal-warm': ['gpu'],
      'gpu-thermal-by-design': ['gpu'],
      'gpu-vram-bandwidth': ['gpu'],
      'gpu-vram-full': ['gpu'],
      'gpu-gtt-churn': ['gpu'],
      'memory-swap-thrash': ['memory'],
      'memory-dram-stall': ['memory'],
      'memory-page-faults': ['memory'],
      'stutter-proxy': ['cpu', 'gpu', 'memory'],
      'cpu-bound': ['cpu'],
      'gpu-shader-bound': ['gpu'],
      'gpu-fps-cap': ['gpu'],
      'resolution-swap-stutter': ['memory'],
      'resolution-load-settle': ['memory'],
      'resolution-cpu-perf': ['cpu'],
      'cpu-ccd-spread': ['cpu'],
      'game-files-corrupt': ['cpu', 'gpu', 'memory'],
      'game-update-pending': ['cpu', 'gpu', 'memory'],
      'game-libs-missing': ['cpu', 'gpu', 'memory'],
      'steam-disk-low': ['cpu', 'gpu', 'memory'],
      'vulkan-broken': ['gpu'],
      'game-prefix-reset': ['cpu', 'gpu', 'memory'],
      'system-balanced': ['cpu', 'gpu', 'memory'],
    };
    let lastWarningsHints = [];

    let gridColor = 'rgba(255,255,255,.06)';
    let tickColor = '#9aa3b2';

    function chartGridColor() {
      // Plot wells stay dark in every chrome so series colors remain readable.
      return 'rgba(255,255,255,.10)';
    }
    function chartTickColor() {
      return '#d0d7e2';
    }
    function applyChartChrome() {
      gridColor = chartGridColor();
      tickColor = chartTickColor();
      const charts = (typeof ALL_PULSE_CHARTS !== 'undefined') ? ALL_PULSE_CHARTS : [];
      charts.forEach((ch) => {
        if (!ch?.options?.scales) return;
        Object.values(ch.options.scales).forEach((sc) => {
          if (!sc) return;
          if (sc.ticks) sc.ticks.color = tickColor;
          if (sc.grid) sc.grid.color = gridColor;
        });
        const lab = ch.options?.plugins?.legend?.labels;
        if (lab) lab.color = tickColor;
        try { if (!chartInteractActive) ch.update('none'); } catch (_) { /* */ }
      });
    }

    /* —— Chart pause / drag-zoom (all Chart.js graphs) —— */
    let chartsPaused = false;
    /** Fixed unix-sec window when paused or zoomed; null = follow live spanSec tail. */
    let chartRange = null;
    /** Window captured when the user clicks Pause (not when zoom auto-pauses). */
    let chartPauseSnapshot = null;
    let chartZoomed = false;
    let _chartZoomSyncing = false;
    /** True while user is mid drag-zoom / pan — skip scale rewrites that abort the gesture. */
    let chartInteractActive = false;

    function fmtTimeAxis(ts) {
      if (ts == null || !Number.isFinite(+ts)) return '';
      return new Date(+ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    function getLiveChartWindow() {
      const last = rawHistory.at(-1)?.ts ?? (Date.now() / 1000);
      return { min: last - spanSec, max: last };
    }

    function getActiveChartWindow() {
      if (chartRange && Number.isFinite(chartRange.min) && Number.isFinite(chartRange.max)) {
        return chartRange;
      }
      return getLiveChartWindow();
    }

    function xySeries(tsArr, valArr) {
      const out = [];
      const n = Math.min(tsArr.length, valArr.length);
      for (let i = 0; i < n; i++) {
        const x = tsArr[i];
        if (x == null || !Number.isFinite(+x)) continue;
        out.push({ x: +x, y: valArr[i] });
      }
      return out;
    }

    /** Slice to the visible time window, then cap point count for canvas draw.
     *  Buckets are epoch-aligned so a sliding 1 Hz window does not pick a new
     *  subset of peaks every tick (index-stride downsample did). */
    function xySeriesView(tsArr, valArr, viewSec, maxPts, agg = 'avg') {
      const n = Math.min(tsArr?.length || 0, valArr?.length || 0);
      if (!n) return [];
      let t0;
      let t1;
      if (chartRange && (chartsPaused || chartZoomed)
          && Number.isFinite(chartRange.min) && Number.isFinite(chartRange.max)) {
        t0 = chartRange.min;
        t1 = chartRange.max;
      } else {
        t1 = tsArr[n - 1] || 0;
        t0 = t1 - (Number(viewSec) || 600);
      }
      const span = Math.max(30, t1 - t0);
      let i0 = 0;
      while (i0 < n && tsArr[i0] < t0 - 2) i0 += 1;
      i0 = Math.max(0, i0 - 1);
      let i1 = n;
      while (i1 > i0 && tsArr[i1 - 1] > t1 + 2) i1 -= 1;
      const ts = tsArr.slice(i0, i1);
      const vs = valArr.slice(i0, i1);
      const cap = Math.max(120, maxPts || 480);
      // 1 Hz AMD GPU busy (and session index derived from it) square-waves.
      // Sub-2s buckets + cubic tension drew a hashed comb that reshaped every tick.
      let bucketSec = Math.max(1, Math.round(span / cap));
      if (span >= 120) bucketSec = Math.max(3, bucketSec);
      if (bucketSec <= 1 && ts.length <= cap + 40) return xySeries(ts, vs);
      return epochBucketSeries(ts, vs, bucketSec, agg);
    }

    function canvasVisible(chart) {
      const el = chart?.canvas;
      return !!(el && el.offsetParent);
    }

    function isDrillOpen(id) {
      const el = document.getElementById(id);
      return !!(el && el.open);
    }

    /** Epoch-aligned visual buckets so a sliding window does not crawl the line. */
    function epochBucketSeries(tsArr, valArr, bucketSec, agg = 'avg') {
      const n = Math.min(tsArr?.length || 0, valArr?.length || 0);
      if (!n) return [];
      const b = Math.max(1, Number(bucketSec) || 1);
      if (b <= 1) return xySeries(tsArr, valArr);
      const map = new Map();
      for (let i = 0; i < n; i++) {
        const x = tsArr[i];
        if (x == null || !Number.isFinite(+x)) continue;
        const t = Math.floor(+x / b) * b;
        let s = map.get(t);
        if (!s) { s = []; map.set(t, s); }
        s.push(valArr[i]);
      }
      const keys = [...map.keys()].sort((a, c) => a - c);
      const reduce = (vals) => {
        const nums = vals.filter(v => v != null && Number.isFinite(+v)).map(Number);
        if (!nums.length) return null;
        if (agg === 'max') return Math.max(...nums);
        if (agg === 'min') return Math.min(...nums);
        return +(nums.reduce((a, c) => a + c, 0) / nums.length).toFixed(2);
      };
      return keys.map(t => ({ x: t + b / 2, y: reduce(map.get(t)) }));
    }

    function epochBucketsFromHistory(cut, bucketSec) {
      if (!cut?.length) return { tsMids: [], slices: [] };
      const b = Math.max(1, Number(bucketSec) || 1);
      if (b <= 1) {
        return { tsMids: cut.map(h => +h.ts), slices: cut.map(h => [h]) };
      }
      const map = new Map();
      for (const h of cut) {
        if (h?.ts == null || !Number.isFinite(+h.ts)) continue;
        const t = Math.floor(+h.ts / b) * b;
        let s = map.get(t);
        if (!s) { s = []; map.set(t, s); }
        s.push(h);
      }
      const keys = [...map.keys()].sort((a, c) => a - c);
      return {
        tsMids: keys.map(t => t + b / 2),
        slices: keys.map(t => map.get(t)),
      };
    }

    function onChartInspectComplete(chart) {
      if (_chartZoomSyncing || !chart?.scales?.x) return;
      const x = chart.scales.x;
      if (!Number.isFinite(x.min) || !Number.isFinite(x.max) || x.max <= x.min) return;
      chartRange = { min: x.min, max: x.max };
      chartZoomed = true;
      chartsPaused = true;
      syncChartControlUI();
      applyChartRangeToAll(chartRange, chart);
      refreshAllCharts();
    }

    function applyChartRangeToAll(range, except) {
      if (!range) return;
      _chartZoomSyncing = true;
      try {
        for (const c of ALL_PULSE_CHARTS) {
          if (!c || c === except || !c.options?.scales?.x) continue;
          c.options.scales.x.min = range.min;
          c.options.scales.x.max = range.max;
          try { c.update('none'); } catch (_) { /* ignore */ }
        }
      } finally {
        _chartZoomSyncing = false;
      }
    }

    function clearChartRangeLimits() {
      _chartZoomSyncing = true;
      try {
        for (const c of ALL_PULSE_CHARTS) {
          if (!c?.options?.scales?.x) continue;
          delete c.options.scales.x.min;
          delete c.options.scales.x.max;
          try {
            if (typeof c.resetZoom === 'function') c.resetZoom('none');
          } catch (_) { /* ignore */ }
        }
      } finally {
        _chartZoomSyncing = false;
      }
    }

    function zoomPluginOpts() {
      // Always attach zoom config. Plugin is registered before charts are created.
      return {
        zoom: {
          zoom: {
            wheel: { enabled: true, modifierKey: 'ctrl', speed: 0.12 },
            pinch: { enabled: true },
            drag: {
              enabled: true,
              backgroundColor: 'rgba(230, 155, 253, 0.18)',
              borderColor: 'rgba(230, 155, 253, 0.65)',
              borderWidth: 1,
            },
            mode: 'x',
            onZoomStart: () => { chartInteractActive = true; },
            onZoomComplete: ({ chart }) => {
              chartInteractActive = false;
              onChartInspectComplete(chart);
            },
          },
          pan: {
            enabled: true,
            mode: 'x',
            modifierKey: 'shift',
            onPanStart: () => { chartInteractActive = true; },
            onPanComplete: ({ chart }) => {
              chartInteractActive = false;
              onChartInspectComplete(chart);
            },
          },
          // Unix-sec axis: minRange = 15 seconds of visible window
          limits: { x: { minRange: 15 } },
        },
      };
    }

    /**
     * Live X window is always [now − view, now]. Seconds-per-pixel stays constant
     * so 1 Hz does not stretch across a 10m/60m plot when history is still short.
     */
    function applyLiveTimeAxis(chart, windowSec) {
      if (!chart?.options?.scales?.x) return;
      if (chartsPaused || chartZoomed || chartInteractActive) {
        if (chartRange) {
          chart.options.scales.x.min = chartRange.min;
          chart.options.scales.x.max = chartRange.max;
        }
        return;
      }
      const last = rawHistory.at(-1)?.ts
        ?? sparkRing?.ts?.at(-1)
        ?? (Date.now() / 1000);
      const span = Math.max(30, windowSec || spanSec || 300);
      chart.options.scales.x.min = last - span;
      chart.options.scales.x.max = last;
      const ticks = chart.options.scales.x.ticks;
      if (ticks) {
        ticks.maxTicksLimit = 7;
        ticks.stepSize = span <= 60 ? 10 : span <= 300 ? 30 : span <= 600 ? 60 : 300;
      }
    }

    function timeXScale(extra = {}) {
      return {
        type: 'linear',
        ticks: {
          color: tickColor,
          maxTicksLimit: 7,
          font: { size: 15, weight: '500' },
          callback: (v) => fmtTimeAxis(v),
        },
        grid: { color: gridColor },
        ...extra,
      };
    }

    function chartOpts(y2) {
      const scales = {
        x: timeXScale(),
        y: { position: 'left', ticks: { color: tickColor, font: { size: 15, weight: '500' } }, grid: { color: gridColor } },
      };
      if (y2) scales.y1 = { position: 'right', ticks: { color: tickColor, font: { size: 15, weight: '500' } }, grid: { drawOnChartArea: false } };
      return {
        responsive: true, maintainAspectRatio: false, animation: false,
        parsing: false,
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#2b2e34',
            titleFont: { family: 'Inter', weight: '500' },
            bodyFont: { family: 'Inter', weight: '400' },
            padding: 12,
            cornerRadius: 10,
            callbacks: {
              title(items) {
                const x = items?.[0]?.parsed?.x;
                return fmtTimeAxis(x);
              },
            },
          },
          ...zoomPluginOpts(),
        },
        scales,
      };
    }

    // Register zoom BEFORE any new Chart(...) — UMD may auto-register; force it.
    (function registerZoomPlugin() {
      try {
        if (typeof Chart === 'undefined') {
          console.warn('Chart.js missing — charts disabled');
          return;
        }
        const zoomPlug = window['chartjs-plugin-zoom'] || window.ChartZoom;
        if (zoomPlug) Chart.register(zoomPlug);
        if (!Chart.registry?.plugins?.get('zoom')) {
          console.warn('chartjs-plugin-zoom not registered — drag-zoom unavailable');
        }
      } catch (e) {
        console.warn('Chart zoom plugin unavailable', e);
      }
    })();

    const utilChart = new Chart(document.getElementById('utilChart'), { type: 'line', data: { datasets: [] }, options: chartOpts() });
    utilChart.options.scales.y.min = 0;
    utilChart.options.scales.y.max = 100;
    const bwChart = new Chart(document.getElementById('bwChart'), { type: 'line', data: { datasets: [] }, options: chartOpts(true) });
    bwChart.options.scales.y.min = 0;
    bwChart.options.scales.y1.min = 0;
    const ioChart = new Chart(document.getElementById('ioChart'), { type: 'line', data: { datasets: [] }, options: chartOpts() });
    ioChart.options.scales.y.min = 0;
    const sparkChart = new Chart(document.getElementById('sparkChart'), {
      type: 'line',
      data: { datasets: [] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        parsing: false,
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        layout: { padding: { top: 4, right: 6, bottom: 2, left: 2 } },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(32, 34, 40, .94)',
            titleFont: { family: 'Inter', weight: '600', size: 11 },
            bodyFont: { family: 'Inter', size: 11 },
            padding: 10,
            cornerRadius: 8,
            borderColor: 'rgba(255,255,255,.08)',
            borderWidth: 1,
            displayColors: true,
            boxPadding: 4,
            callbacks: {
              title(items) {
                return fmtTimeAxis(items?.[0]?.parsed?.x);
              },
            },
          },
          ...zoomPluginOpts(),
        },
        scales: {
          x: timeXScale({
            ticks: {
              color: 'rgba(154, 163, 178, .85)',
              maxTicksLimit: 6,
              font: { size: 9, weight: '500' },
              maxRotation: 0,
              autoSkipPadding: 8,
              callback: (v) => fmtTimeAxis(v),
            },
            grid: { display: false },
            border: { display: false },
          }),
          y: {
            min: 0, max: 100,
            ticks: {
              color: 'rgba(154, 163, 178, .85)',
              font: { size: 9, weight: '500' },
              callback: v => v + '%',
              stepSize: 25,
              padding: 6,
            },
            grid: {
              color: 'rgba(255,255,255,.09)',
              drawTicks: false,
              lineWidth: 1,
            },
            border: { display: false },
          },
        },
      },
    });
    const stutterChartOpts = {
      responsive: true, maintainAspectRatio: false, animation: false,
      parsing: false,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: {
        legend: {
          display: true, position: 'bottom',
          labels: {
            color: tickColor, font: { family: 'Inter', size: 10 }, boxWidth: 10, padding: 10,
            filter: (item) => item.text !== 'Hitch event',
          },
        },
        tooltip: {
          backgroundColor: '#404349',
          titleFont: { family: 'Inter' },
          bodyFont: { family: 'Inter' },
          padding: 10,
          callbacks: { title(items) { return fmtTimeAxis(items?.[0]?.parsed?.x); } },
        },
        ...zoomPluginOpts(),
      },
      scales: {
        x: timeXScale({
          ticks: { color: tickColor, maxTicksLimit: 5, font: { size: 9 }, callback: (v) => fmtTimeAxis(v) },
          grid: { display: false },
        }),
        y: { min: 0, max: 100, ticks: { color: tickColor, font: { size: 9 }, callback: v => v }, grid: { color: gridColor } },
      },
    };
    const stutterChart = new Chart(document.getElementById('stutterChart'), {
      type: 'line',
      data: { datasets: [] },
      options: stutterChartOpts,
    });
    const indexChart = new Chart(document.getElementById('indexChart'), {
      type: 'line',
      data: { datasets: [] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        parsing: false,
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        plugins: {
          legend: {
            display: true, position: 'bottom',
            labels: { color: tickColor, font: { family: 'Inter', size: 10 }, boxWidth: 10, padding: 10 },
          },
          tooltip: {
            backgroundColor: '#404349',
            titleFont: { family: 'Inter' },
            bodyFont: { family: 'Inter' },
            padding: 10,
            callbacks: { title(items) { return fmtTimeAxis(items?.[0]?.parsed?.x); } },
          },
          ...zoomPluginOpts(),
        },
        scales: {
          x: timeXScale({
            ticks: { color: tickColor, maxTicksLimit: 5, font: { size: 9 }, callback: (v) => fmtTimeAxis(v) },
            grid: { display: false },
          }),
          y: { min: 0, max: 100, ticks: { color: tickColor, font: { size: 9 }, callback: v => v }, grid: { color: gridColor } },
        },
      },
    });
    const gamePerfChartOpts = {
      responsive: true, maintainAspectRatio: false, animation: false,
      parsing: false,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: {
        legend: {
          display: true, position: 'bottom',
          labels: { color: tickColor, font: { family: 'Inter', size: 10 }, boxWidth: 10, padding: 8 },
        },
        tooltip: {
          backgroundColor: '#404349',
          titleFont: { family: 'Inter' },
          bodyFont: { family: 'Inter' },
          padding: 10,
          callbacks: { title(items) { return fmtTimeAxis(items?.[0]?.parsed?.x); } },
        },
        ...zoomPluginOpts(),
      },
      scales: {
        x: timeXScale({
          ticks: { color: tickColor, maxTicksLimit: 6, font: { size: 9 }, callback: (v) => fmtTimeAxis(v) },
          grid: { display: false },
        }),
        y: { min: 0, max: 100, ticks: { color: tickColor, font: { size: 9 } }, grid: { color: gridColor } },
      },
    };
    const gamePerfChart = new Chart(document.getElementById('gamePerfChart'), {
      type: 'line',
      data: { datasets: [] },
      options: gamePerfChartOpts,
    });
    const gamePerfSessionsChart = new Chart(document.getElementById('gamePerfSessionsChart'), {
      type: 'bar',
      data: { labels: [], datasets: [] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#404349',
            callbacks: {
              afterLabel(ctx) {
                const s = ctx.dataset.sessionMeta?.[ctx.dataIndex];
                if (!s) return '';
                const lines = [
                  `Smooth ${s.smoothness_avg ?? '—'}%`,
                  `1% low ${s.hitch_ms_1pct ?? '—'}ms${s.mangohud || s.fps_avg != null ? ' (MangoHud)' : ' (proxy)'}`,
                  `${s.hitch_events ?? 0} hitches`,
                ];
                if (s.fps_avg != null) {
                  lines.splice(1, 0, `FPS avg ${s.fps_avg}${s.fps_1pct != null ? ` · 1% ${s.fps_1pct}` : ''}`);
                }
                return lines;
              },
            },
          },
          ...zoomPluginOpts(),
        },
        scales: {
          x: { ticks: { color: tickColor, maxTicksLimit: 6, font: { size: 9 } }, grid: { color: gridColor } },
          y: { min: 0, max: 100, ticks: { color: tickColor, font: { size: 9 } }, grid: { color: gridColor } },
        },
      },
    });

    const ALL_PULSE_CHARTS = [
      utilChart, bwChart, ioChart, sparkChart, stutterChart, indexChart, gamePerfChart, gamePerfSessionsChart,
    ];
    const CHART_DPR = Math.min(window.devicePixelRatio || 1, 1.4);
    ALL_PULSE_CHARTS.forEach(c => {
      if (c) c.options.devicePixelRatio = CHART_DPR;
    });
    applyChartChrome();

    function syncChartControlUI() {
      const paused = chartsPaused || chartZoomed;
      document.body.classList.toggle('charts-paused', paused);
      const statusText = chartZoomed ? 'Zoomed' : (chartsPaused ? 'Paused' : 'Live');
      const statusCls = chartZoomed ? 'is-zoom' : (chartsPaused ? 'is-paused' : '');
      document.querySelectorAll('#chartViewStatus, [data-charts-status]').forEach(el => {
        el.textContent = statusText;
        el.classList.remove('is-paused', 'is-zoom');
        if (statusCls) el.classList.add(statusCls);
      });
      document.querySelectorAll('#btnChartsPause, [data-charts-pause]').forEach(el => {
        el.hidden = chartsPaused && !chartZoomed;
        el.setAttribute('aria-pressed', chartsPaused ? 'true' : 'false');
        el.classList.toggle('is-active', chartsPaused && !chartZoomed);
      });
      document.querySelectorAll('#btnChartsResume, [data-charts-resume]').forEach(el => {
        el.hidden = !chartsPaused && !chartZoomed;
      });
      document.querySelectorAll('#btnChartsResetZoom, [data-charts-reset-zoom]').forEach(el => {
        el.hidden = !chartZoomed;
      });
    }

    function pauseCharts() {
      if (!chartRange) chartRange = getLiveChartWindow();
      chartPauseSnapshot = { min: chartRange.min, max: chartRange.max };
      chartsPaused = true;
      syncChartControlUI();
      applyChartRangeToAll(chartRange);
    }

    function resumeChartsLive() {
      chartsPaused = false;
      chartZoomed = false;
      chartRange = null;
      chartPauseSnapshot = null;
      clearChartRangeLimits();
      syncChartControlUI();
      refreshAllCharts();
    }

    function resetChartsZoom() {
      chartZoomed = false;
      if (chartPauseSnapshot) {
        // Explicit Pause then zoom: unzoom but keep the frozen window.
        chartsPaused = true;
        chartRange = { min: chartPauseSnapshot.min, max: chartPauseSnapshot.max };
      } else {
        // Zoom from live: Reset zoom returns to follow, does not leave a fake pause.
        chartsPaused = false;
        chartRange = null;
      }
      clearChartRangeLimits();
      if (chartsPaused && chartRange) applyChartRangeToAll(chartRange);
      syncChartControlUI();
      refreshAllCharts();
    }

    function refreshAllCharts() {
      try { renderCharts(); } catch (_) { /* ignore */ }
      try { renderSparkChart(); } catch (_) { /* ignore */ }
      try { renderStutterChart(); } catch (_) { /* ignore */ }
      try { renderIndexChart(); } catch (_) { /* ignore */ }
      try {
        if (lastLatest) {
          renderGamePerfLiveTrend(
            rawHistory,
            lastLatest.game_performance || {},
            lastLatest.game_totals || {},
          );
        }
      } catch (_) { /* ignore */ }
    }

    function syncChartViewUI() {
      document.querySelectorAll('[data-view]').forEach(btn => {
        btn.classList.toggle('active', +btn.dataset.view === chartViewSec);
      });
    }

    function setChartView(sec) {
      const n = +sec;
      if (!CHART_VIEW_OPTS.includes(n)) return;
      if (n === chartViewSec) return;
      chartViewSec = n;
      spanSec = n;
      persistChartView();
      syncChartViewUI();
      refreshAllCharts();
    }

    function wireChartLiveControls() {
      document.querySelectorAll('#btnChartsPause, [data-charts-pause]').forEach(el => {
        el.addEventListener('click', () => pauseCharts());
      });
      document.querySelectorAll('#btnChartsResume, [data-charts-resume]').forEach(el => {
        el.addEventListener('click', () => resumeChartsLive());
      });
      document.querySelectorAll('#btnChartsResetZoom, [data-charts-reset-zoom]').forEach(el => {
        el.addEventListener('click', () => resetChartsZoom());
      });
      syncChartControlUI();
    }
    wireChartLiveControls();
    document.querySelectorAll('[data-view]').forEach(btn => {
      btn.addEventListener('click', () => setChartView(btn.dataset.view));
    });
    syncChartViewUI();

    const utilDefs = [
      { key: 'cpu', label: 'CPU %', color: CHART.cpu, pick: h => h.cpu?.overall_pct ?? 0 },
      { key: 'gpu', label: 'GPU %', color: CHART.gpu, pick: h => histGpuPct(h) ?? 0 },
      { key: 'ram', label: 'RAM %', color: CHART.ram, pick: h => h.memory?.pct ?? 0 },
      { key: 'swap', label: 'Swap %', color: CHART.swap, pick: h => h.memory?.swap_pct ?? 0 },
      { key: 'gameCpu', label: 'Game process', color: CHART.gameCpu, pick: h => h.game_totals?.cpu_pct ?? 0 },
    ];
    const bwDefs = [
      { key: 'vramBw', label: 'VRAM GB/s', color: CHART.vramBw, yAxis: 'y', pick: h => h.bandwidth?.gpu?.vram_est_gbps ?? 0 },
      { key: 'dramBw', label: 'RAM bandwidth', color: CHART.dramBw, yAxis: 'y', pick: h => h.bandwidth?.memory?.dram_est_gbps ?? 0 },
      { key: 'gtt', label: 'Shared RAM', color: CHART.gtt, yAxis: 'y1', pick: h => h.bandwidth?.gpu?.gtt_rate_mbps ?? 0 },
    ];
    const ioDefs = [
      { key: 'netDn', label: 'Net ↓', color: CHART.netDn, pick: h => h.network?.down_mbps ?? 0 },
      { key: 'netUp', label: 'Net ↑', color: CHART.netUp, pick: h => h.network?.up_mbps ?? 0 },
      { key: 'diskR', label: 'Disk R', color: CHART.diskR, pick: h => h.disk?.read_mbps ?? 0 },
      { key: 'diskW', label: 'Disk W', color: CHART.diskW, pick: h => h.disk?.write_mbps ?? 0 },
    ];

    function buildToggles(container, defs, group) {
      container.innerHTML = defs.map(d => `<span class="chip on" data-g="${group}" data-k="${d.key}">${d.label}</span>`).join('');
      container.querySelectorAll('.chip').forEach(el => {
        el.onclick = () => {
          const k = el.dataset.k, g = el.dataset.g;
          enabled[g][k] = !enabled[g][k];
          el.classList.toggle('on', enabled[g][k]);
          el.classList.toggle('off', !enabled[g][k]);
          renderCharts();
        };
      });
    }

    function buildRollupMini(container, group) {
      container.innerHTML = [1, 60, 300, 600].map(r =>
        `<button class="btn" data-g="${group}" data-r="${r}">${ROLL_LABELS[r]}</button>`
      ).join('');
      container.querySelectorAll('.btn').forEach(b => {
        b.onclick = () => {
          const g = b.dataset.g, r = +b.dataset.r;
          chartRollup[g] = chartRollup[g] === r ? null : r;
          container.querySelectorAll('.btn').forEach(x => x.classList.toggle('active', chartRollup[g] === +x.dataset.r));
          renderCharts();
        };
      });
    }

    ['util', 'bw', 'io'].forEach(g => {
      buildToggles(document.getElementById(g + 'Toggles'), { util: utilDefs, bw: bwDefs, io: ioDefs }[g], g);
      buildRollupMini(document.getElementById(g + 'Rollup'), g);
    });

    document.querySelectorAll('#spanBtns .btn').forEach(b => {
      b.onclick = () => setChartView(b.dataset.view || b.dataset.span);
    });
    document.querySelectorAll('#rollupBtns .btn').forEach(b => {
      b.onclick = () => {
        document.querySelectorAll('#rollupBtns .btn').forEach(x => x.classList.remove('active'));
        b.classList.add('active');
        globalRollup = +b.dataset.roll;
        chartRollup.util = chartRollup.bw = chartRollup.io = null;
        document.querySelectorAll('.rollup-mini .btn').forEach(x => x.classList.remove('active'));
        renderCharts();
      };
    });

    const fmtTime = ts => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const tempClass = v => v == null ? '' : v >= 90 ? 'hot' : v >= 75 ? 'warn' : '';
    function gpuThermalProf() {
      return lastStatic?.gpu_thermal || lastLatest?.gpu?.discrete?.thermal_profile || {};
    }
    function gpuThermalState() {
      return lastLatest?.gpu?.discrete?.thermal_state || {};
    }
    function gpuJuncUiClass(junc) {
      const tp = gpuThermalProf();
      const ts = gpuThermalState();
      if (junc == null) return '';
      if (ts.throttling) return ' hot';
      if (ts.by_design) return ' info';
      const hot = tp.hot_c ?? 100;
      const warm = tp.warm_c;
      if (junc >= hot) return ' hot';
      if (warm != null && junc >= warm) return ' warn';
      return '';
    }
    function gpuJuncValCls(junc) {
      const ui = gpuJuncUiClass(junc);
      if (ui === ' hot') return 'temp hot';
      if (ui === ' warn') return 'temp warn';
      if (ui === ' info') return 'temp info';
      return 'temp';
    }
    function gpuJuncTrackCls(junc) { return gpuJuncValCls(junc); }
    function suppressedInsights() {
      return lastStatic?.suppressed_insights || [];
    }
    function resolvedInsights() {
      return lastStatic?.resolved_insights || [];
    }
    function isInsightSuppressed(iid) {
      return iid && suppressedInsights().includes(iid);
    }
    function isInsightResolved(iid) {
      return iid && resolvedInsights().includes(iid);
    }
    function hintUserStatus(h) {
      return h?.user_status || (isInsightResolved(h?.insight_id) ? 'resolved'
        : isInsightSuppressed(h?.insight_id) ? 'ignored' : 'outstanding');
    }
    function gpuTempPct(junc) {
      const throttle = hwScales.gpu_temp_max_c ?? gpuThermalProf().throttle_c ?? 110;
      return junc == null ? 0 : Math.min(100, (junc / throttle) * 100);
    }
    const pct = (v, max) => Math.min(100, Math.round((v / max) * 100));

    /**
     * Bucket history onto a fixed epoch grid so a sliding window does not
     * reshuffle past points every tick (that made Live overview lines "crawl").
     * Only the open last bucket still updates as new samples land.
     */
    function bucketize(cut, bucket) {
      if (!cut.length) return { labels: [], points: [] };
      if (bucket <= 1) return { labels: cut.map(h => fmtTime(h.ts)), points: cut };
      const t0 = Math.floor(cut[0].ts / bucket) * bucket;
      const end = cut.at(-1).ts;
      const buckets = [];
      for (let t = t0; t <= end; t += bucket) {
        const slice = cut.filter(h => h.ts >= t && h.ts < t + bucket);
        if (slice.length) buckets.push({ t, slice });
      }
      return {
        labels: buckets.map(b => fmtTime(b.t + bucket / 2)),
        points: buckets.map(b => b.slice),
      };
    }

    function avg(slice, fn) {
      const v = slice.map(fn).filter(x => x != null && !isNaN(x));
      return v.length ? +(v.reduce((a, b) => a + b, 0) / v.length).toFixed(2) : 0;
    }

    function renderOneChart(chart, defs, group, metaEl, rollup, dualAxis) {
      const win = getActiveChartWindow();
      const cut = rawHistory.filter(h => h.ts >= win.min && h.ts <= win.max + 0.05);
      const visual = (rollup && rollup > 1) ? rollup : 1;
      const { tsMids, slices: bucketPoints } = epochBucketsFromHistory(cut, visual);
      const rollLabel = visual === 1 ? '1 Hz' : (ROLL_LABELS[visual] || `${visual}s`);
      const winSec = Math.max(1, win.max - win.min);
      const modeTag = chartZoomed ? 'zoom' : (chartsPaused ? 'paused' : `${(winSec / 60).toFixed(winSec >= 60 ? 0 : 1)}m`);
      metaEl.textContent = `${modeTag} · ${rollLabel} · ${tsMids.length} pts · drag to zoom · Shift+drag pan · Ctrl+wheel`;
      // bucketPoints are always slices (arrays of samples). avg() handles len=1.
      // The old rollup<=1 path passed the array into pick() and threw on Live rollup,
      // leaving util/bw/io with empty datasets while meta still showed a point count.
      const getVal = (p, fn) => avg(p, fn);
      const activeDefs = defs.filter(d => enabled[group][d.key]);
      const enabledKey = activeDefs.map(d => d.key).join(',');
      const structKey = `${group}|${tsMids.length}|${tsMids[0] ?? ''}|${tsMids.at(-1) ?? ''}|${visual}|${enabledKey}|${chartsPaused}|${chartZoomed}`;
      const newDatasets = activeDefs.map(d => {
        const raw = bucketPoints.map(p => getVal(p, d.pick));
        const alpha = group === 'io' ? CHART_SMOOTH_ALPHA_SPIKY : CHART_SMOOTH_ALPHA;
        const smoothed = smoothChartSeries(`${group}:${d.key}`, raw, alpha);
        return {
          label: d.label,
          data: xySeries(tsMids, smoothed),
          borderColor: d.color, backgroundColor: d.color + '20',
          yAxisID: dualAxis ? (d.yAxis || 'y') : 'y',
          fill: group !== 'io', tension: .35, pointRadius: 0, borderWidth: 3,
        };
      });
      if (group === 'util') {
        lockPctAxis(chart, 'y');
      } else if (group === 'bw') {
        const yVals = newDatasets.filter(d => d.yAxisID === 'y').flatMap(d => d.data.map(p => p.y));
        const y1Vals = newDatasets.filter(d => d.yAxisID === 'y1').flatMap(d => d.data.map(p => p.y));
        if (yVals.length) stableAxisMax(chart, 'y', Math.max(...yVals));
        if (y1Vals.length) stableAxisMax(chart, 'y1', Math.max(...y1Vals), 50);
      } else if (group === 'io') {
        const vals = newDatasets.flatMap(d => d.data.map(p => p.y));
        if (vals.length) stableAxisMax(chart, 'y', Math.max(...vals), 5);
      }
      if (!chartInteractActive) applyLiveTimeAxis(chart, chartViewSec);
      if (structKey === chart._pulseStructKey && chart.data.datasets.length === newDatasets.length) {
        newDatasets.forEach((ds, i) => { chart.data.datasets[i].data = ds.data; });
      } else {
        chart._pulseStructKey = structKey;
        chart.data.datasets = newDatasets;
      }
      if (!chartInteractActive && canvasVisible(chart)) chart.update('none');
    }

    function renderCharts() {
      if (!isDrillOpen('drill-charts')) return;
      try {
        renderOneChart(utilChart, utilDefs, 'util', document.getElementById('utilMeta'), chartRollup.util ?? globalRollup);
      } catch (e) { console.warn('util chart render failed', e); }
      try {
        renderOneChart(bwChart, bwDefs, 'bw', document.getElementById('bwMeta'), chartRollup.bw ?? globalRollup, true);
      } catch (e) { console.warn('bw chart render failed', e); }
      try {
        renderOneChart(ioChart, ioDefs, 'io', document.getElementById('ioMeta'), chartRollup.io ?? globalRollup);
      } catch (e) { console.warn('io chart render failed', e); }
    }
