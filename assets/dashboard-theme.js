// SPDX-FileCopyrightText: 2026 Pulse contributors
// SPDX-License-Identifier: GPL-3.0-only
    /** Viewport wrap vs UI scale. rem in @media ignores html font-size / --ui-scale. */
    function syncUiWrap() {
      const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale');
      const scale = Math.max(1, Math.min(2, parseFloat(String(raw).trim()) || 1));
      const w = window.innerWidth;
      const wide = 75 * 16 * scale;      // 1200px @100%, 1800px @150%
      const tight = 68.75 * 16 * scale;  // 1100px @100%, 1650px @150%
      const roomy = 105 * 16 * scale;    // 1680px @100%, 2520px @150%
      document.body.classList.toggle('ui-wrap-wide', w <= wide);
      document.body.classList.toggle('ui-wrap-tight', w <= tight);
      document.body.classList.toggle('ui-wrap-roomy', w >= roomy);
      syncLabStage();
    }

    /** Leftover 1080p is a max. Stage height itself is --lab-stage-h (24rem). */
    function syncLabStage() {
      const viz = document.getElementById('vizPanel');
      if (!viz) return;
      const header = document.querySelector('header');
      const summary = document.getElementById('summaryBar');
      const head = viz.querySelector('.viz-panel-head');
      const main = document.querySelector('main');
      const pad = main ? (() => {
        const cs = getComputedStyle(main);
        return (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
      })() : 24;
      const dash = document.getElementById('pageDashboard');
      const gap = dash ? (parseFloat(getComputedStyle(dash).gap) || 8) : 8;
      const chrome = (header?.offsetHeight || 56)
        + (summary?.offsetHeight || 100)
        + (head?.offsetHeight || 44)
        + pad + gap * 2;
      const screen = Math.min(window.innerHeight || 1080, 1080);
      const maxH = Math.max(280, Math.round(screen - chrome));
      viz.style.setProperty('--lab-stage-max', `${maxH}px`);
      requestAnimationFrame(() => {
        try { sparkChart?.resize(); } catch (_) { /* chart not ready */ }
        try { indexChart?.resize(); } catch (_) { /* chart not ready */ }
        try { stutterChart?.resize(); } catch (_) { /* chart not ready */ }
      });
    }
    syncUiWrap();
    window.addEventListener('resize', syncUiWrap);

    /**
     * Canonical metric palette — mirrors CSS --m-* tokens.
     * Same metric key → same color on every chart, bar, and KPI.
     * Families stay grouped by function (CPU blues, GPU violets, …).
     */
    /* Single source of truth — live overview bars, dials, and chart all use these. */
    const HW_SCALE_DEFAULTS = {
      cpu_temp_min_c: 30,
      cpu_temp_max_c: 105,
      gpu_temp_max_c: 105,
      cpu_power_max_w: 125,
      gpu_power_max_w: 250,
    };
    let hwScales = { ...HW_SCALE_DEFAULTS };

    const METRIC = {
      cpu: '#38bdf8',       /* sky — CPU load + CPU °C */
      cpuDeep: '#0ea5e9',
      gpu: '#c084fc',       /* bright violet — GPU load + GPU °C + power/fan */
      gpuDeep: '#a855f7',
      gpuVram: '#e9d5ff',   /* pale violet — VRAM util / VRAM temp dial */
      gpuGtt: '#ddd6fe',
      mem: '#34d399',       /* emerald — RAM load + bus */
      memDeep: '#10b981',
      swap: '#a3e635',
      disk: '#fbbf24',      /* gold — disk activity / read */
      diskDeep: '#f59e0b',
      diskWrite: '#fb923c', /* orange — write */
      net: '#22d3ee',
      netDeep: '#0e7490',
      netUp: '#67e8f9',
      power: '#c084fc',     /* same family as GPU (GPU power) */
      thermal: '#fb7185',
      thermalWarn: '#fbbf24',
      stutter: '#e879f9',
      game: '#f472b6',
      league: '#818cf8',
    };
    // Chart.js series map (kept for existing call sites)
    const CHART = {
      cpu: METRIC.cpu,
      gpu: METRIC.gpu,
      ram: METRIC.mem,
      swap: METRIC.swap,
      vramBw: METRIC.gpuVram,
      dramBw: METRIC.mem,
      gtt: METRIC.gpuGtt,
      netDn: METRIC.net,
      netUp: METRIC.netUp,
      diskR: METRIC.disk,
      diskW: METRIC.diskWrite,
      diskAct: METRIC.disk,
      gameCpu: METRIC.game,
      stutter: METRIC.stutter,
      headroom: METRIC.league,
    };

    function syncMetricCssVars() {
      const root = document.documentElement.style;
      const map = {
        '--m-cpu': METRIC.cpu,
        '--m-cpu-deep': METRIC.cpuDeep,
        '--m-gpu': METRIC.gpu,
        '--m-gpu-deep': METRIC.gpuDeep,
        '--m-gpu-vram': METRIC.gpuVram,
        '--m-gpu-gtt': METRIC.gpuGtt,
        '--m-mem': METRIC.mem,
        '--m-mem-deep': METRIC.memDeep,
        '--m-swap': METRIC.swap,
        '--m-disk': METRIC.disk,
        '--m-disk-deep': METRIC.diskDeep,
        '--m-disk-write': METRIC.diskWrite,
        '--m-net': METRIC.net,
        '--m-net-deep': METRIC.netDeep,
        '--m-net-up': METRIC.netUp,
        '--m-power': METRIC.power,
        '--m-thermal': METRIC.thermal,
        '--m-thermal-warn': METRIC.thermalWarn,
        '--m-stutter': METRIC.stutter,
        '--m-game': METRIC.game,
        '--m-league': METRIC.league,
        '--chart-cpu': METRIC.cpu,
        '--chart-gpu': METRIC.gpu,
        '--chart-ram': METRIC.mem,
      };
      Object.entries(map).forEach(([k, v]) => root.setProperty(k, v));
      // Keep CHART in lockstep for Chart.js
      Object.assign(CHART, {
        cpu: METRIC.cpu,
        gpu: METRIC.gpu,
        ram: METRIC.mem,
        swap: METRIC.swap,
        vramBw: METRIC.gpuVram,
        dramBw: METRIC.mem,
        gtt: METRIC.gpuGtt,
        netDn: METRIC.net,
        netUp: METRIC.netUp,
        diskR: METRIC.disk,
        diskW: METRIC.diskWrite,
        diskAct: METRIC.disk,
        gameCpu: METRIC.game,
        stutter: METRIC.stutter,
        headroom: METRIC.league,
      });
    }
    syncMetricCssVars();

    /* ── Theme chrome (non-metric). Metrics stay on METRIC / --m-* ─────── */
    const THEME_MODE_DEFAULT = 'cosmic';
    const THEME_MODE_LABELS = {
      cosmic: 'Cosmic (desktop)',
      'cosmic-dark': 'Cosmic Dark',
      'cosmic-light': 'Cosmic Light',
      system: 'System',
      dark: 'Pulse Dark',
      light: 'Pulse Light',
    };
    const THEME_MODE_ALLOWED = [
      'cosmic', 'cosmic-dark', 'cosmic-light', 'system', 'dark', 'light',
    ];
    /** Built-in chrome packs — deliberately separate from metric families. */
    const CHROME_DARK = {
      available: true,
      is_dark: true,
      is_frosted: false,
      palette: 'pulse-dark',
      accent: '#e69bfd',
      accent_hover: '#cc90df',
      accent_soft: 'rgba(230, 155, 253, 0.14)',
      accent_on: '#000000',
      bg: '#1b1b1b',
      panel: 'rgba(64, 67, 73, 0.94)',
      panel_solid: '#404349',
      panel_elevated: '#5a5d63',
      panel_hover: '#53565c',
      text: '#cedbee',
      text_secondary: '#b8c4d8',
      muted: '#ababab',
      line: 'rgba(206, 219, 238, 0.16)',
      blue: '#63d0de',
      purple: '#e79bfd',
      green: '#92ce9b',
      orange: '#ffad00',
      amber: '#f6e062',
      hot: '#fca1a0',
      ok: '#92ce9b',
      glass: 'rgba(43, 46, 52, 0.94)',
      radius: 8,
      radius_lg: 16,
    };
    const CHROME_LIGHT = {
      available: true,
      is_dark: false,
      is_frosted: false,
      palette: 'pulse-light',
      accent: '#6d28d9',
      accent_hover: '#5b21b6',
      accent_soft: 'rgba(109, 40, 217, 0.12)',
      accent_on: '#ffffff',
      bg: '#e6ebf3',
      panel: '#ffffff',
      panel_solid: '#ffffff',
      panel_elevated: '#f4f6fb',
      panel_hover: '#eef1f7',
      text: '#111827',
      text_secondary: '#374151',
      muted: '#4b5563',
      line: 'rgba(17, 24, 39, 0.14)',
      blue: '#0369a1',
      purple: '#6d28d9',
      green: '#047857',
      orange: '#b45309',
      amber: '#a16207',
      hot: '#b91c1c',
      ok: '#047857',
      glass: 'rgba(255, 255, 255, 0.92)',
      radius: 8,
      radius_lg: 16,
    };

    let themeMode = THEME_MODE_DEFAULT;
    let lastChromeKey = '';
    let themeSaveBusy = false;
    let themeSavePending = null; // last { mode, silent } while a POST is in flight
    let storeWriteGen = 0; // bump on Options POST so an older GET cannot paint over it
    let themePreviewMode = null; // hover preview without commit

    function softHex(c, aHex) {
      if (!c || typeof c !== 'string') return null;
      if (c.startsWith('rgba') || c.startsWith('rgb')) return null;
      if (c.startsWith('#') && (c.length === 7 || c.length === 4)) {
        if (c.length === 4) {
          const r = c[1], g = c[2], b = c[3];
          return `#${r}${r}${g}${g}${b}${b}${aHex}`;
        }
        return `${c}${aHex}`;
      }
      return null;
    }

    function prefersDarkSystem() {
      try {
        return window.matchMedia('(prefers-color-scheme: dark)').matches;
      } catch (_) {
        return true;
      }
    }

    function resolveChromeTokens(mode, cosmic) {
      const m = mode || THEME_MODE_DEFAULT;
      const darkPack = lastStatic?.cosmic_theme_dark;
      const lightPack = lastStatic?.cosmic_theme_light;
      if (m === 'cosmic') {
        if (cosmic?.available) return cosmic;
        return CHROME_DARK;
      }
      if (m === 'cosmic-dark') return darkPack?.available ? darkPack : CHROME_DARK;
      if (m === 'cosmic-light') return lightPack?.available ? lightPack : CHROME_LIGHT;
      if (m === 'system') return prefersDarkSystem() ? CHROME_DARK : CHROME_LIGHT;
      if (m === 'light') return CHROME_LIGHT;
      return CHROME_DARK;
    }

    /**
     * Map COSMIC / chrome token object onto CSS variables.
     * Sets both Pulse chrome vars (--bg, --text, …) and --cosmic-* mirrors
     * without removing unrelated custom properties on :root.
     */
    function applyThemeCssVars(t) {
      if (!t || typeof t !== 'object') return;
      const root = document.documentElement.style;
      const set = (k, v) => { if (v != null && v !== '') root.setProperty(k, v); };

      // Primary chrome tokens (existing dashboard stylesheet)
      set('--bg', t.bg || t['bg-color']);
      set('--panel', t.is_frosted ? (t.glass || t.panel) : (t.panel || t.bg));
      set('--panel-solid', t.panel_solid || t.panel);
      set('--panel-elevated', t.panel_elevated);
      set('--panel-hover', t.panel_hover);
      set('--text', t.text || t['text-color']);
      set('--text-secondary', t.text_secondary);
      set('--muted', t.muted);
      set('--accent', t.accent);
      set('--accent-hover', t.accent_hover || t.accent);
      set('--accent-soft', t.accent_soft);
      set('--accent-on', t.accent_on != null ? t.accent_on : '#000000');
      set('--blue', t.blue);
      set('--purple', t.purple);
      set('--green', t.green);
      set('--orange', t.orange);
      set('--amber', t.amber);
      set('--hot', t.hot);
      set('--ok', t.ok);
      set('--line', t.line);
      set('--glass', t.glass);
      if (t.radius != null) set('--radius', typeof t.radius === 'number' ? `${t.radius}px` : t.radius);
      if (t.radius_lg != null) set('--radius-lg', typeof t.radius_lg === 'number' ? `${t.radius_lg}px` : t.radius_lg);
      set('--glow-accent', t.accent_soft);
      const gb = softHex(t.blue, '1a');
      const gm = softHex(t.green, '12');
      const gg = softHex(t.purple || t.accent, '14');
      if (gb) set('--glow-blue', gb);
      if (gm) set('--glow-mem', gm);
      if (gg) set('--glow-gpu', gg);

      // --cosmic-* mirrors for theme-sync consumers / future CSS
      const cosmicSkip = new Set(['available', 'chart', 'is_dark', 'is_frosted', 'mtime', 'palette', 'space_m']);
      Object.keys(t).forEach((key) => {
        if (cosmicSkip.has(key)) return;
        const val = t[key];
        if (val == null || typeof val === 'object') return;
        const cssName = '--cosmic-' + String(key).replace(/_/g, '-');
        set(cssName, typeof val === 'number' && /radius/.test(key) ? `${val}px` : val);
      });
      // Common aliases
      if (t.bg || t['bg-color']) set('--cosmic-bg-color', t.bg || t['bg-color']);
      if (t.text || t['text-color']) set('--cosmic-text-color', t.text || t['text-color']);
      if (t.accent) set('--cosmic-accent', t.accent);
    }

    function applyChromeTheme(t, { force = false } = {}) {
      if (!t) return false;
      const key = JSON.stringify([
        t.mtime, t.palette, t.accent, t.bg, t.is_frosted, t.panel, t.panel_elevated, t.panel_hover,
        t.text, t.is_dark,
      ]);
      if (!force && key === lastChromeKey) return false;
      lastChromeKey = key;

      applyThemeCssVars(t);

      document.body.classList.toggle('cosmic-frosted', !!t.is_frosted);
      document.body.classList.toggle('theme-light', t.is_dark === false);
      document.body.classList.toggle('theme-dark', t.is_dark !== false);
      if (typeof applyChartChrome === 'function') {
        try { applyChartChrome(); } catch (_) { /* charts script may not be loaded yet */ }
      }
      const themeMeta = document.querySelector('meta[name="theme-color"]');
      if (themeMeta && (t.bg || t['bg-color'])) themeMeta.content = t.bg || t['bg-color'];
      // Metrics intentionally unchanged — chrome only.
      return true;
    }

    /** @deprecated name kept for call sites; routes through chrome resolver */
    function applyCosmicTheme(t) {
      if (themeMode !== 'cosmic') return false;
      if (!t?.available) return false;
      return applyChromeTheme(t);
    }

    function paintThemePreview(tokens, mode) {
      const el = document.getElementById('themePreview');
      if (!el || !tokens) return;
      const map = {
        '--tp-bg': tokens.bg,
        '--tp-panel': tokens.panel_solid || tokens.panel,
        '--tp-elevated': tokens.panel_elevated,
        '--tp-glass': tokens.glass || tokens.panel,
        '--tp-text': tokens.text,
        '--tp-text-sec': tokens.text_secondary,
        '--tp-muted': tokens.muted,
        '--tp-line': tokens.line,
        '--tp-accent': tokens.accent,
        '--tp-accent-on': tokens.accent_on,
      };
      Object.entries(map).forEach(([k, v]) => {
        if (v != null) el.style.setProperty(k, v);
      });
      const sw = document.getElementById('themePreviewSwatches');
      if (sw) {
        const colors = [
          tokens.bg, tokens.panel_solid || tokens.panel, tokens.accent,
          tokens.text, tokens.muted, tokens.hot, tokens.ok,
        ].filter(Boolean);
        sw.innerHTML = colors.map(c =>
          `<span class="theme-preview-swatch" style="background:${c}" title="${c}"></span>`
        ).join('');
      }
      const cap = document.getElementById('themePreviewCaption');
      if (cap) {
        const label = THEME_MODE_LABELS[mode] || mode;
        const pal = tokens.palette || (tokens.is_dark === false ? 'light' : 'dark');
        cap.textContent = `Preview · ${label} · ${pal}` +
          (tokens.is_frosted ? ' · frosted' : '');
      }
    }

    function updateThemeStatus(cosmic) {
      const el = document.getElementById('themeStatus');
      if (!el) return;
      if (themeMode === 'cosmic') {
        if (cosmic?.available) {
          const mode = cosmic.is_dark === false ? 'Light' : 'Dark';
          const frost = cosmic.is_frosted ? ' · frosted' : '';
          const plat = lastStatic?.platform;
          const hostBits = [];
          if (plat?.is_pop && plat.os?.version) hostBits.push(`Pop!_OS ${plat.os.version}`);
          else if (plat?.is_pop) hostBits.push('Pop!_OS');
          if (plat?.is_system76 && plat.vendor?.model_short) hostBits.push(plat.vendor.model_short);
          const host = hostBits.length ? ` · ${hostBits.join(' · ')}` : '';
          el.innerHTML = `Desktop: <strong>${cosmic.palette || 'COSMIC'}</strong> · ${mode}${frost}${host}`;
        } else {
          el.innerHTML = 'Cosmic theme <strong>not detected</strong> — using Pulse dark chrome.';
        }
      } else if (themeMode === 'cosmic-dark' || themeMode === 'cosmic-light') {
        const pack = themeMode === 'cosmic-light'
          ? lastStatic?.cosmic_theme_light
          : lastStatic?.cosmic_theme_dark;
        const name = pack?.palette || (themeMode === 'cosmic-light' ? 'cosmic-light' : 'cosmic-dark');
        const src = pack?.available ? 'Pop COSMIC pack' : 'Pulse fallback';
        el.innerHTML = `<strong>${THEME_MODE_LABELS[themeMode]}</strong> · ${name} · ${src}`;
      } else if (themeMode === 'system') {
        el.innerHTML = `Browser preference: <strong>${prefersDarkSystem() ? 'dark' : 'light'}</strong>`;
      } else {
        el.innerHTML = `Override: <strong>${THEME_MODE_LABELS[themeMode] || themeMode}</strong>`;
      }
    }

    function syncThemeModeUi() {
      document.querySelectorAll('.theme-mode-opt').forEach(lab => {
        const mode = lab.dataset.mode;
        const on = mode === themeMode;
        lab.classList.toggle('is-active', on);
        const input = lab.querySelector('input[type="radio"]');
        if (input) input.checked = on;
      });
    }

    function applyThemeFromSettings({ force = false, previewMode = null } = {}) {
      const mode = previewMode || themeMode;
      const cosmic = lastStatic?.cosmic_theme || storeCache?.cosmic_theme;
      // Prefer live cosmic from metrics bootstrap; store may not carry it.
      const tokens = resolveChromeTokens(mode, lastStatic?.cosmic_theme || cosmic);
      let changed = false;
      if (!previewMode) {
        changed = applyChromeTheme(tokens, { force });
        updateThemeStatus(lastStatic?.cosmic_theme);
      }
      paintThemePreview(tokens, mode);
      return changed;
    }

    async function setThemeMode(mode, { silent = false } = {}) {
      if (!THEME_MODE_ALLOWED.includes(mode)) return;
      themeMode = mode;
      themePreviewMode = null;
      syncThemeModeUi();
      applyThemeFromSettings({ force: true });
      themeSavePending = { mode, silent };
      flushThemeSave();
    }

    async function flushThemeSave() {
      if (themeSaveBusy) return;
      themeSaveBusy = true;
      try {
        while (themeSavePending) {
          const job = themeSavePending;
          themeSavePending = null;
          storeWriteGen += 1;
          try {
            const res = await fetch('/api/store', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ theme_mode: job.mode }),
            });
            const data = await res.json();
            if (!data.ok) throw new Error(data.error || 'failed');
            storeCache = data;
            storeWriteGen += 1; // drop GETs that raced this POST
            if (!themeSavePending && !job.silent) {
              showOptionsMsg(`Theme: ${THEME_MODE_LABELS[job.mode] || job.mode}`, true);
            }
          } catch (e) {
            if (!themeSavePending && !job.silent) {
              showOptionsMsg(e.message || 'Could not save theme', false);
            }
          }
        }
      } finally {
        themeSaveBusy = false;
        if (themeSavePending) flushThemeSave();
      }
    }

    function wireThemeControls() {
      const list = document.getElementById('themeModeList');
      if (!list) return;
      list.querySelectorAll('.theme-mode-opt').forEach(lab => {
        const mode = lab.dataset.mode;
        lab.addEventListener('mouseenter', () => {
          themePreviewMode = mode;
          applyThemeFromSettings({ previewMode: mode });
        });
        lab.addEventListener('mouseleave', () => {
          themePreviewMode = null;
          applyThemeFromSettings({ previewMode: null });
        });
        lab.addEventListener('change', (e) => {
          if (e.target?.name === 'themeMode' && e.target.checked) {
            setThemeMode(mode);
          }
        });
        lab.addEventListener('click', (e) => {
          // Label click selects radio; change handler saves.
          if (e.target?.type === 'radio') return;
          const input = lab.querySelector('input[type="radio"]');
          if (input && !input.checked) {
            input.checked = true;
            setThemeMode(mode);
          }
        });
      });
      try {
        const mq = window.matchMedia('(prefers-color-scheme: dark)');
        const onChange = () => {
          if (themeMode === 'system') applyThemeFromSettings({ force: true });
        };
        if (mq.addEventListener) mq.addEventListener('change', onChange);
        else if (mq.addListener) mq.addListener(onChange);
      } catch (_) { /* ignore */ }
    }
    wireThemeControls();
