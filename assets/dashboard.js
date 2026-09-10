// SPDX-FileCopyrightText: 2026 Pulse contributors
// SPDX-License-Identifier: GPL-3.0-only

    function vsFmtPlain(n) {
      if (n == null || isNaN(n)) return '—';
      const sign = n > 0 ? '+' : '';
      return `${sign}${n}%`;
    }

    function vsFmt(n) {
      if (n == null || isNaN(n)) return '—';
      const cls = n >= 0 ? 'vs-pos' : 'vs-neg';
      return `<span class="${cls}">${vsFmtPlain(n)}</span>`;
    }

    function updateRankRow(tr, r) {
      if (!tr) return;
      const liveBar = smoothDisplayPct(`rank-live-${r.part}`, r.liveBar);
      setMeterWidth(tr.querySelector('[data-live-fill]'), liveBar);
      const liveText = tr.querySelector('[data-live-text]');
      if (liveText) {
        if (r.part === 'CPU') {
          liveText.textContent = `${liveBar}% load · ${smoothDisplayPct(`rank-head-${r.part}`, r.headroom_pct)}% headroom`;
        } else if (r.part === 'GPU') {
          liveText.textContent = `${liveBar}% GPU · ${r.vram_gbps_live} GB/s VRAM (${r.vram_bw_busy_pct}% BW)`;
        } else {
          liveText.textContent = `${r.live_gbps_est} GB/s est. · ${liveBar}% pressure`;
        }
      }
      const vsAvg = tr.querySelector('[data-vs-avg]');
      const vsEnth = tr.querySelector('[data-vs-enth]');
      if (vsAvg) vsAvg.innerHTML = vsFmt(r.vs_avg_pct);
      if (vsEnth) vsEnth.innerHTML = vsFmt(r.vs_enthusiast_pct);
    }

    function renderComparison(c, mem, pulseRoot = '') {
      if (!c) return;
      if (!isDrillOpen('drill-league')) return;
      const sessionIdx = smoothDisplayPct('session-index', c.session_index);
      document.getElementById('sessionIndex').textContent = `${sessionIdx}/100`;
      setTierBadge(document.getElementById('compositeRank'), c.composite_rank);
      document.getElementById('compositeSub').textContent =
        `Composite tier ${c.composite_tier}/100 · CPU+GPU+RAM blend`;

      const rows = [
        {
          part: 'CPU', ...c.cpu,
          live: `${c.cpu.live_pct}% load · ${c.cpu.headroom_pct}% headroom`,
          liveBar: c.cpu.live_pct,
        },
        {
          part: 'GPU', ...c.gpu,
          live: `${c.gpu.live_pct}% GPU · ${c.gpu.vram_gbps_live} GB/s VRAM (${c.gpu.vram_bw_busy_pct}% BW)`,
          liveBar: c.gpu.live_pct,
        },
        {
          part: 'RAM', ...c.memory,
          live: `${c.memory.live_gbps_est} GB/s est. · ${c.memory.live_pressure_pct}% pressure`,
          liveBar: c.memory.live_pressure_pct,
        },
      ];

      const structKey = rows.map(r => `${r.part}:${r.name}:${r.tier_rank}:${r.tier_score}`).join('|');
      if (structKey !== lastRankStructKey) {
        lastRankStructKey = structKey;
        const partHw = { CPU: 'cpu', GPU: 'gpu', RAM: 'memory' };
        document.getElementById('rankBody').innerHTML = rows.map(r => `
          <tr data-rank-part="${r.part}" data-hw="${partHw[r.part] || 'cpu'}">
            <td>${partLabel(r.part)}</td>
            <td>${hwIdentityCell(r)}</td>
            <td>${tierBadge(r.tier_rank, false)}</td>
            <td><div class="rank-bar tier"><span data-tier-fill style="width:0%"></span></div> <span data-tier-score>${r.tier_score}</span></td>
            <td><div class="rank-bar live"><span data-live-fill style="width:0%"></span></div> <span class="sub" data-live-text style="margin:0;display:inline">${esc(r.live)}</span></td>
            <td data-vs-avg>${vsFmt(r.vs_avg_pct)}</td>
            <td data-vs-enth>${vsFmt(r.vs_enthusiast_pct)}</td>
          </tr>`).join('');
        rows.forEach(r => {
          const tr = document.querySelector(`[data-rank-part="${r.part}"]`);
          setMeterWidth(tr?.querySelector('[data-tier-fill]'), r.tier_score);
          updateRankRow(tr, r);
        });
      } else {
        rows.forEach(r => updateRankRow(document.querySelector(`[data-rank-part="${r.part}"]`), r));
      }

      const conf = mem?.confidence || 'unknown';
      const note = mem?.note || '';
      const probeKey = `${conf}|${mem?.label || ''}|${note}|${pulseRoot}`;
      if (probeKey !== lastMemProbeKey) {
        lastMemProbeKey = probeKey;
        document.getElementById('memProbeNote').innerHTML = conf === 'exact'
          ? `RAM spec: <strong>${mem.label}</strong> (probed via DMI)`
          : `RAM spec: <strong>${mem?.label || 'unknown'}</strong> (${conf}) — ${note}
             <button type="button" id="probeBtn">Probe exact speed</button>`;
        const btn = document.getElementById('probeBtn');
        if (btn) btn.onclick = async () => {
          btn.textContent = 'Need sudo in terminal…';
          btn.disabled = true;
          const probe = pulseRoot ? `${pulseRoot}/probe_memory.py` : 'probe_memory.py';
          alert(`Run in terminal for exact RAM speed:\\n\\nsudo python3 '${probe}'\\n\\nThen refresh this page.`);
        };
      }
    }

    function ensureBwPanels() {
      const gpu = document.getElementById('gpuBw');
      if (!gpu.dataset.init) {
        gpu.innerHTML = `
          <div class="bw-head">
            <div class="bw-big" id="gpuBwBig">—</div>
            <div class="bw-sub" id="gpuBwSub">—</div>
          </div>
          <div class="meter-label"><span id="gpuBwMeterLbl">—</span><span id="gpuBwEngineLbl">—</span></div>
          <div class="meter gpu"><span id="gpuBwMeterFill" style="width:0%"></span></div>
          <div class="bw-row">
            <div class="bw-kv"><span class="k">PCIe link</span><span class="v" id="gpuBwPcie">—</span></div>
            <div class="bw-kv"><span class="k">Shared system RAM</span><span class="v" id="gpuBwGtt">—</span></div>
            <div class="bw-kv"><span class="k">VRAM fill</span><span class="v" id="gpuBwVramFill">—</span></div>
          </div>`;
        gpu.dataset.init = '1';
      }
      const mem = document.getElementById('memBw');
      if (!mem.dataset.init) {
        mem.innerHTML = `
          <div class="bw-head">
            <div class="bw-big mem" id="memBwBig">—</div>
            <div class="bw-sub" id="memBwSub">—</div>
          </div>
          <div class="meter-label"><span id="memBwMeterLbl">—</span><span id="memBwPsiLbl">—</span></div>
          <div class="meter mem"><span id="memBwMeterFill" style="width:0%"></span></div>
          <div class="bw-row">
            <div class="bw-kv"><span class="k">Page fault estimate</span><span class="v" id="memBwFault">—</span></div>
            <div class="bw-kv"><span class="k">Page churn</span><span class="v" id="memBwPages">—</span></div>
            <div class="bw-kv"><span class="k">Swap I/O</span><span class="v" id="memBwSwap">—</span></div>
            <div class="bw-kv"><span class="k">Active / cached</span><span class="v" id="memBwActive">—</span></div>
          </div>`;
        mem.dataset.init = '1';
      }
    }

    function updateGpuBwTitle(s) {
      const el = document.getElementById('gpuBwTitle');
      if (!el || !s) return;
      const gpu = s.gpu_model || s.rig?.gpu?.model || 'GPU';
      const maker = s.rig?.gpu?.maker;
      el.textContent = maker ? `GPU Bandwidth — ${maker} ${gpu}` : `GPU Bandwidth — ${gpu}`;
    }

    function smartMetaLine(smart, temp) {
      if (!smart) {
        return temp != null ? ` · ${temp}°C` : '';
      }
      const parts = [];
      if (temp != null) parts.push(`${temp}°C`);
      else if (smart.temperature_c != null) parts.push(`${smart.temperature_c}°C`);
      if (smart.percentage_used != null) parts.push(`${smart.percentage_used}% worn`);
      if (smart.available_spare != null) parts.push(`${smart.available_spare}% spare`);
      if (smart.tb_written != null) parts.push(`${smart.tb_written} TB written`);
      if (smart.critical_warning) parts.push('SMART warn');
      return parts.length ? ` · ${parts.join(' · ')}` : '';
    }

    function renderStorageDrives(s, l) {
      const el = document.getElementById('driveList');
      if (!el) return;
      const drives = s?.rig?.storage || s?.storage || [];
      const sensors = l?.sensors || [];
      const smartMap = l?.nvme_smart?.drives || {};
      const tempById = {};
      sensors.filter(t => t.id?.startsWith('nvme_')).forEach(t => {
        const name = t.drive?.name || t.id.replace(/^nvme_/, '');
        tempById[name] = t.value;
      });
      if (!drives.length) {
        el.innerHTML = '<p class="storage-note">No NVMe drives detected on this system.</p>';
        return;
      }
      const smartSig = Object.keys(smartMap).sort().map(k => {
        const h = smartMap[k] || {};
        return `${k}:${h.percentage_used}:${h.tb_written}:${h.critical_warning}`;
      }).join('|');
      const key = drives.map(d => `${d.id}:${d.label}:${d.size}`).join('|') + '|' + smartSig
        + '|' + (l?.nvme_smart?.readable ? '1' : '0');
      if (el.dataset.key === key) {
        el.querySelectorAll('.drive-card').forEach((card, i) => {
          const d = drives[i];
          if (!d) return;
          const temp = tempById[d.name];
          const smart = smartMap[d.name] || d.smart;
          const meta = card.querySelector('.drive-meta');
          if (meta) {
            const pci = d.pci_bdf ? ` · ${d.pci_bdf}` : '';
            meta.textContent = `${d.size || '—'}${smartMetaLine(smart, temp)}${pci}`;
          }
          card.classList.toggle('warn', !!(smart?.critical_warning || (smart?.percentage_used ?? 0) >= 90));
        });
        return;
      }
      el.dataset.key = key;
      const smartNote = l?.nvme_smart && !l.nvme_smart.readable
        ? `<p class="storage-note">${esc(l.nvme_smart.message || 'NVMe SMART not readable yet.')} <button type="button" class="btn" data-open-guidance-tools>Guidance → Data tools</button></p>`
        : '';
      el.innerHTML = smartNote + drives.map(d => {
        const temp = tempById[d.name];
        const smart = smartMap[d.name] || d.smart;
        const pci = d.pci_bdf ? ` · ${d.pci_bdf}` : '';
        const warn = !!(smart?.critical_warning || (smart?.percentage_used ?? 0) >= 90);
        return `<div class="drive-card${warn ? ' warn' : ''}" data-drive="${esc(d.name)}">
          <span class="drive-brand">${esc(d.brand || 'NVMe')}</span>
          <span class="drive-name">${esc(d.label || d.model || d.name)}</span>
          <span class="drive-meta">${esc(d.size || '—')}${esc(smartMetaLine(smart, temp))}${esc(pci)}</span>
        </div>`;
      }).join('');
    }

    function renderBandwidth(l) {
      if (!isDrillOpen('drill-bandwidth')) return;
      const g = l.bandwidth?.gpu || {}, m = l.bandwidth?.memory || {};
      const vramPct = g.vram_busy_pct ?? 0;
      const dramPct = m.dram_util_pct ?? 0;
      ensureBwPanels();
      document.getElementById('gpuBwBig').innerHTML =
        `${g.vram_est_gbps ?? '—'} <small style="font-size:1.15rem;color:var(--muted)">GB/s</small>`;
      document.getElementById('gpuBwSub').textContent =
        `Peak ~${g.vram_peak_gbps} GB/s · MCLK ${g.mclk_mhz ?? '—'} MHz`;
      document.getElementById('gpuBwMeterLbl').textContent = `Memory bus ${vramPct}% busy`;
      document.getElementById('gpuBwEngineLbl').textContent =
        `${g.vram_est_gbps ?? '—'} GB/s · MCLK ${g.mclk_mhz ?? '—'} MHz`;
      setMeterWidth(document.getElementById('gpuBwMeterFill'), vramPct);
      document.getElementById('gpuBwPcie').textContent = g.pcie_link || '—';
      document.getElementById('gpuBwGtt').textContent =
        `${g.gtt_used_mb ?? '—'} MB · ${g.gtt_rate_mbps ?? 0} MB/s churn`;
      document.getElementById('gpuBwVramFill').textContent =
        `${l.gpu?.discrete?.vram_used_mb ?? '—'} / ${l.gpu?.discrete?.vram_total_mb ?? '—'} MB`;

      document.getElementById('memBwBig').innerHTML =
        `${m.dram_est_gbps ?? '—'} <small style="font-size:1.15rem;color:var(--muted)">GB/s demand</small>`;
      document.getElementById('memBwSub').textContent =
        `${m.dram_util_pct ?? 0}% of ${m.dram_peak_gbps} GB/s ceiling · workload model (not a hw counter)`;
      document.getElementById('memBwMeterLbl').textContent = `RAM bandwidth ${dramPct}%`;
      document.getElementById('memBwPsiLbl').textContent = `Memory wait ${m.psi_avg10 ?? 0}%`;
      setMeterWidth(document.getElementById('memBwMeterFill'), dramPct);
      document.getElementById('memBwFault').textContent =
        `${m.dram_fault_gbps ?? m.fault_proxy_gbps ?? 0} GB/s · ${(m.pgmajfault_per_s ?? 0).toLocaleString()}/s major faults`;
      document.getElementById('memBwPages').textContent =
        `${(m.pgfault_per_s ?? 0).toLocaleString()}/s minor · ${(m.pgmajfault_per_s ?? 0).toLocaleString()}/s major`;
      document.getElementById('memBwSwap').textContent =
        `↓${m.swap_in_kbps ?? 0} ↑${m.swap_out_kbps ?? 0} KB/s`;
      document.getElementById('memBwActive').textContent =
        `${m.active_gb ?? '—'} GB active · ${m.cached_gb ?? '—'} GB cache`;
    }

    function fmtAgo(ts) {
      if (!ts) return '';
      const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
      if (s < 60) return `${s}s ago`;
      if (s < 3600) return `${Math.floor(s / 60)}m ago`;
      return `${Math.floor(s / 3600)}h ago`;
    }

    function copyText(text, btn) {
      const done = () => { btn.textContent = 'Copied'; btn.classList.add('ok'); setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('ok'); }, 1600); };
      if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(() => {});
      } else {
        const t = document.createElement('textarea');
        t.value = text; document.body.appendChild(t); t.select();
        try { document.execCommand('copy'); done(); } catch {}
        t.remove();
      }
    }

    const KIND_LABEL = { cmd: 'Terminal', game: 'In-game', steam: 'Steam', bios: 'BIOS', file: 'File' };
    const openPanels = new Set();
    let lastWarningsKey = '', lastFixesKey = '', lastGameIssuesKey = '', lastSensorKey = '';
    let cachedIssuesByGame = null, lastIssuesFetchKey = '';
    let lastActiveGameId = null;
    let gameWasRunning = false;
    let lastWarningsPillsKey = '', lastMemProbeKey = '', lastProcKey = '', lastSensorStripKey = '';
    let panelScrollState = {};
    let lastRankStructKey = '';
    const meterSmooth = new Map();
    const displaySmooth = new Map();
    /** @type {Map<string, {smooth: number[], raw: number[]}>} */
    const chartSeriesSmooth = new Map();
    /** Soft ceilings for rate→activity normalization (rise fast, fall slow). */
    const rateCeilSmooth = new Map();
    const METER_SMOOTH_ALPHA = 0.22;
    const DISPLAY_SMOOTH_ALPHA = 0.18;
    const CHART_SMOOTH_ALPHA = 0.28;
    /** Spiky rates (disk/net): stronger damping so sporadic blips don't thrash the line. */
    const CHART_SMOOTH_ALPHA_SPIKY = 0.12;
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function clampPct(p) {
      return Math.min(100, Math.max(0, Number(p) || 0));
    }

    function smoothPct(el, raw) {
      const v = clampPct(raw);
      if (prefersReducedMotion) return v;
      const key = el.id || el.dataset.smoothKey || el;
      const prev = meterSmooth.has(key) ? meterSmooth.get(key) : v;
      const next = prev + METER_SMOOTH_ALPHA * (v - prev);
      meterSmooth.set(key, next);
      return next;
    }

    function smoothDisplay(key, raw) {
      const v = Number(raw);
      if (raw == null || isNaN(v)) return raw;
      if (prefersReducedMotion) return v;
      const prev = displaySmooth.has(key) ? displaySmooth.get(key) : v;
      const next = prev + DISPLAY_SMOOTH_ALPHA * (v - prev);
      displaySmooth.set(key, next);
      return next;
    }

    function smoothDisplayPct(key, raw) {
      return Math.round(smoothDisplay(key, raw));
    }

    /**
     * Temporal EMA for chart series. Keys must be stable (series id only — not
     * window timestamps) so a sliding 5‑min window doesn't reset smoothing.
     * When the window slides, each new sample is blended from the previous
     * smoothed value at the matching wall-clock slot (aligned to series end).
     */
    function smoothChartSeries(key, data, alpha = CHART_SMOOTH_ALPHA) {
      if (!data || !data.length) return data || [];
      if (prefersReducedMotion) {
        chartSeriesSmooth.set(key, { smooth: data.slice(), raw: data.slice() });
        return data.slice();
      }
      const a = Math.min(1, Math.max(0.02, alpha));
      const state = chartSeriesSmooth.get(key);
      const prevS = state?.smooth;
      const prevR = state?.raw;

      // Causal seed when first seen or length jumped a lot (bootstrap / span change)
      if (!prevS || !prevS.length || Math.abs(prevS.length - data.length) > 8) {
        const out = [];
        let s = Number(data[0]) || 0;
        for (const raw of data) {
          const v = Number(raw) || 0;
          s = s + a * (v - s);
          out.push(+s.toFixed(2));
        }
        chartSeriesSmooth.set(key, { smooth: out, raw: data.map(Number) });
        return out;
      }

      // Align to series end: length can grow/shrink as the 5m window fills.
      // Prefer shifted baseline when the window advanced by ~1 bucket.
      const out = new Array(data.length);
      const lenDiff = data.length - prevS.length;
      for (let i = 0; i < data.length; i++) {
        const v = Number(data[i]) || 0;
        // Map this index onto previous series (end-aligned)
        let baseIdx = i - lenDiff;
        if (prevR && prevR.length === prevS.length && baseIdx >= 0 && baseIdx < prevR.length) {
          const dStay = Math.abs(v - (prevR[baseIdx] ?? v));
          const dShift = baseIdx + 1 < prevR.length
            ? Math.abs(v - (prevR[baseIdx + 1] ?? v))
            : Infinity;
          // Sliding window: current raw[i] ≈ previous raw[i+1]
          if (dShift + 0.05 < dStay) baseIdx = baseIdx + 1;
        }
        // Unchanged raw at a frozen bucket → keep prior smooth value (no float crawl)
        if (
          baseIdx >= 0 && baseIdx < prevS.length && prevR
          && Math.abs(v - (prevR[baseIdx] ?? NaN)) < 0.08
        ) {
          out[i] = prevS[baseIdx];
          continue;
        }
        let p;
        if (baseIdx >= 0 && baseIdx < prevS.length) p = prevS[baseIdx];
        else if (i > 0) p = out[i - 1];
        else p = v;
        out[i] = +(p + a * (v - p)).toFixed(2);
      }
      chartSeriesSmooth.set(key, { smooth: out, raw: data.map(x => Number(x) || 0) });
      return out;
    }

    /** Soft max for rate series: rises with peaks, decays slowly so scale doesn't thrash. */
    function softRateCeil(key, values, floor = 16) {
      const nums = (values || []).map(Number).filter(v => !isNaN(v) && v >= 0);
      const peak = nums.length ? Math.max(floor, ...nums) : floor;
      const prev = rateCeilSmooth.get(key) ?? peak;
      // Rise immediately on new peaks; decay very slowly so older points barely rescale.
      const next = peak >= prev ? peak : prev + (peak - prev) * 0.02;
      rateCeilSmooth.set(key, next);
      return Math.max(floor, next);
    }

    /**
     * Map rate samples to 0–100 activity.
     * Uses a fixed reference (refMbps) so historical shape does not squash/stretch
     * when a new spike raises the soft ceiling. Soft ceiling only lifts the ref
     * when sustained load exceeds it (rare), with very slow decay.
     */
    function ratesToActivity(key, rates, floor = 16, refMbps = null) {
      const fixed = refMbps != null ? refMbps : floor;
      const ceil = Math.max(fixed, softRateCeil(key, rates, fixed));
      return rates.map(r => clampPct(((Number(r) || 0) / ceil) * 100));
    }

    function lockPctAxis(chart, axisId = 'y') {
      const scale = chart.options?.scales?.[axisId];
      if (!scale) return;
      scale.min = 0;
      scale.max = 100;
      scale._pulseMax = 100;
    }

    function stableAxisMax(chart, axisId, dataMax, min = 8, cap = Infinity) {
      const scale = chart.options.scales[axisId];
      if (!scale) return;
      const target = Math.min(cap, Math.max(min, Math.ceil(dataMax * 1.12)));
      const prev = scale._pulseMax ?? target;
      let next;
      if (target > prev) {
        next = target; // expand immediately so spikes aren't clipped
      } else if (target < prev * 0.65) {
        // Regime change (disk toggled off / spike left the window) — snap down
        // so the plot doesn't stay stuck on an old 0–100 ceiling.
        next = prev + (target - prev) * 0.35;
      } else {
        next = prev + (target - prev) * 0.1;
      }
      if (next > cap) next = cap;
      scale._pulseMax = next;
      scale.max = next;
    }

    function setMeterWidth(el, pct) {
      if (!el) return;
      el.style.width = `${smoothPct(el, pct).toFixed(1)}%`;
    }

    function setMeterHeight(el, pct, min = 2) {
      if (!el) return;
      el.style.height = `${Math.max(min, smoothPct(el, pct)).toFixed(1)}%`;
    }

    /** Circular utilization ring (pathLength=100 → dasharray is percent). */
    function setRingPct(el, pct) {
      if (!el) return;
      const p = Math.max(0, Math.min(100, smoothPct(el, pct)));
      el.setAttribute('stroke-dasharray', `${p.toFixed(1)} 100`);
    }
    let activeTab = sessionStorage.getItem('pulse-tab') || 'dashboard';
    // Deep-link: ?tab=guidance|fixes|dashboard|options (A/B + second-monitor bookmarks)
    try {
      const tabQ = new URLSearchParams(location.search).get('tab');
      if (tabQ === 'guidance' || tabQ === 'fixes') activeTab = 'fixes';
      else if (tabQ === 'dashboard' || tabQ === 'options') activeTab = tabQ;
    } catch (_) { /* ignore */ }

    function onDrillOpened(d) {
      const key = d?.dataset?.openKey || d?.id || '';
      requestAnimationFrame(() => {
        try {
          if (key === 'drill-charts' || d.id === 'drill-charts') {
            renderCharts();
            utilChart?.resize();
            bwChart?.resize();
            ioChart?.resize();
          } else if (key === 'drill-compute' || d.id === 'drill-compute') {
            if (lastLatest) renderCores(lastLatest.cpu?.per_core || []);
          } else if (key === 'drill-sensors' || d.id === 'drill-sensors') {
            if (lastLatest) renderSensorGroups(lastLatest.sensors || []);
          } else if (key === 'drill-bandwidth' || d.id === 'drill-bandwidth') {
            if (lastLatest) renderBandwidth(lastLatest);
          } else if (key === 'drill-league' || d.id === 'drill-league') {
            if (lastLatest) renderComparison(lastLatest.comparison, lastStatic?.memory || {}, lastStatic?.pulse_root);
          }
        } catch (_) { /* ignore */ }
      });
    }

    document.addEventListener('toggle', e => {
      const d = e.target;
      if (d.tagName !== 'DETAILS' || !d.dataset.openKey) return;
      if (d.open) {
        document.querySelectorAll('.drill-stack details.drill[open]').forEach(other => {
          if (other !== d) other.open = false;
        });
        openPanels.clear();
        openPanels.add(d.dataset.openKey);
        onDrillOpened(d);
      } else {
        openPanels.delete(d.dataset.openKey);
      }
    }, true);

    function captureOpenPanels() {
      document.querySelectorAll('details[data-open-key]').forEach(d => {
        const k = d.dataset.openKey;
        if (d.open) openPanels.add(k);
        else openPanels.delete(k);
      });
    }

    function restoreOpenPanels() {
      const keep = [...openPanels].at(-1);
      document.querySelectorAll('details[data-open-key]').forEach(d => {
        d.open = !!(keep && d.dataset.openKey === keep);
      });
    }

    function capturePanelState() {
      captureOpenPanels();
      panelScrollState = {};
      document.querySelectorAll('details[data-open-key]').forEach(d => {
        if (!d.open) return;
        const k = d.dataset.openKey;
        const steps = d.querySelector('.rec-steps');
        if (steps) panelScrollState[`${k}:steps`] = steps.scrollTop;
      });
      document.querySelectorAll('.warn-list.stable-scroll, .diag-list.stable-scroll').forEach(el => {
        if (el.id) panelScrollState[`scroll:${el.id}`] = el.scrollTop;
      });
    }

    function restorePanelState() {
      restoreOpenPanels();
      document.querySelectorAll('details[data-open-key]').forEach(d => {
        if (!d.open) return;
        const k = d.dataset.openKey;
        const steps = d.querySelector('.rec-steps');
        if (steps && panelScrollState[`${k}:steps`] != null) steps.scrollTop = panelScrollState[`${k}:steps`];
      });
      document.querySelectorAll('.warn-list.stable-scroll, .diag-list.stable-scroll').forEach(el => {
        if (el.id && panelScrollState[`scroll:${el.id}`] != null) el.scrollTop = panelScrollState[`scroll:${el.id}`];
      });
    }

    function bindScrollContainment() {
      document.addEventListener('wheel', e => {
        if (e.ctrlKey) return;
        const el = e.target.closest('.rec-steps, .diag-pre, .warn-list, .diag-list, .stable-scroll');
        if (el) {
          const max = el.scrollHeight - el.clientHeight;
          if (max <= 0) return;
          const top = el.scrollTop;
          const dy = e.deltaY;
          const atTop = top <= 0;
          const atBottom = top >= max - 1;
          if ((dy < 0 && atTop) || (dy > 0 && atBottom)) e.preventDefault();
          e.stopPropagation();
          return;
        }
        // Live lab meters use size containment / overflow clip, which Chromium
        // treats as a scrollport that never moves — wheel never reaches the page.
        if (!e.target.closest?.('.rig-col-vitals')) return;
        const mul = e.deltaMode === 1 ? 16 : (e.deltaMode === 2 ? window.innerHeight : 1);
        e.preventDefault();
        window.scrollBy(e.deltaX * mul, e.deltaY * mul);
      }, { passive: false, capture: true });
    }

    function stablePillsHtml(items) {
      return items
        .filter(([, , n]) => n > 0)
        .map(([lv, lbl, n]) => `<span class="insight-pill ${lv}">${hwIcon(lv, 'hw-pill-glyph')}${n} ${lbl}</span>`)
        .join('');
    }

    /* Guidance diffing: layout key ignores condition_live / last_seen so the index
       does not rebuild every poll. patchGuidanceLiveState() updates dots in place. */
    function hintsLayoutKey(hints) {
      return JSON.stringify((hints || []).map(h => [
        h.insight_id, h.level, h.title, h.text,
        h.games_affected, h.multi_game, h.bucket,
        !!h.requires_root,
        (h.actions || []).map(a => [a.label, a.cmd, a.note, a.kind || '']),
      ]));
    }

    function hintsStructKey(hints) {
      return hintsLayoutKey(hints);
    }

    function patchGuidanceLiveState(hints) {
      const byId = new Map((hints || []).map(h => [h.insight_id, h]));
      document.querySelectorAll('.guidance-idx-row[data-guidance-pick]').forEach(row => {
        const id = row.dataset.guidancePick;
        if (!id || id.startsWith('diag:')) return;
        const h = byId.get(id);
        if (!h) return;
        const resolved = hintUserStatus(h) === 'resolved';
        const live = h.condition_live && !resolved;
        row.classList.toggle('resolved', resolved);
        row.classList.toggle('is-live', live);
        // Tags replaced the old meta dots — keep LIVE / FIXED in sync without full rebuild
        const tags = row.querySelector('.guidance-idx-tags');
        if (tags) {
          let liveTag = tags.querySelector('.guidance-tag.live');
          let fixedTag = tags.querySelector('.guidance-tag.fixed');
          if (live && !liveTag) {
            tags.insertAdjacentHTML('beforeend', '<span class="guidance-tag live">Live</span>');
          } else if (!live && liveTag) {
            liveTag.remove();
          }
          if (resolved && !fixedTag) {
            tags.insertAdjacentHTML('beforeend', '<span class="guidance-tag fixed">Fixed</span>');
          } else if (!resolved && fixedTag) {
            fixedTag.remove();
          }
        }
      });
      document.querySelectorAll('#guidanceDetailCard article.rec-card[data-iid]').forEach(card => {
        const h = byId.get(card.dataset.iid);
        if (!h) return;
        const badge = card.querySelector('.rec-status');
        if (!badge) return;
        const resolved = hintUserStatus(h) === 'resolved';
        if (resolved) {
          badge.className = 'rec-status resolved';
          badge.textContent = 'Fixed';
        } else if (h.condition_live) {
          badge.className = 'rec-status live';
          badge.textContent = 'Live now';
        } else {
          badge.className = 'rec-status outstanding';
          badge.textContent = 'Outstanding';
        }
      });
    }

    function updateRecMetas(hints) {
      (hints || []).forEach(h => {
        const sid = h.insight_id || 'insight';
        const when = h.last_seen ? `Last seen ${fmtAgo(h.last_seen)}` : '';
        document.querySelectorAll(`article.rec-card[data-iid="${CSS.escape(sid)}"]`).forEach(card => {
          let meta = card.querySelector('[data-rec-meta]');
          if (!when) {
            if (meta) meta.remove();
            return;
          }
          if (!meta) {
            meta = document.createElement('p');
            meta.className = 'rec-meta';
            meta.dataset.recMeta = '1';
            const anchor = card.querySelector('.rec-body');
            anchor?.insertAdjacentElement('afterend', meta);
          }
          meta.textContent = when;
        });
      });
    }

    function openDrill(id) {
      const el = document.getElementById(id);
      if (!el) return false;
      if (el.tagName === 'DETAILS') {
        document.querySelectorAll('.drill-stack details.drill[open]').forEach(d => {
          if (d !== el) d.open = false;
        });
        el.open = true;
        if (el.dataset.openKey) {
          openPanels.clear();
          openPanels.add(el.dataset.openKey);
        }
        onDrillOpened(el);
        return true;
      }
      return false;
    }

    function syncHeaderScrollOffset() {
      const h = document.querySelector('header');
      const pad = 12;
      const px = (h?.offsetHeight ?? 104) + pad;
      document.documentElement.style.setProperty('--header-scroll-offset', `${px}px`);
      return px;
    }
    syncHeaderScrollOffset();
    window.addEventListener('resize', syncHeaderScrollOffset);

    function scrollToElement(el, smooth = true) {
      if (!el) return;
      const pad = syncHeaderScrollOffset();
      const top = el.getBoundingClientRect().top + window.scrollY - pad;
      window.scrollTo({ top: Math.max(0, top), behavior: smooth ? 'smooth' : 'auto' });
    }

    const DIAG_AUTO_REFRESH_MS = 90000;
    let diagAutoRefreshId = null;

    function syncDiagAutoRefresh() {
      if (diagAutoRefreshId) {
        clearInterval(diagAutoRefreshId);
        diagAutoRefreshId = null;
      }
      if (activeTab !== 'fixes') return;
      fetchDiagnostics(false);
      diagAutoRefreshId = setInterval(() => fetchDiagnostics(false), DIAG_AUTO_REFRESH_MS);
    }

    function setTab(name, scrollTo, scrollTop = false) {
      activeTab = name;
      sessionStorage.setItem('pulse-tab', name);
      document.getElementById('pageDashboard').classList.toggle('active', name === 'dashboard');
      document.getElementById('pageFixes').classList.toggle('active', name === 'fixes');
      document.getElementById('pageOptions')?.classList.toggle('active', name === 'options');
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
      syncDiagAutoRefresh();
      if (name === 'options') {
        try { fetchStore(); } catch (_) { /* ignore */ }
        try {
          fetchRuleCatalog(document.getElementById('ruleCatalogSearch')?.value?.trim());
        } catch (_) { /* ignore */ }
        try { fillHwScaleHints(); } catch (_) { /* ignore */ }
      }
      if (name === 'fixes') {
        try {
          renderFixes(lastLatest?.tuning || lastWarningsHints);
        } catch (_) { /* ignore */ }
      }
      if (name === 'dashboard' && lastLatest) {
        requestAnimationFrame(() => {
          try {
            renderVisualDashboard(lastLatest, lastComparison);
            // Page was display:none — resize the visible Live lab chart, not only Snapshot.
            if (vizFocus === 'index') {
              indexChart?.resize();
              renderIndexChart();
            } else if (vizFocus === 'stutter') {
              stutterChart?.resize();
              renderStutterChart();
            } else {
              sparkChart?.resize();
              renderSparkChart();
            }
          } catch (_) { /* ignore */ }
        });
      }
      if (scrollTo) {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            if (scrollTo.startsWith('insight-')) {
              selectGuidanceHint(scrollTo.slice(8), { scroll: true });
              scrollToElement(document.getElementById('guidanceDetail'));
            } else {
              scrollToElement(document.getElementById(scrollTo));
            }
          });
        });
      } else if (scrollTop) {
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }
    }

    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.onclick = () => setTab(btn.dataset.tab, null, true);
    });
    document.getElementById('warnMoreFixesBtn')?.addEventListener('click', () => {
      setTab('fixes', 'insightsSection');
    });
    document.querySelectorAll('.sum-cell[data-drill], .sum-game-main[data-drill], .sum-game-index[data-drill]').forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        jumpTo(btn.dataset.drill);
      };
    });
    // Pulse Index tab is the analysis view; full comparison table stays in drill-league
    setTab(activeTab);

    function renderBacklog(_items) {
      /* Backlog is dev-only — not shown in the dashboard UI. */
    }

    const DRILL_IDS = new Set([
      'warningsSection',
      'drill-sensors', 'drill-charts', 'drill-bandwidth', 'drill-compute',
      'drill-league', 'drill-game', 'drill-storage',
    ]);

    const DIAG_CAT_LABEL = {
      boot: 'Boot', steam: 'Steam', game: 'Game', libraries: 'Libraries',
      driver: 'Driver', updates: 'Updates', storage: 'Storage', system: 'System',
    };

    let diagCache = null;
    let lastDiagKey = '';
    let lastGuidanceScanFindings = [];
    let lastDiagPrimary = null;
    let diagPollId = null;
    let diagHasScanned = false;

    function stopDiagPoll() {
      if (diagPollId) {
        clearInterval(diagPollId);
        diagPollId = null;
      }
    }

    function startDiagPoll() {
      if (diagPollId) return;
      // Taste-test: poll job status without re-forcing (no scan storms)
      diagPollId = setInterval(() => fetchDiagnostics(false), 900);
    }

    async function fetchDiagnostics(force = false) {
      const btn = document.getElementById('diagRefresh');
      if (force && btn) {
        btn.disabled = true;
        btn.textContent = 'Scanning…';
      }
      // keep label consistent (was flipping to bare "Scan")
      try {
        const url = force ? '/api/diagnostics?force=1' : '/api/diagnostics';
        const d = await (await fetch(url)).json();
        const scan = d.scan_findings || d.findings || [];
        const running = !!(d.job?.running || d.pending);
        const key = JSON.stringify([
          d.counts, d.scanned_at, running,
          (d.primary && d.primary.id) || null,
          scan.map(f => [f.id, f.severity, f.fix || '']),
        ]);
        if (force || key !== lastDiagKey) {
          lastDiagKey = key;
          diagCache = d;
          renderDiagnostics(d);
        } else if (btn) {
          btn.disabled = running;
          btn.textContent = running ? 'Scanning…' : 'Scan system';
        }
        if (running) startDiagPoll();
        else {
          stopDiagPoll();
          if (btn) {
            btn.disabled = false;
            btn.textContent = 'Scan system';
          }
        }
        return d;
      } catch {
        stopDiagPoll();
        const metaEl = document.getElementById('diagMeta');
        if (metaEl) {
          metaEl.textContent = 'Scan failed';
          metaEl.classList.remove('is-scanning');
        }
        if (btn) {
          btn.disabled = false;
          btn.textContent = 'Scan system';
        }
      }
      return null;
    }

    function sortScanFindings(scan) {
      return [...scan].sort((a, b) => {
        const rank = { hot: 0, warn: 1, info: 2, ok: 3 };
        const sev = (rank[a.severity] ?? 9) - (rank[b.severity] ?? 9);
        if (sev) return sev;
        return (a.title || '').localeCompare(b.title || '');
      });
    }

    function renderDiagnostics(d) {
      if (!d) return;
      const scan = (d.scan_findings || d.findings || []).filter(f => f.id !== 'all-clear');
      const scanCounts = { hot: 0, warn: 0, info: 0, ok: 0 };
      scan.forEach(f => { if (scanCounts[f.severity] !== undefined) scanCounts[f.severity]++; });
      const flagged = (scanCounts.hot || 0) + (scanCounts.warn || 0);
      const running = !!(d.job?.running || d.pending);
      if (d.scanned_at) diagHasScanned = true;
      const metaEl = document.getElementById('diagMeta');
      if (metaEl) {
        metaEl.classList.toggle('is-scanning', running);
        if (running && !d.scanned_at) {
          metaEl.textContent = 'Scanning…';
        } else if (running) {
          const when = d.scanned_at
            ? new Date(d.scanned_at * 1000).toLocaleTimeString()
            : '';
          metaEl.textContent = when ? `Rescanning · last ${when}` : 'Scanning…';
        } else if (d.job?.error) {
          metaEl.textContent = 'Scan error';
        } else if (!d.scanned_at) {
          metaEl.textContent = 'Optional deep check';
        } else {
          const when = new Date(d.scanned_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
          if (flagged) metaEl.textContent = `${flagged} flagged · ${when}`;
          else if (scan.length) metaEl.textContent = `${scan.length} notes · ${when}`;
          else metaEl.textContent = `Clean · ${when}`;
        }
      }
      const btn = document.getElementById('diagRefresh');
      if (btn) {
        btn.disabled = running;
        btn.textContent = running ? 'Scanning…' : 'Scan system';
      }
      // Keep Scan chip visible after first result so quiet machines aren't lost
      guidanceSectionCounts.scan = flagged || scan.length || (diagHasScanned ? 0 : 0);
      // Force chip visibility via special count: 0 still shows if we've scanned
      guidanceSectionCounts.scan_always = diagHasScanned || running || scan.length > 0;
      guidanceSectionCounts.scan_hot = (scanCounts.hot || 0) > 0;
      lastGuidanceScanFindings = sortScanFindings(scan);
      lastDiagPrimary = d.primary && d.primary.id !== 'all-clear' ? d.primary : null;
      // Prefer primary from scan_findings (same quality filter as UI list)
      if (lastDiagPrimary && !scan.some(f => f.id === lastDiagPrimary.id)) {
        lastDiagPrimary = scan[0] || null;
      } else if (!lastDiagPrimary && scan[0]) {
        lastDiagPrimary = scan[0];
      }
      renderGuidanceHero(lastGuidanceSummaryHints);
      renderGuidanceFilters();
      if (lastGuidanceIndexGroups.length || lastGuidanceFixedHints.length || lastGuidanceScanFindings.length || diagHasScanned) {
        renderGuidanceIndex(lastGuidanceIndexGroups, lastGuidanceFixedHints, lastSelectedGuidanceId);
        selectGuidanceHint(lastSelectedGuidanceId, { scroll: false });
      }
    }

    document.getElementById('diagRefresh')?.addEventListener('click', () => fetchDiagnostics(true));

    function openGuidanceScan() {
      setTab('fixes', 'guidanceIndex');
      guidanceIndexFilter = 'scan';
      renderGuidanceFilters();
      renderGuidanceIndex(lastGuidanceIndexGroups, lastGuidanceFixedHints, lastSelectedGuidanceId);
      const first = lastDiagPrimary || lastGuidanceScanFindings[0];
      if (first) selectGuidanceHint(`diag:${first.id}`, { scroll: true });
    }

    function openGuidanceDataTools() {
      const tools = document.getElementById('guidanceTools');
      if (tools) tools.open = true;
      setTab('fixes', 'guidanceTools');
    }
    fetchDiagnostics();

    function jumpTo(id) {
      if (id === 'drill-admin' || id === 'guidanceTools' || id === 'toolsList') {
        openGuidanceDataTools();
        return;
      }
      if (id === 'drill-troubleshoot') {
        openGuidanceScan();
        return;
      }
      if (id === 'insightsSection' || id === 'guidanceSection' || id === 'guidanceHero') {
        setTab('fixes', id === 'guidanceSection' ? 'insightsSection' : id);
        return;
      }
      if (activeTab !== 'dashboard') setTab('dashboard');
      // Game hero only occupies the main screen while a title is live
      if (id === 'viz-game' || id === 'gameVizBlock' || id === 'gamePerformanceHero') {
        const hero = document.getElementById('gamePerformanceHero');
        const live = !!(hero && !hero.classList.contains('is-minimized'));
        requestAnimationFrame(() => {
          if (live) {
            scrollToElement(hero);
            try { gamePerfChart?.resize(); gamePerfSessionsChart?.resize(); } catch (_) { /* */ }
          } else {
            openDrill('drill-game');
            scrollToElement(document.getElementById('drill-game'));
          }
        });
        return;
      }
      if (id === 'viz-index' || id === 'pulseIndexBlock') {
        requestAnimationFrame(() => {
          setVizFocus('index');
          scrollToElement(document.getElementById('vizPanel'));
        });
        return;
      }
      if (id === 'viz-stutter' || id === 'stutterBlock') {
        requestAnimationFrame(() => {
          setVizFocus('stutter');
          scrollToElement(document.getElementById('vizPanel'));
        });
        return;
      }
      if (id === 'viz-rig' || id === 'rigSnapshotBlock') {
        requestAnimationFrame(() => {
          setVizFocus('rig');
          scrollToElement(document.getElementById('vizPanel'));
        });
        return;
      }
      requestAnimationFrame(() => {
        if (DRILL_IDS.has(id)) openDrill(id);
        scrollToElement(document.getElementById(id));
      });
    }

    function renderTools(tools) {
      const data = tools?.data_sources || tools?.recommended?.filter(t => t.role !== 'helper') || [];
      const helpers = tools?.helpers || tools?.recommended?.filter(t => t.role === 'helper') || [];
      const el = document.getElementById('toolsList');
      if (!el) return;
      const rows = [];
      const renderRow = (t) => {
        const installed = !!t.installed;
        const feeding = !!t.feeding;
        let badge = 'missing';
        let badgeCls = 'high';
        if (installed && feeding) { badge = 'feeding'; badgeCls = 'done'; }
        else if (installed && t.role === 'helper') { badge = 'ready'; badgeCls = 'done'; }
        else if (installed) { badge = 'idle'; badgeCls = 'med'; }
        const setup = t.setup === 'enable-nvme-smart'
          ? `<div class="sub" style="margin-top:.35rem">Needs device access — from Guidance run:
              <code style="display:block;margin-top:.25rem;font-size:.85rem;color:var(--blue)">sudo usermod -aG disk $USER &amp;&amp; echo 'KERNEL=="nvme[0-9]*", GROUP="disk", MODE="0660"' | sudo tee /etc/udev/rules.d/60-nvme-smart-pulse.rules</code>
              Then log out/in and restart Pulse.</div>`
          : t.setup === 'enable-cpu-rapl'
          ? `<div class="sub" style="margin-top:.35rem">RAPL <code>energy_uj</code> is root-only — CPU watt dial stays n/a until:
              <code style="display:block;margin-top:.25rem;font-size:.85rem;color:var(--blue)">sudo cp deploy/99-rapl-readable.rules /etc/udev/rules.d/ &amp;&amp; sudo udevadm control --reload &amp;&amp; sudo udevadm trigger -s powercap</code>
              Then restart Pulse (from the Pulse install dir). No extra apt package; zenpower is not in Pop repos.</div>`
          : '';
        // Title = package people search for in apt; bin is what Pulse runs.
        const pkg = t.pkg || t.bin || t.id || 'tool';
        const bin = t.bin || pkg;
        const title = pkg;
        const binNote = bin !== pkg
          ? `<span style="color:var(--muted)"> · provides <code>${esc(bin)}</code></span>`
          : '';
        return `<div class="bl-item">
          <span class="bl-pri ${badgeCls}">${hwIcon(feeding || (installed && t.role === 'helper') ? 'ok' : 'warn', 'hw-pill-glyph')}${badge}</span>
          <div>
            <strong>${esc(title)}</strong>${binNote}
            <div class="sub" style="margin:.15rem 0 0">${esc(t.note || '')}</div>
            ${t.detail ? `<div class="sub" style="margin-top:.2rem;color:var(--text-secondary)">${esc(t.detail)}</div>` : ''}
            ${!installed ? `<code style="display:block;margin-top:.35rem;font-size:.9rem;color:var(--blue)">sudo apt install ${esc(pkg)}</code>` : ''}
            ${setup}
          </div>
        </div>`;
      };
      if (data.length) {
        rows.push('<div class="sub" style="margin:.2rem 0 .45rem;font-weight:600;letter-spacing:.02em">DATA SOURCES</div>');
        data.forEach(t => rows.push(renderRow(t)));
      }
      if (helpers.length) {
        rows.push('<div class="sub" style="margin:.85rem 0 .45rem;font-weight:600;letter-spacing:.02em">HELPERS (not live metrics)</div>');
        helpers.forEach(t => rows.push(renderRow(t)));
      }
      if (!rows.length) {
        el.innerHTML = '<div class="sub">No tool list configured</div>';
        return;
      }
      el.innerHTML = rows.join('');
      const toolsSum = document.getElementById('guidanceToolsSum');
      const all = [...data, ...helpers];
      const feeding = data.filter(t => t.feeding).length;
      const installed = all.filter(t => t.installed).length;
      if (toolsSum) {
        toolsSum.textContent = `${feeding}/${data.length} feeding · ${installed}/${all.length} installed`;
      }
    }

    const GAME_RATING_TIERS = ['excellent', 'good', 'fair', 'poor', 'bad'];

    function gameSummaryState(gp, gt, st) {
      const gid = gt?.running ? gt.game_id : (gp?.last_session?.game_id || lastActiveGameId);
      const runName = gt?.running
        ? (gt.primary_name || gt.game_name || (gid ? gameLabel(gid) : 'Game'))
        : null;

      if (gp?.active && gp.recording) {
        const tier = gp.rating_tier || 'fair';
        const hitches = gp.hitch_events ?? 0;
        const hitchMs = gp.hitch_ms_1pct ?? '—';
        const sess = st?.session || {};
        const hitchCls = (gp.hitch_ms_1pct || 0) >= 50 ? 'poor' : '';
        const gameName = gp.game_name || runName || 'Game';
        const gameId = gp.game_id || gt?.game_id;
        const mh = sessionHasMangoHud(gp);
        const stats = [
          { k: 'Smooth', v: `${gp.smoothness_avg ?? '—'}%`, s: 'session avg', cls: tier },
          { k: '1% low', v: `${hitchMs}ms`, s: mh ? 'MangoHud measured' : 'worst hitch est.', cls: hitchCls },
          { k: 'Hitches', v: hitches, s: `${sess.hitch_rate_per_min ?? 0}/min`, cls: hitches >= 5 ? 'fair' : '' },
          { k: 'CPU', v: `${gp.game_cpu_avg ?? '—'}%`, s: `now ${gt?.cpu_pct ?? '—'}%` },
          { k: 'GPU', v: `${gp.gpu_busy_avg ?? '—'}%`, s: 'session avg' },
        ];
        if (mh && gp.fps_avg != null) {
          stats.splice(1, 0, { k: 'FPS', v: `${gp.fps_avg}`, s: gp.fps_1pct != null ? `1% ${gp.fps_1pct}` : 'MangoHud', cls: 'ok' });
        }
        return {
          tall: true,
          live: true,
          tier,
          gameId,
          label: gameLabel(gameId) || gameName,
          sectionTitle: mh
            ? `Live session · ${gameName} · MangoHud`
            : `Live session · ${gameName}`,
          explainer: mh
            ? 'Session smoothness + MangoHud FPS/frametime — Pulse rating'
            : 'Session smoothness score · Pulse rating — not a Steam score',
          val: `${gp.rating ?? '—'}/100`,
          context: mh
            ? `Live · ${fmtDuration(gp.duration_sec)} · MangoHud`
            : `Live · ${fmtDuration(gp.duration_sec)}`,
          meter: gp.rating ?? 0,
          stats,
          drillRollup: mh && gp.fps_avg != null
            ? `${gameName} · ${gp.rating ?? '—'}/100 · ${gp.fps_avg} FPS`
            : `${gameName} · ${gp.rating ?? '—'}/100 · ${gp.smoothness_avg ?? '—'}% smooth`,
        };
      }
      if (gp?.active && !gp.recording) {
        const remain = Math.ceil(gp.load_remaining_sec ?? 0);
        const gameName = gp.game_name || runName || 'Game';
        const gameId = gp.game_id || gt?.game_id;
        return {
          tall: true,
          live: true,
          tier: null,
          gameId,
          label: gameLabel(gameId) || gameName,
          sectionTitle: `Starting · ${gameName}`,
          explainer: 'Recording starts after the load grace period',
          val: 'Loading',
          context: `Loading · ${remain}s until stats`,
          meter: Math.max(0, 100 - Math.min(remain, 45) * (100 / 45)),
          stats: [
            { k: 'Process', v: `${gt?.cpu_pct ?? '—'}%`, s: 'live CPU', cls: 'ok' },
            { k: 'RAM', v: `${((gt?.rss_mb || 0) / 1024).toFixed(1)} GB`, s: 'game process' },
            { k: 'Grace', v: `${remain}s`, s: 'until recording' },
          ],
          drillRollup: `${gameName} · loading ${remain}s`,
        };
      }
      const last = resolveLastSession(gp, gid);
      if (last?.rating != null) {
        const tier = last.rating_tier || 'fair';
        const gameName = last.game_name || gameLabel(last.game_id);
        const mh = sessionHasMangoHud(last);
        const stats = [
          { k: 'Smooth', v: `${last.smoothness_avg ?? '—'}%`, s: fmtDuration(last.duration_sec), cls: tier },
          { k: '1% low', v: `${last.hitch_ms_1pct ?? '—'}ms`, s: hitchStatSub(last) },
          { k: 'CPU', v: `${last.game_cpu_avg ?? '—'}%`, s: 'session avg' },
          { k: 'GPU', v: `${last.gpu_busy_avg ?? '—'}%`, s: 'session avg' },
        ];
        if (mh && last.fps_avg != null) {
          stats.splice(1, 0, { k: 'FPS', v: `${last.fps_avg}`, s: last.fps_1pct != null ? `1% ${last.fps_1pct}` : 'MangoHud', cls: 'ok' });
        }
        return {
          tall: true,
          live: false,
          tier,
          gameId: last.game_id,
          label: gameLabel(last.game_id) || gameName,
          sectionTitle: mh
            ? `Last played · ${gameName} · MangoHud`
            : `Last played · ${gameName}`,
          explainer: mh
            ? 'Session smoothness + MangoHud FPS/frametime — Pulse rating'
            : 'Session smoothness score · Pulse rating — not a Steam score',
          val: `${last.rating}/100`,
          context: mh
            ? `Last session · ${fmtStoreSpan(last.ended_ts)} · MangoHud`
            : `Last session · ${fmtStoreSpan(last.ended_ts)}`,
          meter: last.rating,
          stats,
          drillRollup: mh && last.fps_avg != null
            ? `${gameName} · last ${last.rating}/100 · ${last.fps_avg} FPS`
            : `${gameName} · last ${last.rating}/100 · ${last.smoothness_avg ?? '—'}% smooth`,
        };
      }
      if (gt?.running) {
        const lingering = gt.lingering;
        const lingerSec = gt.linger_remaining_sec;
        const gameName = runName || gameLabel(gt.game_id) || 'Game';
        return {
          tall: true,
          live: true,
          tier: null,
          gameId: gt.game_id,
          label: gameLabel(gt.game_id) || gameName,
          sectionTitle: lingering ? `Starting · ${gameName}` : `Now playing · ${gameName}`,
          explainer: lingering
            ? 'Process paused during load — card stays up until the game returns'
            : 'Live process CPU — session rating building',
          val: lingering ? 'Loading' : `${gt.cpu_pct}%`,
          context: lingering
            ? `Loading · ${Math.ceil(lingerSec ?? 0)}s hold`
            : 'Starting session',
          meter: lingering
            ? Math.max(0, 100 - Math.min(lingerSec ?? 10, 10) * 10)
            : (gt.cpu_pct ?? 0),
          stats: [
            { k: 'Process', v: lingering ? '—' : `${gt.cpu_pct ?? '—'}%`, s: lingering ? 'waiting for PID' : 'live CPU', cls: 'ok' },
            { k: 'RAM', v: lingering ? '—' : `${((gt.rss_mb || 0) / 1024).toFixed(1)} GB`, s: 'game process' },
          ],
          drillRollup: lingering
            ? `${gameName} · loading`
            : `${gameName} · ${gt.cpu_pct}% CPU`,
        };
      }
      return {
        tall: false,
        live: false,
        tier: null,
        gameId: null,
        label: 'Game',
        sectionTitle: 'Game performance',
        explainer: 'Waiting for first session… Launch a Steam game to start tracking',
        val: '—',
        context: 'Launch a Steam game',
        meter: 0,
        stats: [],
        drillRollup: 'Awaiting Steam game',
      };
    }

    function renderGameSummaryStats(el, stats) {
      if (!el) return;
      let visible = stats || [];
      const maxStats = window.innerWidth < 900 ? 4 : (window.innerWidth < 520 ? 3 : 5);
      if (visible.length > maxStats) {
        const hidden = visible.length - (maxStats - 1);
        visible = visible.slice(0, maxStats - 1).concat([
          { k: 'More', v: `+${hidden}`, s: 'session stats', cls: '' },
        ]);
      }
      const key = JSON.stringify(visible);
      if (el.dataset.statsKey === key) return;
      el.dataset.statsKey = key;
      if (!visible.length) {
        el.innerHTML = '';
        el.hidden = true;
        el.style.removeProperty('--game-stat-cols');
        return;
      }
      el.hidden = false;
      el.style.setProperty('--game-stat-cols', String(visible.length));
      el.innerHTML = visible.map(s => `
        <div class="sum-game-stat${s.cls ? ` ${esc(s.cls)}` : ''}">
          <span class="k">${esc(s.k)}</span>
          <span class="v">${esc(String(s.v))}</span>
          ${s.s ? `<span class="s">${esc(s.s)}</span>` : ''}
        </div>`).join('');
    }

    function gameAppId(id, catalog) {
      const norm = normalizeGameId(id);
      if (!norm) return null;
      if (/^\d+$/.test(String(norm))) return String(norm);
      const cat = catalog?.[norm] || catalog?.[id];
      return cat?.appid ? String(cat.appid) : null;
    }

    const STEAM_ART_CDN = 'https://shared.fastly.steamstatic.com/store_item_assets/steam/apps';
    const STEAM_ART_LEGACY_CDN = 'https://cdn.cloudflare.steamstatic.com/steam/apps';
    const gameArtResolved = new Map();
    let gameArtProbeAppid = null;

    function steamArtCandidates(appid, catalog) {
      const cat = catalog?.[appid];
      if (cat?.art_urls?.length) return cat.art_urls;
      return [
        `${STEAM_ART_CDN}/${appid}/library_hero.jpg`,
        `${STEAM_ART_CDN}/${appid}/header.jpg`,
        `${STEAM_ART_CDN}/${appid}/capsule_616x353.jpg`,
        `${STEAM_ART_LEGACY_CDN}/${appid}/header.jpg`,
      ];
    }

    function setGameSummaryArtVisible(wrap, show) {
      if (!wrap) return;
      wrap.hidden = !show;
      wrap.classList.toggle('is-loaded', show);
    }

    function bindGameArtImg(img) {
      if (img.dataset.artBound === '1') return;
      img.dataset.artBound = '1';
      img.referrerPolicy = 'no-referrer';
      img.decoding = 'async';
    }

    function showGameArtUrl(wrap, img, appid, url) {
      const reveal = () => setGameSummaryArtVisible(wrap, true);
      img.onload = reveal;
      img.onerror = () => {
        gameArtResolved.delete(appid);
        gameArtProbeAppid = null;
        applyGameSummaryArt(appid, img.alt.replace(/ artwork$/, ''));
      };
      if (img.getAttribute('src') !== url) img.src = url;
      else if (img.complete && img.naturalWidth > 0) reveal();
      else setGameSummaryArtVisible(wrap, false);
    }

    function applyGameSummaryArt(gameId, label) {
      const wrap = document.getElementById('sumGameArt');
      const img = document.getElementById('sumGameArtImg');
      if (!wrap || !img) return;
      bindGameArtImg(img);

      const catalog = lastStatic?.games_catalog || {};
      const appid = gameAppId(gameId, catalog);
      img.alt = label ? `${label} artwork` : 'Game artwork';

      if (!appid) {
        gameArtProbeAppid = null;
        setGameSummaryArtVisible(wrap, false);
        img.removeAttribute('src');
        return;
      }

      if (gameArtResolved.has(appid)) {
        const resolved = gameArtResolved.get(appid);
        if (!resolved) {
          setGameSummaryArtVisible(wrap, false);
          img.removeAttribute('src');
          return;
        }
        if (img.getAttribute('src') === resolved && img.complete && img.naturalWidth > 0) {
          setGameSummaryArtVisible(wrap, true);
          return;
        }
        showGameArtUrl(wrap, img, appid, resolved);
        return;
      }

      if (gameArtProbeAppid === appid) return;

      gameArtProbeAppid = appid;
      setGameSummaryArtVisible(wrap, false);
      const candidates = steamArtCandidates(appid, catalog);
      let idx = 0;

      const tryNext = () => {
        if (gameArtProbeAppid !== appid) return;
        if (idx >= candidates.length) {
          gameArtResolved.set(appid, null);
          gameArtProbeAppid = null;
          setGameSummaryArtVisible(wrap, false);
          img.removeAttribute('src');
          return;
        }
        const url = candidates[idx++];
        img.onload = () => {
          if (gameArtProbeAppid !== appid) return;
          gameArtResolved.set(appid, url);
          gameArtProbeAppid = null;
          setGameSummaryArtVisible(wrap, true);
        };
        img.onerror = () => {
          if (gameArtProbeAppid !== appid) return;
          tryNext();
        };
        img.src = url;
      };
      tryNext();
    }

    function setRatingTierBadge(el, tier) {
      if (!el) return;
      const key = tier || '';
      if (el.dataset.tierKey === key) return;
      el.dataset.tierKey = key;
      if (!tier) {
        el.innerHTML = '';
        return;
      }
      const label = RATING_TIER_LABEL[tier] || tier;
      el.innerHTML = `<span class="rating-tier-pill ${esc(tier)}">${esc(label)}</span>`;
    }

    function renderGameSummaryCell(gp, gt, st) {
      const gs = gameSummaryState(gp, gt, st);
      const gameCell = document.getElementById('sumGameCell');
      const gameVal = document.getElementById('sumGameVal');
      if (!gameCell || !gameVal) return;

      document.querySelector('.sum-grid')?.classList.toggle('game-prominent', gs.tall);
      document.body.classList.toggle('game-prominent-active', gs.tall);
      gameCell.classList.toggle('tall', gs.tall);
      gameCell.classList.toggle('game-live', gs.live);
      gameCell.classList.toggle('sum-game-idle-pulse', !gs.tall);
      const banner = document.getElementById('sumGameBanner');
      const sectionTitle = document.getElementById('sumGameSectionTitle');
      const explainer = document.getElementById('sumGameExplainer');
      if (banner) {
        banner.hidden = !gs.tall;
        banner.classList.toggle('is-visible', gs.tall);
        banner.setAttribute('aria-hidden', gs.tall ? 'false' : 'true');
      }
      if (sectionTitle) sectionTitle.textContent = gs.sectionTitle || gs.label || 'Game performance';
      if (explainer) explainer.textContent = gs.explainer || '';
      const sumLbl = document.getElementById('sumGameLabel');
      if (sumLbl && gs.label) sumLbl.textContent = gs.tall ? '' : gs.label;
      GAME_RATING_TIERS.forEach(t => gameCell.classList.remove(`tier-${t}`));
      if (gs.tier) gameCell.classList.add(`tier-${gs.tier}`);

      gameVal.textContent = gs.val;
      gameVal.className = `sum-value${gs.tier ? ` ${gs.tier}` : ''}`;
      const ctxEl = document.getElementById('sumGameContext');
      if (ctxEl) ctxEl.textContent = gs.context || '';
      const subEl = document.getElementById('sumGameSub');
      if (subEl) subEl.textContent = gs.tall ? '' : (gs.context || '');
      setMeterWidth(document.getElementById('sumGameMeter'), gs.meter);
      setRatingTierBadge(document.getElementById('sumGameBadge'), gs.tier);
      renderGameSummaryStats(document.getElementById('sumGameStats'), gs.stats);
      applyGameSummaryArt(gs.gameId, gs.label);
      document.getElementById('drillGameSum').textContent = gs.drillRollup;
    }

    function renderSummaryBar(l, hints, comparison) {
      const c = l.cpu || {}, m = l.memory || {}, g = l.gpu?.discrete || {}, bw = l.bandwidth || {};
      const gt = l.game_totals;
      const open = guidanceOpenCounts(hints);
      const active = guidanceOutstanding(hints).filter(h => !isInsightSuppressed(h.insight_id));
      const healthHints = anyHwFocus() ? active.filter(h => hintVisibleForFocus(h)) : active;
      const counts = { hot: open.hot, warn: open.warn, info: open.info };
      const focusTag = anyHwFocus() ? ` · ${hwFocusLabelText()} focus` : '';

      const healthCell = document.getElementById('sumHealthCell');
      // Same outstanding set as the Guidance hero (live cards + scan findings).
      let healthVal = 'Clear';
      let healthSub = anyHwFocus()
        ? `No open cards for ${hwFocusLabelText()}`
        : 'No open Guidance cards';
      let healthCls = 'ok';
      const totalOpen = open.total;
      if (counts.hot) {
        healthVal = counts.hot === 1 ? '1 critical' : `${counts.hot} critical`;
        healthSub = `${totalOpen} open${focusTag}`;
        healthCls = 'hot';
      } else if (counts.warn) {
        healthVal = counts.warn === 1 ? '1 warning' : `${counts.warn} warnings`;
        healthSub = `${totalOpen} open${focusTag}`;
        healthCls = 'warn';
      } else if (counts.info) {
        healthVal = counts.info === 1 ? '1 info' : `${counts.info} info`;
        healthSub = `${totalOpen} open${focusTag}`;
        healthCls = 'info';
      } else if (anyHwFocus() && active.length) {
        healthVal = 'Clear';
        healthSub = `No open cards for ${hwFocusLabelText()}`;
        healthCls = 'ok';
      }
      if (healthCell) {
        healthCell.classList.remove('hot', 'warn', 'info', 'ok');
        healthCell.classList.add('sum-cell', 'tall', healthCls);
      }
      const healthValEl = document.getElementById('sumHealthVal');
      const healthSubEl = document.getElementById('sumHealthSub');
      if (healthValEl) healthValEl.textContent = healthVal;
      if (healthSubEl) healthSubEl.textContent = healthSub;

      // Severity tiles — fill width of tall column (counts, not a fake score meter)
      const sevEl = document.getElementById('sumHealthSev');
      if (sevEl) {
        const chip = (lv, n, label) =>
          `<span class="health-sev ${lv}${n ? '' : ' zero'}"><span class="n">${n}</span><span class="lbl">${label}</span></span>`;
        sevEl.innerHTML = [
          chip('hot', counts.hot, 'crit'),
          chip('warn', counts.warn, 'warn'),
          chip('info', counts.info, 'info'),
        ].join('');
        sevEl.setAttribute('aria-hidden', 'false');
      }
      // Up to 3 open cards — uses vertical room in the tall cell
      const listEl = document.getElementById('sumHealthList');
      const clearEl = document.getElementById('sumHealthClear');
      if (listEl) {
        const order = { hot: 0, warn: 1, info: 2, ok: 3 };
        const tops = [...healthHints].sort((a, b) =>
          (order[a.level] ?? 9) - (order[b.level] ?? 9)
          || String(a.title || '').localeCompare(String(b.title || '')),
        ).slice(0, 3);
        listEl.innerHTML = tops.map(h => {
          const lv = ['hot', 'warn', 'info'].includes(h.level) ? h.level : 'info';
          return `<span class="health-item ${lv}"><span class="dot"></span><span class="t">${esc(h.title || h.insight_id || 'Card')}</span></span>`;
        }).join('');
      }
      if (clearEl) clearEl.hidden = totalOpen > 0;
      const leagueIdx = comparison ? smoothDisplayPct('session-index', comparison.session_index) : 0;

      const setChipBar = (id, pct) => {
        const bar = document.getElementById(id);
        if (!bar) return;
        const p = Math.max(0, Math.min(100, Number(pct) || 0));
        bar.style.width = `${p.toFixed(1)}%`;
      };

      const cpuPct = c.overall_pct ?? 0;
      setRingPct(document.getElementById('sumCpuRing'), cpuPct);
      setChipBar('sumCpuBar', cpuPct);
      document.getElementById('sumCpuVal').textContent =
        Number.isFinite(Number(cpuPct)) ? `${Math.round(Number(cpuPct))}%` : '—';
      const cpuTemp = document.getElementById('sumCpuTemp');
      if (cpuTemp) {
        cpuTemp.textContent = c.temps?.package != null ? `${Math.round(c.temps.package)}°C` : '—';
      }
      const cpuLoad = document.getElementById('sumCpuLoad');
      if (cpuLoad) {
        const l1 = c.load?.[0];
        cpuLoad.textContent = l1 != null ? `load ${Number(l1).toFixed(2)}` : 'load —';
      }

      const memPct = m.pct ?? 0;
      setRingPct(document.getElementById('sumMemRing'), memPct);
      setChipBar('sumMemBar', memPct);
      document.getElementById('sumMemVal').textContent =
        Number.isFinite(Number(memPct)) ? `${Math.round(Number(memPct))}%` : '—';
      const memUsed = document.getElementById('sumMemUsed');
      if (memUsed) {
        if (m.used_gb != null && m.total_gb != null) {
          const used = Number(m.used_gb);
          const total = Number(m.total_gb);
          const usedStr = Number.isFinite(used) ? used.toFixed(1) : String(m.used_gb);
          const totalStr = Number.isFinite(total)
            ? (Math.abs(total - Math.round(total)) < 0.05 ? String(Math.round(total)) : total.toFixed(1))
            : String(m.total_gb);
          const label = `${usedStr}/${totalStr} GB`;
          memUsed.textContent = label;
          memUsed.title = `${usedStr} / ${totalStr} GB used`;
        } else {
          memUsed.textContent = '—';
          memUsed.removeAttribute('title');
        }
      }
      const memSwap = document.getElementById('sumMemSwap');
      if (memSwap) {
        memSwap.textContent = m.swap_pct != null ? `swap ${Math.round(m.swap_pct)}%` : 'swap —';
      }

      const engines = Array.isArray(g.engines) ? g.engines : [];
      const engPct = (id, fallback) => {
        const hit = engines.find(e => e && e.id === id);
        if (hit && hit.pct != null && Number.isFinite(Number(hit.pct))) return Number(hit.pct);
        return fallback;
      };
      const gfxPct = engPct('gfx', g.busy_pct);
      const memBusPct = engPct('vram', g.mem_busy_pct);
      setRingPct(document.getElementById('sumGpuRing'), gfxPct ?? 0);
      setChipBar('sumGpuBar', gfxPct ?? 0);
      document.getElementById('sumGpuVal').textContent =
        gfxPct != null && Number.isFinite(Number(gfxPct))
          ? `${Math.round(Number(gfxPct))}%`
          : '—';
      const gpuTemp = document.getElementById('sumGpuTemp');
      if (gpuTemp) {
        gpuTemp.textContent = g.junction_c != null ? `${Math.round(g.junction_c)}°C` : '—';
      }
      const gpuPower = document.getElementById('sumGpuPower');
      if (gpuPower) {
        gpuPower.textContent = g.power_w != null ? `${Math.round(g.power_w)} W` : '— W';
      }
      const gpuMemBus = document.getElementById('sumGpuMemBus');
      if (gpuMemBus) {
        gpuMemBus.textContent =
          memBusPct != null && Number.isFinite(Number(memBusPct))
            ? `${Math.round(Number(memBusPct))}%`
            : '—';
      }

      // VRAM chip — gaming-critical headroom next to GPU busy
      const vramPctRaw = g.vram_pct != null
        ? Number(g.vram_pct)
        : (g.vram_used_mb != null && g.vram_total_mb
          ? (100 * Number(g.vram_used_mb) / Number(g.vram_total_mb))
          : null);
      const vramPct = vramPctRaw != null && Number.isFinite(vramPctRaw) ? vramPctRaw : 0;
      setChipBar('sumVramBar', vramPct);
      const vramVal = document.getElementById('sumVramVal');
      if (vramVal) {
        vramVal.textContent = vramPctRaw != null && Number.isFinite(vramPctRaw)
          ? `${Math.round(vramPctRaw)}%`
          : '—';
      }
      const vramUsedEl = document.getElementById('sumVramUsed');
      if (vramUsedEl) {
        if (g.vram_used_mb != null && g.vram_total_mb != null) {
          const u = Math.round(Number(g.vram_used_mb) / 1024 * 10) / 10;
          const t = Math.round(Number(g.vram_total_mb) / 1024 * 10) / 10;
          vramUsedEl.textContent = `${u}/${t} GB`;
          vramUsedEl.title = `${Math.round(g.vram_used_mb)} / ${Math.round(g.vram_total_mb)} MB`;
        } else {
          vramUsedEl.textContent = '—';
          vramUsedEl.removeAttribute('title');
        }
      }
      const vramBusEl = document.getElementById('sumVramBus');
      if (vramBusEl) {
        vramBusEl.textContent =
          memBusPct != null && Number.isFinite(Number(memBusPct))
            ? `bus ${Math.round(Number(memBusPct))}%`
            : 'bus —';
      }

      // Pulse Index — docked on game / live-session strip
      const soleFocus = soleHwFocus();
      if (soleFocus && comparison) {
        const part = soleFocus === 'memory' ? comparison.memory : comparison[soleFocus];
        const live = soleFocus === 'memory' ? part?.live_pressure_pct : part?.live_pct;
        const liveSmooth = smoothDisplayPct(`sum-league-${soleFocus}`, live ?? 0);
        document.getElementById('sumLeagueVal').textContent = `${liveSmooth}%`;
        setTierBadge(document.getElementById('sumLeagueBadge'), part?.tier_rank);
        document.getElementById('sumLeagueSub').textContent =
          `Class ${part?.tier_rank ?? '—'} · ${part?.tier_score ?? '—'}/100`;
        setMeterWidth(document.getElementById('sumLeagueMeter'), liveSmooth);
      } else {
        document.getElementById('sumLeagueVal').textContent = comparison ? `${leagueIdx}` : '—';
        setTierBadge(document.getElementById('sumLeagueBadge'), comparison?.composite_rank);
        document.getElementById('sumLeagueSub').textContent =
          comparison?.composite_rank != null
            ? `Class ${comparison.composite_rank} · /100`
            : 'Build score';
        setMeterWidth(document.getElementById('sumLeagueMeter'), leagueIdx);
      }

      const sh = l.sensor_health;
      const cpuT = c.temps?.package;
      const gpuT = g.junction_c;
      document.getElementById('drillSensorsSum').textContent = sh
        ? `${sh.ok}/${sh.total} live\nCPU ${cpuT != null ? Math.round(cpuT) : '—'}° · GPU ${gpuT != null ? Math.round(gpuT) : '—'}°`
        : 'Sensors offline';

      const st = l.stutter || {};
      const hitchMs = st.session?.hitch_ms_1pct;
      document.getElementById('drillChartsSum').textContent =
        `CPU ${Math.round(c.overall_pct ?? 0)}% · GPU ${g.busy_pct != null ? Math.round(g.busy_pct) : '—'}%\nhitch ${st.score ?? 0}${hitchMs != null ? ` · 1% ${hitchMs}ms` : ''}`;

      document.getElementById('drillBwSum').textContent =
        `VRAM ${bw.gpu?.vram_est_gbps ?? '—'} · DRAM ${bw.memory?.dram_est_gbps ?? '—'} GB/s`;

      const vramU = g.vram_used_mb, vramT = g.vram_total_mb;
      const cpuGpuBit = `CPU ${Math.round(c.overall_pct ?? 0)}% · GPU ${g.busy_pct != null ? Math.round(g.busy_pct) : '—'}%`;
      document.getElementById('drillComputeSum').textContent =
        (vramU != null && vramT != null)
          ? `${cpuGpuBit}\nVRAM ${Math.round(vramU / 1024 * 10) / 10}/${Math.round(vramT / 1024)}G`
          : cpuGpuBit;

      document.getElementById('drillLeagueSum').textContent = comparison
        ? `Index ${leagueIdx}/100 · class ${comparison.composite_rank ?? '—'}`
        : 'Building index…';

      renderGameSummaryCell(l.game_performance, gt, l.stutter);
    }

    /* Main load meters — Adrenaline-like primary set. Swap/game live elsewhere. */
    const UTIL_SPECS = [
      { id: 'cpu', label: 'CPU', icon: 'cpu', cls: 'cpu', hw: 'cpu' },
      { id: 'ram', label: 'RAM', icon: 'ram', cls: 'mem', hw: 'memory' },
      { id: 'gpu', label: 'GPU', icon: 'gpu', cls: 'gpu', hw: 'gpu' },
      { id: 'vram', label: 'VRAM', icon: 'gpu', cls: 'vram', hw: 'gpu' },
    ];
    /* Compact right-panel vitals — fewer rows so the column doesn't thrash height every tick.
       Full sensor detail stays in the hardware strip / drill panels. */
    const TEMP_SPECS = [
      { id: 'cpu-pkg', label: 'CPU', icon: 'cpu', key: 'package', hw: 'cpu' },
      { id: 'gpu-junc', label: 'GPU', icon: 'gpu', gpu: true, key: 'junction_c', hw: 'gpu' },
      { id: 'gpu-mem', label: 'VRAM', icon: 'temp', gpu: true, key: 'mem_temp_c', hw: 'gpu' },
    ];
    const BW_SPECS = [
      { id: 'vram-bw', label: 'GPU bus', icon: 'gpu', cls: 'bw-gpu', hw: 'gpu' },
      { id: 'dram-bw', label: 'RAM BW', icon: 'ram', cls: 'bw-mem', hw: 'memory' },
      { id: 'dram-psi', label: 'Wait', icon: 'cpu', cls: 'mem', hw: 'memory' },
    ];
    const IO_SPECS = [
      { id: 'disk-read', label: 'Read', icon: 'storage', cls: 'disk-read', hw: 'storage' },
      { id: 'disk-write', label: 'Write', icon: 'storage', cls: 'disk-write', hw: 'storage' },
      { id: 'disk-busy', label: 'Busy', icon: 'storage', cls: 'disk-busy', hw: 'storage' },
    ];

    /** Unified pulse dial updater — same API for temps / bus / storage / power. */
    function setPulseDial(rootId, dialId, pct, text, { hot = false, warn = false, missing = false } = {}) {
      const root = document.getElementById(rootId);
      if (!root || !root.classList.contains('pulse-dials')) return;
      const el = root.querySelector(`[data-dial="${dialId}"]`);
      if (!el) return;
      const p = missing ? 0 : Math.max(0, Math.min(100, Number(pct) || 0));
      el.style.setProperty('--dial-p', p.toFixed(1));
      const val = el.querySelector('[data-val]');
      if (val) val.textContent = text;
      el.classList.toggle('is-hot', !!hot);
      el.classList.toggle('is-warn', !!warn && !hot);
      el.classList.toggle('is-active', p >= 4);
      el.classList.toggle('is-missing', !!missing);
    }

    function updateIoCompact(diskRead, diskWrite, diskBusy) {
      const bPct = Number(diskBusy) || 0;
      const tip = `${fmtDiskRate(diskRead || 0)} R · ${fmtDiskRate(diskWrite || 0)} W`;
      const el = document.querySelector('#pressureMeters [data-dial="busy"]');
      if (el) el.title = `Disk busy · ${tip}`;
      setPulseDial('pressureMeters', 'busy', bPct, `${Math.round(bPct)}%`, { hot: bPct >= 85 });
    }
    const NET_SPECS = [
      { id: 'net-down', label: 'Down', icon: 'net', cls: 'net-down', hw: '' },
      { id: 'net-up', label: 'Up', icon: 'net', cls: 'net-up', hw: '' },
      { id: 'net-link', label: 'Link', icon: 'net', cls: 'net-link', hw: '' },
    ];
    const DISK_RATE_CEIL = 500;
    /** Soft ceiling for net bar fill — scales with link speed when known. */
    const NET_RATE_CEIL_DEFAULT = 100;
    const STUTTER_COMP_SPECS = [
      { id: 'major_faults', label: 'Page faults', cls: 'stutter-faults', hw: 'cpu memory' },
      { id: 'mem_stall', label: 'Memory wait', cls: 'stutter-mem', hw: 'memory' },
      { id: 'io_stall', label: 'I/O stall', cls: 'stutter-io', hw: 'cpu memory storage' },
      { id: 'swap', label: 'Swap', cls: 'stutter-swap', hw: 'memory' },
      { id: 'disk_spike', label: 'Disk spike', cls: 'stutter-disk', hw: 'memory storage' },
    ];
    const STUTTER_CAUSE_LABELS = {
      major_faults: 'Major page faults',
      mem_stall: 'Memory wait',
      io_stall: 'Disk I/O wait',
      swap: 'Swap activity',
      disk_spike: 'Disk spike',
    };
    const STUTTER_MIX_WEIGHTS = {
      major_faults: 0.38,
      mem_stall: 0.32,
      io_stall: 0.12,
      swap: 0.13,
      disk_spike: 0.05,
    };
    const STUTTER_MIX_SHORT = {
      major_faults: 'Page faults',
      mem_stall: 'Memory wait',
      io_stall: 'Disk wait',
      swap: 'Swap',
      disk_spike: 'Disk',
    };
    const STUTTER_GAUGE_COLORS = {
      severe: 'var(--sev-hot)',
      moderate: 'var(--sev-warn)',
      mild: 'var(--sev-info)',
      none: 'var(--sev-ok)',
    };

    function metricLabelHtml(s) {
      const icon = s.icon ? hwIcon(s.icon, 'hw-metric-glyph') : '';
      return `<span class="metric-bar-label hw-row">${icon}${esc(s.label)}</span>`;
    }

    function syncMetricHwTags(containerId, specs) {
      specs.forEach(s => {
        const row = document.querySelector(`#${containerId} [data-mid="${s.id}"]`);
        if (!row) return;
        if (s.hw) row.setAttribute('data-hw', s.hw);
        else row.removeAttribute('data-hw');
      });
    }

    function ensureMetricList(containerId, specs, trackKey = 'cls') {
      const el = document.getElementById(containerId);
      // Bump when compact vitals specs change so lists rebuild once after deploy
      if (el.dataset.hwVer !== '6') {
        delete el.dataset.init;
        el.dataset.hwVer = '6';
      }
      if (el.dataset.init) return;
      el.innerHTML = specs.map(s => `
        <div class="metric-bar" data-mid="${s.id}"${s.hw ? ` data-hw="${s.hw}"` : ''}>
          <div class="metric-bar-head">
            ${metricLabelHtml(s)}
            <span class="metric-bar-val" data-val>—</span>
          </div>
          <div class="metric-bar-track ${s[trackKey] || 'cpu'}" data-track><span data-fill style="width:0%"></span></div>
          <span class="metric-bar-sub" data-sub>—</span>
        </div>`).join('');
      el.dataset.init = '1';
    }

    function setMetricBar(containerId, id, pct, valText, subText, valCls, trackCls) {
      const row = document.querySelector(`#${containerId} [data-mid="${id}"]`);
      if (!row) return;
      const val = row.querySelector('[data-val]');
      val.textContent = valText;
      val.className = `metric-bar-val${valCls ? ' ' + valCls : ''}`;
      setMeterWidth(row.querySelector('[data-fill]'), pct);
      if (trackCls) row.querySelector('[data-track]').className = `metric-bar-track ${trackCls}`;
      const subEl = row.querySelector('[data-sub]');
      // Always text — never promote untrusted game/sensor strings to HTML
      subEl.textContent = subText == null ? '' : String(subText);
    }

    function tempPct(v, maxC) {
      const max = maxC || hwScales.cpu_temp_max_c || 105;
      return v == null ? 0 : Math.min(100, (v / max) * 100);
    }
    function fmtClockMhz(mhz) {
      if (mhz == null || !Number.isFinite(Number(mhz))) return '—';
      const n = Number(mhz);
      return n >= 1000 ? `${(n / 1000).toFixed(1)}G` : `${Math.round(n)}M`;
    }
    function cpuClockStats(cores) {
      const mhz = (cores || []).map(c => Number(c.mhz)).filter(n => n > 0);
      if (!mhz.length) return { avg: null, peak: null };
      return {
        avg: Math.round(mhz.reduce((a, b) => a + b, 0) / mhz.length),
        peak: Math.round(Math.max(...mhz)),
      };
    }
    function tempValCls(v) {
      if (v == null) return '';
      if (v >= 90) return 'temp hot';
      if (v >= 75) return 'temp warn';
      return 'temp';
    }
    function tempTrackCls(v) {
      if (v == null) return 'temp';
      if (v >= 90) return 'temp hot';
      if (v >= 75) return 'temp warn';
      return 'temp';
    }

    function sparkBucketAvg(p, fn) {
      const slice = Array.isArray(p) ? p : [p];
      return avg(slice, fn);
    }
    /** Peak within bucket — preserves short spikes before we damp them on the chart. */
    function sparkBucketMax(p, fn) {
      const slice = Array.isArray(p) ? p : [p];
      const vals = slice.map(fn).filter(x => x != null && !isNaN(x));
      return vals.length ? Math.max(...vals) : 0;
    }

    /**
     * Append-only Live overview ring (1 Hz).
     * Past points are NEVER recomputed — only a new tip is pushed each second.
     * This is what keeps the graph readable; re-bucketing rawHistory always wiggled.
     */
    /** Keep a full hour in the ring so 60m view has data; X-axis window is chartViewSec. */
    const SPARK_RING_KEEP_SEC = 3600;
    const SPARK_DISK_REF_MBPS = 100; // 100 MB/s → 100% (NVMe can do more; gaming-relevant scale)
    function sparkTempMin() { return hwScales.cpu_temp_min_c ?? 30; }
    function sparkTempMax() {
      return Math.max(hwScales.cpu_temp_max_c || 105, hwScales.gpu_temp_max_c || 105);
    }
    const SPARK_RING_KEYS = [
      'cpu', 'gpu', 'ram', 'vram', 'disk', 'diskR', 'diskW', 'cpuTemp', 'gpuTemp',
      'hitch', 'hitchEvent', 'index',
    ];
    /** Scoreboard chips: ~1 minute so they roll, not scribble 10 minutes into 120px. */
    const CHIP_SPARK_SEC = 48;
    const sparkRing = {
      ts: [],
      labels: [],
      cpu: [],
      gpu: [],
      ram: [],
      vram: [],
      disk: [],
      diskR: [],
      diskW: [],
      cpuTemp: [],
      gpuTemp: [],
      hitch: [],
      hitchEvent: [],
      index: [],
      lastTs: 0,
      ema: {
        cpu: null, gpu: null, ram: null, vram: null, disk: null,
        diskR: null, diskW: null, cpuTemp: null, gpuTemp: null, hitch: null, index: null,
      },
      seeded: false,
    };

    const SPARK_TOGGLE_DEFAULTS = {
      cpu: true, gpu: true, ram: true,
      diskR: true, diskW: true,
      cpuTemp: true, gpuTemp: true,
      hitch: true,
    };
    function loadSparkEnabled() {
      try {
        const raw = sessionStorage.getItem('pulse-spark-enabled');
        if (!raw) return { ...SPARK_TOGGLE_DEFAULTS };
        const parsed = JSON.parse(raw);
        return { ...SPARK_TOGGLE_DEFAULTS, ...parsed };
      } catch (_) {
        return { ...SPARK_TOGGLE_DEFAULTS };
      }
    }
    let sparkEnabled = loadSparkEnabled();
    function persistSparkEnabled() {
      try { sessionStorage.setItem('pulse-spark-enabled', JSON.stringify(sparkEnabled)); } catch (_) { /* ignore */ }
    }
    function toggleSparkSeries(key) {
      if (!(key in sparkEnabled)) return;
      sparkEnabled[key] = !sparkEnabled[key];
      // Keep at least one series on
      if (!Object.values(sparkEnabled).some(Boolean)) sparkEnabled[key] = true;
      persistSparkEnabled();
      try { renderSparkChart(); } catch (_) { /* ignore */ }
    }

    function resetSparkRing() {
      sparkRing.ts = [];
      sparkRing.labels = [];
      SPARK_RING_KEYS.forEach(k => { sparkRing[k] = []; });
      sparkRing.lastTs = 0;
      sparkRing.ema = {
        cpu: null, gpu: null, ram: null, vram: null, disk: null,
        diskR: null, diskW: null, cpuTemp: null, gpuTemp: null, hitch: null, index: null,
      };
      sparkRing.seeded = false;
      if (typeof sparkChart !== 'undefined' && sparkChart) {
        sparkChart._pulseStructKey = '';
      }
    }

    function sparkRingShiftFront() {
      sparkRing.ts.shift();
      sparkRing.labels.shift();
      SPARK_RING_KEYS.forEach(k => sparkRing[k].shift());
    }

    function sparkDiskActivity(disk) {
      const r = Number(disk?.read_mbps) || 0;
      const w = Number(disk?.write_mbps) || 0;
      // Throughput only — busy_pct often pegs at 100% under light sustained I/O.
      return clampPct((Math.max(r, w) / SPARK_DISK_REF_MBPS) * 100);
    }
    function sparkDiskReadPct(disk) {
      return clampPct(((Number(disk?.read_mbps) || 0) / SPARK_DISK_REF_MBPS) * 100);
    }
    function sparkDiskWritePct(disk) {
      return clampPct(((Number(disk?.write_mbps) || 0) / SPARK_DISK_REF_MBPS) * 100);
    }

    function sparkCpuTempC(h) {
      const t = h?.cpu?.temps || {};
      if (t.package != null && !isNaN(t.package)) return +t.package;
      const ccd = t.ccd || [];
      const nums = ccd.filter(v => v != null && !isNaN(v));
      return nums.length ? Math.max(...nums) : null;
    }

    function sparkGpuTempC(h) {
      const g = h?.gpu?.discrete || {};
      if (g.junction_c != null && !isNaN(g.junction_c)) return +g.junction_c;
      if (g.edge_c != null && !isNaN(g.edge_c)) return +g.edge_c;
      return null;
    }

    /** Same GPU % the scoreboard chip shows (shader/GFX, not the AMD busy square-wave). */
    function histGpuPct(h) {
      const g = h?.gpu?.discrete || {};
      if (g.gfx_pct != null && Number.isFinite(Number(g.gfx_pct))) return Number(g.gfx_pct);
      const engines = Array.isArray(g.engines) ? g.engines : [];
      const gfx = engines.find(e => e && e.id === 'gfx');
      if (gfx && gfx.pct != null && Number.isFinite(Number(gfx.pct))) return Number(gfx.pct);
      if (g.busy_pct != null && Number.isFinite(Number(g.busy_pct))) return Number(g.busy_pct);
      return null;
    }

    function histVramPct(h) {
      const g = h?.gpu?.discrete || {};
      if (g.vram_pct != null && Number.isFinite(Number(g.vram_pct))) return Number(g.vram_pct);
      if (g.vram_used_mb != null && g.vram_total_mb) {
        const t = Number(g.vram_total_mb);
        if (t > 0) return 100 * Number(g.vram_used_mb) / t;
      }
      return null;
    }

    function sparkEmaPush(key, raw, alpha, { clamp01 = true } = {}) {
      let v = Number(raw);
      if (raw == null || isNaN(v)) v = clamp01 ? 0 : null;
      if (v == null) {
        // Carry last temp if sensor blips; don't invent zeros on the °C axis
        const prev = sparkRing.ema[key];
        return prev == null ? null : +prev.toFixed(1);
      }
      if (clamp01) v = clampPct(v);
      const prev = sparkRing.ema[key];
      const a = prev == null ? 1 : alpha;
      const s = prev == null ? v : prev + a * (v - prev);
      sparkRing.ema[key] = s;
      return +s.toFixed(1);
    }

    function sparkRingTrim() {
      // Prefer time window so a burst of faster samples can't shrink visible history.
      const oldest = (sparkRing.ts.at(-1) ?? 0) - SPARK_RING_KEEP_SEC;
      while (sparkRing.ts.length > 2 && sparkRing.ts[0] < oldest) {
        sparkRingShiftFront();
      }
      // Hard cap against runaway growth if timestamps stall/repeat.
      const maxPts = SPARK_RING_KEEP_SEC + 30;
      while (sparkRing.ts.length > maxPts) {
        sparkRingShiftFront();
      }
    }

    function sparkRingPushSample(h, alphas) {
      sparkRing.ts.push(h.ts);
      sparkRing.labels.push(fmtTime(h.ts));
      sparkRing.cpu.push(sparkEmaPush('cpu', h.cpu?.overall_pct, alphas.pct, { clamp01: false }));
      sparkRing.gpu.push(sparkEmaPush('gpu', histGpuPct(h), alphas.pct, { clamp01: false }));
      sparkRing.ram.push(sparkEmaPush('ram', h.memory?.pct, alphas.pct, { clamp01: false }));
      sparkRing.vram.push(sparkEmaPush('vram', histVramPct(h), Math.min(0.55, (alphas.pct || 0.4) * 1.2), { clamp01: false }));
      sparkRing.disk.push(sparkEmaPush('disk', sparkDiskActivity(h.disk), alphas.pct * 0.85));
      sparkRing.diskR.push(sparkEmaPush('diskR', sparkDiskReadPct(h.disk), alphas.pct * 0.85));
      sparkRing.diskW.push(sparkEmaPush('diskW', sparkDiskWritePct(h.disk), alphas.pct * 0.85));
      sparkRing.cpuTemp.push(sparkEmaPush('cpuTemp', sparkCpuTempC(h), alphas.temp, { clamp01: false }));
      sparkRing.gpuTemp.push(sparkEmaPush('gpuTemp', sparkGpuTempC(h), alphas.temp, { clamp01: false }));
      // Hitch is snappier than load, but not raw — cubic tension on a 0/80 square
      // wave filled the plot. Missing GPU/index samples carry forward, not 0.
      const hitchAlpha = Math.min(1, (alphas.pct || 0.32) * 1.35);
      sparkRing.hitch.push(sparkEmaPush('hitch', h.stutter?.score, hitchAlpha, { clamp01: false }));
      sparkRing.hitchEvent.push(h.stutter?.event ? 1 : 0);
      sparkRing.index.push(sparkEmaPush('index', h.comparison?.session_index, alphas.pct * 0.55, { clamp01: false }));
    }

    /** One-shot seed from rawHistory so the chart isn't empty after reload. */
    function sparkRingSeedFromHistory() {
      if (!rawHistory.length) return;
      // If history grew a lot after a thin seed (frozen server / empty bootstrap), re-seed.
      if (sparkRing.seeded && rawHistory.length >= 8 && sparkRing.ts.length < 4) {
        resetSparkRing();
      }
      if (sparkRing.seeded) return;
      sparkRing.seeded = true;
      const cut = rawHistory.filter(h => h.ts >= (rawHistory.at(-1).ts - SPARK_RING_KEEP_SEC));
      let last = 0;
      for (const h of cut) {
        // Allow denser seed when history is sparse; skip only true duplicates
        if (last && h.ts - last < 0.45) continue;
        last = h.ts;
        sparkRingPushSample(h, { pct: 0.5, temp: 0.4 });
      }
      sparkRingTrim();
      if (sparkRing.ts.length) sparkRing.lastTs = sparkRing.ts.at(-1);
    }

    /** Append the latest metrics point (call once per poll). */
    function sparkRingIngest(latest) {
      if (!latest || latest.ts == null) return;
      sparkRingSeedFromHistory();
      const ts = latest.ts;
      // Same timestamp as seed tip — don't double-push
      if (sparkRing.lastTs && Math.abs(ts - sparkRing.lastTs) < 0.45) return;
      sparkRing.lastTs = ts;
      sparkRingPushSample(latest, { pct: 0.42, temp: 0.32 });
      sparkRingTrim();
    }

    function sparkRingEnsure() {
      // Keep ingesting while paused/zoomed so resume has a continuous ring (no hole).
      if (lastLatest) sparkRingIngest(lastLatest);
      else if (rawHistory.length) sparkRingIngest(rawHistory.at(-1));
      else if (!sparkRing.seeded) sparkRingSeedFromHistory();
    }

    /** Parse #rgb / #rrggbb into [r,g,b]. */
    function hexToRgb(hex) {
      if (!hex || typeof hex !== 'string') return [160, 170, 180];
      let h = hex.replace('#', '').trim();
      if (h.length === 3) h = h.split('').map(c => c + c).join('');
      if (h.length !== 6) return [160, 170, 180];
      return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
    }

    function rgbaFromHex(hex, a) {
      const [r, g, b] = hexToRgb(hex);
      return `rgba(${r},${g},${b},${a})`;
    }

    /** Vertical gradient fill under a spark series (falls back to flat rgba). */
    function sparkAreaFill(hex, topA, botA) {
      return (ctx) => {
        const chart = ctx.chart;
        const { ctx: c, chartArea } = chart;
        if (!chartArea) return rgbaFromHex(hex, topA);
        const g = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
        g.addColorStop(0, rgbaFromHex(hex, topA));
        g.addColorStop(0.55, rgbaFromHex(hex, (topA + botA) * 0.45));
        g.addColorStop(1, rgbaFromHex(hex, botA));
        return g;
      };
    }

    function updateSparkSwatches(allSeries, activeKeys) {
      const el = document.getElementById('sparkChartSwatches');
      if (!el) return;
      const key = allSeries.map(s => `${s.key}:${sparkEnabled[s.key] ? 1 : 0}:${s.color}`).join('|');
      if (el.dataset.key === key) return;
      el.dataset.key = key;
      const n = allSeries.length || 8;
      el.style.setProperty('--spark-n', String(n));
      el.style.setProperty('--spark-row', String(n <= 4 ? n : Math.ceil(n / 2)));
      el.innerHTML = allSeries.map(s => {
        const on = sparkEnabled[s.key] !== false;
        return `<button type="button" class="rig-chart-swatch${on ? '' : ' is-off'}" data-spark-key="${esc(s.key)}" `
          + `title="${on ? 'Hide' : 'Show'} ${esc(s.label)}" aria-pressed="${on ? 'true' : 'false'}">`
          + `<i style="background:${s.color};color:${s.color}"></i>`
          + `<span>${esc(s.label)}</span></button>`;
      }).join('');
      el.querySelectorAll('[data-spark-key]').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          toggleSparkSeries(btn.dataset.sparkKey);
        });
      });
    }

    function downsampleSpark(arr, maxPts) {
      if (!arr || !arr.length) return [];
      if (arr.length <= maxPts) return arr;
      // Time-even buckets, not index stride — stride crawled the line every tick.
      const out = [];
      const n = arr.length;
      const bucket = n / maxPts;
      for (let i = 0; i < maxPts; i++) {
        const a = Math.floor(i * bucket);
        const b = Math.max(a + 1, Math.floor((i + 1) * bucket));
        let sum = 0;
        let c = 0;
        for (let j = a; j < b && j < n; j++) {
          const v = Number(arr[j]);
          if (Number.isFinite(v)) { sum += v; c += 1; }
        }
        out.push(c ? sum / c : 0);
      }
      return out;
    }

    /** Last ~CHIP_SPARK_SEC of the 1 Hz ring — short window so chips roll. */
    function chipSparkWindow(tsArr, valArr) {
      const n = Math.min(tsArr?.length || 0, valArr?.length || 0);
      if (!n) return [];
      const tCut = (tsArr[n - 1] || 0) - CHIP_SPARK_SEC;
      const out = [];
      for (let i = 0; i < n; i++) {
        if (tsArr[i] >= tCut) out.push(valArr[i]);
      }
      return out;
    }

    function chipSparkPath(values, w, h) {
      const n = values.length;
      if (n < 2) return '';
      const nums = values.map(v => Math.max(0, Math.min(100, Number(v) || 0)));
      // Always 0–100% so chips stay comparable; autoscale turned a steady 40%
      // RAM line into a solid painted slab when the card went wide.
      const yMax = 100;
      const pad = 1.2;
      const pts = nums.map((v, i) => {
        const x = (i / (n - 1)) * w;
        const y = (1 - v / yMax) * (h - pad * 2) + pad;
        return [x, y];
      });
      let d = `M${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)}`;
      for (let i = 1; i < pts.length; i++) d += ` L${pts[i][0].toFixed(2)} ${pts[i][1].toFixed(2)}`;
      return d;
    }

    function vramHistoryPcts() {
      if (!Array.isArray(rawHistory) || !rawHistory.length) return [];
      return rawHistory.map(h => {
        const g = h.gpu?.discrete || {};
        if (g.vram_pct != null && Number.isFinite(Number(g.vram_pct))) return Number(g.vram_pct);
        if (g.vram_used_mb != null && g.vram_total_mb) {
          return 100 * Number(g.vram_used_mb) / Number(g.vram_total_mb);
        }
        return 0;
      });
    }

    function paintChipSpark(svgId, values) {
      const svg = document.getElementById(svgId);
      if (!svg) return;
      const series = values.length > 96 ? downsampleSpark(values, 72) : values;
      const line = chipSparkPath(series, 120, 36);
      const fill = line ? `${line} L120 36 L0 36 Z` : '';
      const lineEl = svg.querySelector('.sum-chip-spark-line');
      const fillEl = svg.querySelector('.sum-chip-spark-fill');
      if (lineEl && lineEl.getAttribute('d') !== line) lineEl.setAttribute('d', line);
      if (fillEl && fillEl.getAttribute('d') !== fill) fillEl.setAttribute('d', fill);
    }

    function sliceSeriesToView(tsArr, valArr) {
      const n = Math.min(tsArr?.length || 0, valArr?.length || 0);
      if (!n) return [];
      const tCut = (tsArr[n - 1] || 0) - chartViewSec;
      const out = [];
      for (let i = 0; i < n; i++) {
        if (tsArr[i] >= tCut) out.push(valArr[i]);
      }
      return out;
    }

    function paintChipSparks() {
      paintChipSpark('sumCpuSpark', chipSparkWindow(sparkRing.ts, sparkRing.cpu));
      paintChipSpark('sumGpuSpark', chipSparkWindow(sparkRing.ts, sparkRing.gpu));
      paintChipSpark('sumMemSpark', chipSparkWindow(sparkRing.ts, sparkRing.ram));
      paintChipSpark('sumVramSpark', chipSparkWindow(sparkRing.ts, sparkRing.vram));
    }

    function renderSparkChart() {
      // Always ingest: pause/zoom freeze the X window, not the ring.
      sparkRingEnsure();
      paintChipSparks();
      if (!canvasVisible(sparkChart)) return;

      // All toggleable series — Disk R/W are separate (scaled % of SPARK_DISK_REF_MBPS).
      const allSparkSeries = [
        {
          key: 'cpu', label: 'CPU', color: METRIC.cpu, focus: ['cpu'],
          data: sparkRing.cpu, fillTop: 0.22, fillBot: 0.02, primary: true, axis: 'y',
        },
        {
          key: 'gpu', label: 'GPU', color: METRIC.gpu, focus: ['gpu'],
          data: sparkRing.gpu, fillTop: 0.18, fillBot: 0.015, axis: 'y',
        },
        {
          key: 'ram', label: 'RAM', color: METRIC.mem, focus: ['memory'],
          data: sparkRing.ram, fillTop: 0.14, fillBot: 0.01, axis: 'y',
        },
        {
          key: 'diskR', label: 'Disk R', color: METRIC.disk, focus: ['storage'],
          data: sparkRing.diskR, fillTop: 0.1, fillBot: 0.01, isDisk: true, axis: 'y',
        },
        {
          key: 'diskW', label: 'Disk W', color: METRIC.diskWrite, focus: ['storage'],
          data: sparkRing.diskW, fillTop: 0.1, fillBot: 0.01, isDisk: true, axis: 'y',
        },
        {
          key: 'cpuTemp', label: 'CPU °C', color: METRIC.cpu, focus: ['cpu'],
          data: sparkRing.cpuTemp, axis: 'y1', isTemp: true,
        },
        {
          key: 'gpuTemp', label: 'GPU °C', color: METRIC.gpu, focus: ['gpu'],
          data: sparkRing.gpuTemp, axis: 'y1', isTemp: true,
        },
        {
          key: 'hitch', label: 'Hitch', color: METRIC.stutter, keep: true,
          data: sparkRing.hitch, fillTop: 0, fillBot: 0, axis: 'y', isHitch: true,
        },
      ];

      // HW focus filters the *available* set; sparkEnabled toggles what is drawn.
      // Hitch stays as a correlate overlay under any hardware focus.
      let candidates = allSparkSeries;
      if (anyHwFocus()) {
        candidates = allSparkSeries.filter(s => s.keep || s.focus?.some(f => hwFocusHas(f)));
        if (!candidates.length) candidates = allSparkSeries;
      }
      // Always show swatches for the candidate set (including off ones).
      updateSparkSwatches(candidates);
      let active = candidates.filter(s => sparkEnabled[s.key] !== false);
      if (!active.length) active = candidates.slice(0, 1);

      const structKey = `spark|${hwFocusKey()}|${active.map(s => s.key).join(',')}|${Object.values(sparkEnabled).join('')}|${chartViewSec}|${sparkTempMin()}|${sparkTempMax()}|${chartsPaused}|${chartZoomed}`;

      const newDatasets = active.map((d, idx) => {
        const isDisk = !!d.isDisk;
        const isTemp = !!d.isTemp;
        const isHitch = !!d.isHitch;
        const primary = idx === 0 && !isHitch;
        const cap = Math.max(160, Math.min(560, Math.round((sparkChart.width || 640) * 0.65)));
        const pts = xySeriesView(sparkRing.ts, d.data, chartViewSec, cap, isHitch ? 'max' : 'avg');
        return {
          label: d.label,
          data: pts,
          borderColor: d.color,
          backgroundColor: isTemp || isDisk || isHitch
            ? 'transparent'
            : sparkAreaFill(d.color, (d.fillTop ?? 0.18) * 1.15, d.fillBot ?? 0.02),
          fill: !isTemp && !isDisk && !isHitch,
          tension: isHitch ? 0 : (isTemp ? 0.1 : 0),
          borderWidth: isHitch ? 1.7 : (isTemp ? 1.75 : (primary ? 2.5 : (isDisk ? 2 : 2.15))),
          borderJoinStyle: 'round',
          borderCapStyle: isTemp ? 'round' : 'round',
          borderDash: isTemp ? [1.5, 3.5] : undefined,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointBackgroundColor: d.color,
          pointBorderColor: rgbaFromHex(d.color, 0.4),
          pointBorderWidth: 1.5,
          pointHitRadius: 8,
          yAxisID: d.axis || 'y',
          order: isHitch ? 0 : (isTemp ? 5 : (isDisk ? 4 : idx + 1)),
          spanGaps: true,
        };
      });
      if (active.some(s => s.key === 'hitch')) {
        const tCut = (sparkRing.ts.at(-1) || 0) - chartViewSec - 2;
        const eventPts = [];
        const nEv = Math.min(sparkRing.ts.length, sparkRing.hitch.length, sparkRing.hitchEvent.length);
        for (let i = 0; i < nEv; i++) {
          if (sparkRing.hitchEvent[i] && sparkRing.ts[i] >= tCut) {
            eventPts.push({ x: sparkRing.ts[i], y: sparkRing.hitch[i] ?? 0 });
          }
        }
        newDatasets.push({
          type: 'scatter',
          label: 'Hitch event',
          data: eventPts,
          borderColor: METRIC.thermal,
          backgroundColor: METRIC.thermal,
          pointRadius: 3.5,
          pointHoverRadius: 5,
          pointStyle: 'triangle',
          pointBackgroundColor: METRIC.thermal,
          pointBorderColor: rgbaFromHex(METRIC.thermal, 0.45),
          pointBorderWidth: 1,
          showLine: false,
          yAxisID: 'y',
          order: -1,
        });
      }

      if (!chartInteractActive) applyLiveTimeAxis(sparkChart, chartViewSec);

      const showTempAxis = active.some(s => s.isTemp);
      lockPctAxis(sparkChart, 'y');
      if (sparkChart.options.scales.y.ticks) {
        sparkChart.options.scales.y.ticks.stepSize = 25;
        sparkChart.options.scales.y.ticks.callback = v => `${v}%`;
      }
      sparkChart.options.scales.y.title = {
        display: true,
        text: '%',
        color: 'rgba(154, 163, 178, .7)',
        font: { size: 9, weight: '600', family: 'Inter' },
      };
      if (showTempAxis) {
        if (!sparkChart.options.scales.y1) {
          sparkChart.options.scales.y1 = {
            position: 'right',
            min: sparkTempMin(),
            max: sparkTempMax(),
            grid: { drawOnChartArea: false },
            border: { display: false },
            ticks: {
              color: 'rgba(206, 219, 238, .7)',
              font: { size: 9, weight: '500' },
              callback: v => `${v}°`,
              stepSize: 25,
              padding: 4,
            },
            title: {
              display: true,
              text: '°C',
              color: 'rgba(206, 219, 238, .65)',
              font: { size: 9, weight: '600', family: 'Inter' },
            },
          };
        } else {
          sparkChart.options.scales.y1.display = true;
          sparkChart.options.scales.y1.min = sparkTempMin();
          sparkChart.options.scales.y1.max = sparkTempMax();
          if (sparkChart.options.scales.y1.title) {
            sparkChart.options.scales.y1.title.display = true;
            sparkChart.options.scales.y1.title.text = '°C';
          }
        }
      } else if (sparkChart.options.scales.y1) {
        sparkChart.options.scales.y1.display = false;
      }
      if (sparkChart.options.scales.x?.ticks) {
        sparkChart.options.scales.x.ticks.maxTicksLimit = 5;
      }

      if (structKey === sparkChart._pulseStructKey && sparkChart.data.datasets.length === newDatasets.length) {
        newDatasets.forEach((ds, i) => {
          const cur = sparkChart.data.datasets[i];
          cur.data = ds.data;
          cur.label = ds.label;
          cur.borderColor = ds.borderColor;
          cur.backgroundColor = ds.backgroundColor;
          cur.fill = ds.fill;
          cur.borderWidth = ds.borderWidth;
          cur.borderDash = ds.borderDash;
          cur.pointRadius = ds.pointRadius;
          cur.pointHoverRadius = ds.pointHoverRadius;
          cur.pointBackgroundColor = ds.pointBackgroundColor;
          cur.pointBorderColor = ds.pointBorderColor;
          cur.yAxisID = ds.yAxisID;
        });
      } else {
        sparkChart._pulseStructKey = structKey;
        sparkChart.data.datasets = newDatasets;
      }
      const chartLabel = document.getElementById('sparkChartLabel');
      if (chartLabel) {
        const viewLbl = CHART_VIEW_LABELS[chartViewSec] || `${Math.round(chartViewSec / 60)} min`;
        const mode = chartZoomed ? 'zoomed' : (chartsPaused ? 'paused' : viewLbl);
        const diskOn = sparkEnabled.diskR || sparkEnabled.diskW;
        const hitchOn = active.some(s => s.key === 'hitch');
        if (!anyHwFocus()) {
          const bits = [showTempAxis ? 'Load & temps' : 'Load'];
          if (hitchOn) bits.push('hitch');
          if (diskOn) bits.push(`disk (${SPARK_DISK_REF_MBPS} MB/s=100%)`);
          chartLabel.textContent = `${bits.join(' · ')} · ${mode}`;
        } else if (hwFocusSet.size === 1 && hwFocusHas('storage')) {
          chartLabel.textContent = hitchOn
            ? `Disk R/W · hitch · ${mode} · ${SPARK_DISK_REF_MBPS} MB/s = 100%`
            : `Disk R/W · ${mode} · ${SPARK_DISK_REF_MBPS} MB/s = 100%`;
        } else {
          chartLabel.textContent = hitchOn
            ? `${hwFocusLabelText()} · hitch · ${mode}`
            : `${hwFocusLabelText()} · ${mode}`;
        }
      }
      if (!chartInteractActive) sparkChart.update('none');
    }

    function renderRigInsight(l) {
      const c = l.cpu || {}, m = l.memory || {}, g = l.gpu?.discrete || {};
      const cores = c.per_core || [];
      const peakCore = cores.length ? cores.reduce((a, b) => (b.pct > a.pct ? b : a), cores[0]) : null;
      const lowCore = cores.length ? cores.reduce((a, b) => (b.pct < a.pct ? b : a), cores[0]) : null;
      const peakPct = peakCore ? smoothDisplayPct('rig-peak-core', peakCore.pct) : 0;

      // Chart-header KPIs: same three series as the Load · 5 min graph (live “now”)
      const cpuNow = c.overall_pct != null ? smoothDisplayPct('rig-kpi-cpu', c.overall_pct) : null;
      const gpuNow = g.busy_pct != null ? smoothDisplayPct('rig-kpi-gpu', g.busy_pct) : null;
      const ramNow = m.pct != null ? smoothDisplayPct('rig-kpi-ram', m.pct) : null;

      const setKpi = (id, subId, value, sub, severity) => {
        const el = document.getElementById(id);
        const subEl = document.getElementById(subId);
        if (el) {
          el.textContent = value;
          el.className = `v${severity ? ` ${severity}` : ''}`;
        }
        if (subEl) subEl.textContent = sub;
      };
      const sev = (p) => (p == null ? '' : p >= 90 ? 'severe' : p >= 75 ? 'moderate' : p >= 50 ? 'mild' : 'ok');

      setKpi(
        'rigKpiCpu', 'rigKpiCpuSub',
        cpuNow != null ? `${cpuNow}%` : '—',
        peakCore ? `peak core ${peakPct}%` : 'overall',
        sev(cpuNow),
      );
      const gpuHot = g.junction_c != null ? Math.round(g.junction_c) : null;
      setKpi(
        'rigKpiGpu', 'rigKpiGpuSub',
        gpuNow != null ? `${gpuNow}%` : '—',
        gpuHot != null ? `${gpuHot}° hotspot` : (g.edge_c != null ? `${Math.round(g.edge_c)}° edge` : 'busy'),
        sev(gpuNow),
      );
      const ramGiB = m.used_gb != null && m.total_gb != null
        ? `${m.used_gb.toFixed?.(1) ?? m.used_gb}/${Math.round(m.total_gb)}G`
        : (m.used_bytes && m.total_bytes
          ? `${(m.used_bytes / 1e9).toFixed(1)}/${Math.round(m.total_bytes / 1e9)}G`
          : null);
      setKpi(
        'rigKpiRam', 'rigKpiRamSub',
        ramNow != null ? `${ramNow}%` : '—',
        ramGiB || ((m.swap_pct || 0) > 1 ? `swap ${Math.round(m.swap_pct)}%` : 'used'),
        sev(ramNow),
      );

      const coreMeta = document.getElementById('rigCoreMeta');
      if (coreMeta) {
        if (!cores.length) {
          coreMeta.textContent = '—';
        } else {
          const spread = Math.round(peakCore.pct - lowCore.pct);
          coreMeta.textContent = `peak ${peakPct}% · core ${peakCore.id} · gap ${spread}%`;
        }
      }

      const engines = (g.engines || []).filter(e => e.pct != null);
      const peakEngine = engines.length
        ? engines.reduce((a, b) => ((b.pct ?? 0) > (a.pct ?? 0) ? b : a), engines[0])
        : null;
      const engineMeta = document.getElementById('rigGpuEngineMeta');
      if (engineMeta) {
        if (!peakEngine) {
          engineMeta.textContent = '—';
        } else {
          const peakEngPct = smoothDisplayPct('rig-peak-gpu-eng', peakEngine.pct ?? 0);
          engineMeta.textContent = `peak ${peakEngPct}% · ${gpuEngineLabel(peakEngine.id, peakEngine.label)}`;
        }
      }

      const statusEl = document.getElementById('rigStatus');
      if (statusEl) {
        const cpu = cpuNow != null ? cpuNow : '—';
        const gpu = gpuNow != null ? gpuNow : '—';
        const ram = ramNow != null ? ramNow : '—';
        let text = `${cpu}/${gpu}/${ram}`;
        let full = `CPU ${cpu}% · GPU ${gpu}% · RAM ${ram}%`;
        if ((m.swap_pct || 0) > 5) {
          const sw = Math.round(m.swap_pct);
          text += ` s${sw}`;
          full += ` · swap ${sw}%`;
        }
        const loadMax = Math.max(c.overall_pct ?? 0, g.busy_pct ?? 0, m.pct ?? 0);
        const cls = loadMax >= 90 ? 'hot' : loadMax >= 75 ? 'warn' : 'ok';
        statusEl.textContent = text;
        statusEl.title = full;
        statusEl.className = `rig-status ${cls}`;
      }
    }

    function renderStutterChart() {
      if (!canvasVisible(stutterChart)) return;
      sparkRingEnsure();
      const cap = Math.max(160, Math.min(560, Math.round((stutterChart.width || 640) * 0.65)));
      const structKey = `stutter|load|${chartViewSec}|${chartsPaused}|${chartZoomed}`;
      const scorePts = xySeriesView(sparkRing.ts, sparkRing.hitch, chartViewSec, cap, 'max');
      const cpuPts = xySeriesView(sparkRing.ts, sparkRing.cpu, chartViewSec, cap);
      const gpuPts = xySeriesView(sparkRing.ts, sparkRing.gpu, chartViewSec, cap);
      const estTs = [];
      const estVals = [];
      const tCut = (sparkRing.ts.at(-1) ?? rawHistory.at(-1)?.ts ?? 0) - chartViewSec - 2;
      for (const h of rawHistory) {
        if (h?.ts == null || h.ts < tCut) continue;
        estTs.push(h.ts);
        estVals.push(h.stutter?.est_ms ?? 0);
      }
      const estPts = xySeriesView(estTs, estVals, chartViewSec, cap, 'max');
      const hitchByTs = new Map(scorePts.map(p => [p.x, p.y]));
      const eventPoints = [];
      const nEv = Math.min(sparkRing.ts.length, sparkRing.hitch.length, sparkRing.hitchEvent.length);
      const evCut = (sparkRing.ts.at(-1) || 0) - chartViewSec - 2;
      for (let i = 0; i < nEv; i++) {
        if (!sparkRing.hitchEvent[i] || sparkRing.ts[i] < evCut) continue;
        eventPoints.push({ x: sparkRing.ts[i], y: sparkRing.hitch[i] ?? hitchByTs.get(sparkRing.ts[i]) ?? 0 });
      }
      const newDatasets = [
        {
          label: 'Hitch score', data: scorePts, borderColor: CHART.stutter || METRIC.stutter,
          backgroundColor: sparkAreaFill(CHART.stutter || METRIC.stutter, 0.18, 0.02), fill: true, tension: 0,
          pointRadius: 0, borderWidth: 2.5, yAxisID: 'y', order: 1, spanGaps: true,
        },
        {
          label: 'CPU', data: cpuPts, borderColor: rgbaFromHex(METRIC.cpu, 0.58),
          backgroundColor: 'transparent', fill: false, tension: .22,
          pointRadius: 0, borderWidth: 1.4, yAxisID: 'y', order: 4, spanGaps: true,
        },
        {
          label: 'GPU', data: gpuPts, borderColor: rgbaFromHex(METRIC.gpu, 0.62),
          backgroundColor: 'transparent', fill: false, tension: .22,
          pointRadius: 0, borderWidth: 1.4, yAxisID: 'y', order: 3, spanGaps: true,
        },
        {
          label: 'Est. ms', data: estPts, borderColor: METRIC.thermal,
          backgroundColor: 'transparent', fill: false, tension: 0,
          pointRadius: 0, borderWidth: 1.5, borderDash: [4, 3], yAxisID: 'y1', order: 5,
        },
        {
          type: 'scatter', label: 'Hitch event', data: eventPoints,
          borderColor: METRIC.thermal, backgroundColor: METRIC.thermal,
          pointRadius: 5, pointStyle: 'triangle', yAxisID: 'y', showLine: false, order: 0,
        },
      ];
      if (!stutterChart.options.scales.y1) {
        stutterChart.options.scales.y1 = {
          position: 'right', min: 0, max: 120,
          ticks: { color: tickColor, font: { size: 9 }, callback: v => v + 'ms' },
          grid: { drawOnChartArea: false },
        };
      }
      const peakEst = Math.max(0, ...estPts.map(p => p.y).filter(v => v > 0), 0);
      stableAxisMax(stutterChart, 'y1', Math.max(40, peakEst), 40);
      lockPctAxis(stutterChart, 'y');
      if (!chartInteractActive) applyLiveTimeAxis(stutterChart, chartViewSec);
      if (structKey === stutterChart._pulseStructKey && stutterChart.data.datasets.length === newDatasets.length) {
        newDatasets.forEach((ds, i) => { stutterChart.data.datasets[i].data = ds.data; });
      } else {
        stutterChart._pulseStructKey = structKey;
        stutterChart.data.datasets = newDatasets;
      }
      if (!chartInteractActive && canvasVisible(stutterChart)) stutterChart.update('none');
      const stLabel = document.getElementById('stutterChartLabel');
      if (stLabel) stLabel.textContent = `Score · CPU/GPU · ${CHART_VIEW_LABELS[chartViewSec] || 'window'}`;
    }

    const STUTTER_SEV_WORD = { severe: 'Severe', moderate: 'Moderate', mild: 'Mild', none: 'Smooth' };

    function stutterSevClass(score) {
      if (score >= 70) return 'severe';
      if (score >= 50) return 'moderate';
      if (score >= 30) return 'mild';
      return 'ok';
    }

    function stutterAgoLabel(sec) {
      if (sec == null || sec < 0) return null;
      if (sec < 45) return `${Math.round(sec)}s ago`;
      if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
      return `${Math.round(sec / 3600)}h ago`;
    }

    function renderStutterMix(components, causes) {
      const barEl = document.getElementById('stutterMixBar');
      const legendEl = document.getElementById('stutterMixLegend');
      const hintEl = document.getElementById('stutterMixHint');
      if (!barEl || !legendEl) return;
      const segments = STUTTER_COMP_SPECS.map(s => ({
        id: s.id,
        weight: (components[s.id] ?? 0) * (STUTTER_MIX_WEIGHTS[s.id] ?? 0),
      })).filter(s => s.weight > 0.4);
      const total = segments.reduce((a, s) => a + s.weight, 0);
      if (!segments.length || total <= 0) {
        barEl.innerHTML = '<div class="stutter-mix-seg" style="flex-grow:1;opacity:.25"></div>';
        legendEl.innerHTML = '<span>No active drivers</span>';
        if (hintEl) hintEl.textContent = 'Idle';
        return;
      }
      const top = segments.reduce((a, b) => (b.weight > a.weight ? b : a), segments[0]);
      if (hintEl) hintEl.textContent = STUTTER_MIX_SHORT[top.id] || top.id;
      const structKey = segments.map(s => `${s.id}:${s.weight.toFixed(1)}`).join('|');
      if (structKey !== barEl.dataset.structKey) {
        barEl.dataset.structKey = structKey;
        barEl.innerHTML = segments.map(s =>
          `<div class="stutter-mix-seg ${s.id}" data-mix="${s.id}" style="flex-grow:0" title="${STUTTER_CAUSE_LABELS[s.id] || s.id}"></div>`
        ).join('');
      }
      barEl.querySelectorAll('[data-mix]').forEach(el => {
        const seg = segments.find(s => s.id === el.dataset.mix);
        el.style.flexGrow = seg ? (seg.weight / total).toFixed(4) : 0;
      });
      const active = causes?.length ? causes : segments.sort((a, b) => b.weight - a.weight).slice(0, 3).map(s => s.id);
      legendEl.innerHTML = active.map(id =>
        `<span><i class="${id}"></i>${STUTTER_MIX_SHORT[id] || id}</span>`
      ).join('');
    }

    function renderStutterTimeline(sess) {
      const trackEl = document.getElementById('stutterTimeline');
      const metaEl = document.getElementById('stutterTimelineMeta');
      const detailEl = document.getElementById('stutterSessionDetail');
      if (!trackEl) return;
      const slots = 30;
      const windowSec = 300;
      const last = rawHistory.at(-1)?.ts ?? 0;
      const t0 = last - windowSec;
      if (!trackEl.dataset.init) {
        trackEl.innerHTML = Array.from({ length: slots }, (_, i) =>
          `<div class="stutter-tick" data-slot="${i}" title="—"></div>`
        ).join('');
        trackEl.dataset.init = '1';
      }
      let events = 0;
      let peakScore = 0;
      let peakEst = 0;
      const slotSec = windowSec / slots;
      for (let i = 0; i < slots; i++) {
        const start = t0 + i * slotSec;
        const slice = rawHistory.filter(h => h.ts >= start && h.ts < start + slotSec);
        const tick = trackEl.querySelector(`[data-slot="${i}"]`);
        if (!tick) continue;
        if (!slice.length) {
          tick.style.height = '16%';
          tick.className = 'stutter-tick';
          tick.title = `${fmtTime(start)} · no data`;
          continue;
        }
        const maxScore = Math.max(...slice.map(h => h.stutter?.score ?? 0));
        const maxEst = Math.max(...slice.map(h => h.stutter?.est_ms ?? 0));
        const hadEvent = slice.some(h => h.stutter?.event);
        if (hadEvent) events += 1;
        peakScore = Math.max(peakScore, maxScore);
        peakEst = Math.max(peakEst, maxEst);
        const sev = stutterSevClass(maxScore);
        tick.className = `stutter-tick${hadEvent ? ' event' : ''}${maxScore >= 30 ? ` sev-${sev === 'ok' ? 'mild' : sev}` : ''}`;
        tick.style.height = `${Math.max(16, Math.min(100, 14 + maxScore * 0.86))}%`;
        const tipParts = [`${fmtTime(start)}`, `score ${Math.round(maxScore)}`];
        if (maxEst > 0) tipParts.push(`~${maxEst.toFixed(1)}ms`);
        if (hadEvent) tipParts.push('hitch');
        tick.title = tipParts.join(' · ');
      }
      const windowSlice = rawHistory.filter(h => h.ts >= t0);
      const lastEvent = [...windowSlice].reverse().find(h => h.stutter?.event);
      const lastAgo = lastEvent ? stutterAgoLabel(last - lastEvent.ts) : null;
      if (metaEl) {
        if (!events) metaEl.textContent = 'No hitches';
        else {
          const parts = [`${events} hitch${events !== 1 ? 'es' : ''}`, `peak ${Math.round(peakScore)}`];
          if (peakEst > 0) parts.push(`~${peakEst.toFixed(0)}ms`);
          if (lastAgo) parts.push(lastAgo);
          metaEl.textContent = parts.join(' · ');
        }
      }
      if (detailEl && sess) {
        const avg = sess.score_avg ?? 0;
        const p95 = sess.score_p95 ?? 0;
        const rate = sess.hitch_rate_per_min ?? 0;
        detailEl.textContent = `avg ${avg} · p95 ${p95} · ${rate}/min`;
      }
    }

    function renderStutterViz(l) {
      const st = l.stutter || {};
      const sess = st.session || {};
      const sev = st.severity || 'none';
      const score = Number(st.score);
      const scoreDisplay = Number.isFinite(score) ? Math.round(smoothDisplayPct('stutter-score', score)) : null;
      const smoothDisplayVal = scoreDisplay != null ? Math.max(0, 100 - scoreDisplay) : null;

      const scoreEl = document.getElementById('stutterScoreVal');
      scoreEl.textContent = scoreDisplay ?? '—';
      scoreEl.className = `score ${sev === 'none' ? 'ok' : sev}`;

      const gaugeEl = document.getElementById('stutterGauge');
      if (gaugeEl) {
        gaugeEl.style.setProperty('--stutter-score', scoreDisplay ?? 0);
        gaugeEl.style.setProperty('--stutter-color', STUTTER_GAUGE_COLORS[sev] || STUTTER_GAUGE_COLORS.none);
        gaugeEl.classList.toggle('event-active', !!st.event);
      }
      const smoothEl = document.getElementById('stutterSmoothVal');
      if (smoothEl) smoothEl.textContent = smoothDisplayVal != null ? `${smoothDisplayVal}% smooth` : '—% smooth';

      const statusEl = document.getElementById('stutterStatus');
      if (statusEl) {
        const word = STUTTER_SEV_WORD[sev] || 'Smooth';
        if (st.event) statusEl.textContent = `${word} · live hitch ~${st.est_ms ?? '—'}ms`;
        else if (sess.events) statusEl.textContent = `${word} · ${sess.events} hitch${sess.events !== 1 ? 'es' : ''} in 5m`;
        else statusEl.textContent = `${word} · clear for 5m`;
        statusEl.className = `stutter-status ${sev === 'none' ? 'ok' : sev}`;
      }

      const estEl = document.getElementById('stutterEstMs');
      estEl.textContent = st.est_ms != null ? `${st.est_ms}ms` : '—';
      estEl.className = `v ${sev === 'none' ? 'ok' : sev}`;
      const estSub = document.getElementById('stutterEstSub');
      if (estSub) estSub.textContent = st.event ? 'live hitch' : 'est.';
      const pctEl = document.getElementById('stutter1Pct');
      pctEl.textContent = sess.hitch_ms_1pct != null ? `${sess.hitch_ms_1pct}ms` : '—';
      pctEl.className = `v ${(sess.hitch_ms_1pct || 0) >= 50 ? 'severe' : (sess.hitch_ms_1pct || 0) >= 28 ? 'moderate' : 'ok'}`;
      const pctSub = document.getElementById('stutter1PctSub');
      if (pctSub) {
        const smoothSess = sess.smoothness_session;
        pctSub.textContent = smoothSess != null ? `${smoothSess}% smooth` : 'session';
      }
      const eventsEl = document.getElementById('stutterEvents');
      eventsEl.textContent = sess.events ?? 0;
      eventsEl.className = `v ${(sess.events || 0) >= 8 ? 'severe' : (sess.events || 0) >= 3 ? 'moderate' : 'ok'}`;
      const eventsSub = document.getElementById('stutterEventsSub');
      if (eventsSub) eventsSub.textContent = `${sess.hitch_rate_per_min ?? 0}/min rate`;

      ensureMetricList('stutterComponents', STUTTER_COMP_SPECS);
      syncMetricHwTags('stutterComponents', STUTTER_COMP_SPECS);
      const comp = st.components || {};
      const dram = l.bandwidth?.memory || {};
      STUTTER_COMP_SPECS.forEach(s => {
        const v = comp[s.id] ?? 0;
        let sub = '';
        if (s.id === 'major_faults') sub = `${dram.pgmajfault_per_s ?? 0}/s maj`;
        else if (s.id === 'mem_stall') sub = `Wait ${dram.psi_avg10 ?? 0}%`;
        else if (s.id === 'io_stall') sub = `I/O ${dram.io_wait_pct ?? dram.psi_io_avg10 ?? 0}%`;
        else if (s.id === 'swap') sub = `↓${dram.swap_in_kbps ?? 0} ↑${dram.swap_out_kbps ?? 0}`;
        else if (s.id === 'disk_spike') sub = `W ${l.disk?.write_mbps ?? 0} MB/s`;
        setMetricBar('stutterComponents', s.id, v, `${Math.round(v)}`, sub, '', s.cls);
      });

      renderStutterChart();
      renderStutterMix(comp, st.causes);
      renderStutterTimeline(sess);

      const causes = st.causes || [];
      const causesEl = document.getElementById('stutterCauses');
      const causesKey = causes.join(',') || 'none';
      if (causesEl.dataset.key !== causesKey) {
        causesEl.dataset.key = causesKey;
        causesEl.innerHTML = causes.length
          ? causes.map(c => `<span class="stutter-cause">${STUTTER_CAUSE_LABELS[c] || c}</span>`).join('')
          : '<span class="stutter-cause placeholder">No active hitch drivers</span>';
      }

      const gt = l.game_totals;
      if (gt?.running && (st.event || (st.score || 0) >= 35)) {
        const hitchTxt =
          `${gt.primary_name || gt.game_name} · hitch ~${st.est_ms}ms · ${sess.events ?? 0} in 5m`;
        const ctxEl = document.getElementById('sumGameContext');
        if (ctxEl) ctxEl.textContent = hitchTxt;
        else document.getElementById('sumGameSub').textContent = hitchTxt;
      }
    }

    function renderCoreStrip(cores) {
      const el = document.getElementById('coreStrip');
      if (!el || !el.offsetParent) return;
      if (!el.dataset.init) {
        el.innerHTML = cores.map(c => `
          <div class="core-strip-cell" data-core="${c.id}" title="Core ${c.id}">
            <div class="core-strip-fill"></div>
          </div>`).join('');
        el.dataset.init = '1';
      }
      cores.forEach(c => {
        const f = el.querySelector(`[data-core="${c.id}"] .core-strip-fill`);
        if (f) setMeterHeight(f, c.pct, 4);
      });
    }

    const GPU_ENGINE_LABELS = {
      gfx: 'Shaders',
      vram: 'Memory bus',
      mm: 'Video',
    };
    const GPU_ENGINE_HINTS = {
      gfx: 'Graphics and shader cores',
      vram: 'VRAM memory controller — how busy the GDDR bus is',
      mm: 'Video encode and decode block',
    };

    function gpuEngineLabel(id, fallback) {
      return GPU_ENGINE_LABELS[id] || fallback || id;
    }

    function renderGpuEngineStrip(engines) {
      const el = document.getElementById('gpuEngineStrip');
      if (!el || !el.offsetParent) return;
      if (!el.dataset.init) {
        el.innerHTML = engines.map(e => `
          <div class="gpu-engine-cell" data-engine="${e.id}">
            <div class="core-strip-cell" title="${GPU_ENGINE_HINTS[e.id] || gpuEngineLabel(e.id, e.label)}">
              <div class="core-strip-fill"></div>
            </div>
            <div class="gpu-engine-pct" data-engine-pct="${e.id}">—</div>
            <div class="gpu-engine-label">${gpuEngineLabel(e.id, e.label)}</div>
          </div>`).join('');
        el.dataset.init = '1';
      }
      engines.forEach(e => {
        const f = el.querySelector(`[data-engine="${e.id}"] .core-strip-fill`);
        const pct = e.pct ?? 0;
        if (f) setMeterHeight(f, pct, 4);
        const pctEl = el.querySelector(`[data-engine-pct="${e.id}"]`);
        if (pctEl) pctEl.textContent = e.pct != null ? `${smoothDisplayPct(`gpu-eng-${e.id}`, pct)}%` : '—';
      });
    }

    const INDEX_RANK_SPECS = [
      { id: 'cpu', part: 'CPU', hw: 'cpu', icon: 'cpu', cls: 'cpu' },
      { id: 'gpu', part: 'GPU', hw: 'gpu', icon: 'gpu', cls: 'gpu' },
      { id: 'ram', part: 'RAM', hw: 'memory', icon: 'ram', cls: 'mem' },
    ];
    const INDEX_MIX_SPECS = [
      { id: 'cpu', label: 'CPU', weight: 0.35 },
      { id: 'gpu', label: 'GPU', weight: 0.45 },
      { id: 'mem', label: 'RAM', weight: 0.20 },
    ];
    const INDEX_GAUGE_COLORS = {
      severe: 'var(--m-stutter)',
      hot: 'var(--m-gpu)',
      warn: 'var(--m-cpu)',
      ok: 'var(--m-mem)',
    };

    function compositeVs(c, key) {
      const vals = [c.cpu, c.gpu, c.memory].map(p => p?.[key]).filter(v => v != null && !isNaN(v));
      if (!vals.length) return null;
      return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
    }

    function leagueLoadStatus(pct) {
      if (pct >= 86) return { word: 'Maxed out', cls: 'severe' };
      if (pct >= 71) return { word: 'Pushed hard', cls: 'hot' };
      if (pct >= 46) return { word: 'Working hard', cls: 'warn' };
      if (pct >= 18) return { word: 'Light load', cls: 'ok' };
      return { word: 'Mostly idle', cls: 'ok' };
    }

    function leagueHeadroomPct(loadPct, partHeadroom) {
      if (partHeadroom != null && !isNaN(partHeadroom)) return Math.round(partHeadroom);
      return Math.max(0, Math.round(100 - loadPct));
    }

    function indexLoadSev(pct) {
      const s = leagueLoadStatus(pct);
      const cls = s.cls === 'hot' ? 'hot' : s.cls;
      return { ...s, cls: cls === 'severe' ? 'severe' : cls };
    }

    function indexHistoryPick(h) {
      const c = h.comparison;
      if (!c) return null;
      const sole = soleHwFocus();
      if (sole === 'cpu') return c.cpu?.live_pct ?? null;
      if (sole === 'gpu') return c.gpu?.live_pct ?? null;
      if (sole === 'memory') return c.memory?.live_pressure_pct ?? null;
      // Multi-select: average live loads of selected parts when possible
      if (anyHwFocus()) {
        const vals = [];
        if (hwFocusHas('cpu') && c.cpu?.live_pct != null) vals.push(c.cpu.live_pct);
        if (hwFocusHas('gpu') && c.gpu?.live_pct != null) vals.push(c.gpu.live_pct);
        if (hwFocusHas('memory') && c.memory?.live_pressure_pct != null) vals.push(c.memory.live_pressure_pct);
        if (vals.length) return vals.reduce((a, b) => a + b, 0) / vals.length;
      }
      return c.session_index ?? null;
    }

    function renderIndexChart() {
      if (!canvasVisible(indexChart)) return;
      sparkRingEnsure();
      const focusKey = hwFocusKey();
      const structKey = `index|hitch|${focusKey}|${chartViewSec}|${chartsPaused}|${chartZoomed}`;
      const cap = Math.max(160, Math.min(560, Math.round((indexChart.width || 640) * 0.65)));
      // Default: append-only sparkRing. HW focus picks live load from history
      // through the same epoch buckets as Snapshot (not 1 Hz index-stride).
      const indexSrc = anyHwFocus()
        ? (() => {
            const ts = [];
            const vs = [];
            for (const h of rawHistory) {
              if (h?.ts == null || !Number.isFinite(+h.ts)) continue;
              ts.push(+h.ts);
              vs.push(indexHistoryPick(h));
            }
            return xySeriesView(ts, vs, chartViewSec, cap);
          })()
        : xySeriesView(sparkRing.ts, sparkRing.index, chartViewSec, cap);
      const headPts = indexSrc.map(p => ({
        x: p.x,
        y: p.y == null || !Number.isFinite(+p.y) ? null : Math.max(0, 100 - p.y),
      }));
      const hitchPts = xySeriesView(sparkRing.ts, sparkRing.hitch, chartViewSec, cap, 'max');
      const sole = soleHwFocus();
      const mainLabel = anyHwFocus()
        ? `${hwFocusLabelText()} load`
        : 'Pulse Index';
      const mainColor = sole === 'cpu' ? CHART.cpu
        : sole === 'gpu' ? CHART.gpu
        : sole === 'memory' ? CHART.ram
        : anyHwFocus() ? METRIC.league
        : METRIC.league;
      const newDatasets = [
        {
          label: mainLabel, data: indexSrc, borderColor: mainColor,
          backgroundColor: sparkAreaFill(mainColor, 0.2, 0.02), fill: true, tension: 0.08,
          pointRadius: 0, borderWidth: 2.5, yAxisID: 'y', order: 2, spanGaps: true,
        },
        {
          label: 'Headroom', data: headPts, borderColor: CHART.headroom || METRIC.cpu,
          backgroundColor: 'transparent', fill: false, tension: 0.08,
          pointRadius: 0, borderWidth: 1.5, borderDash: [4, 3], yAxisID: 'y', order: 3, spanGaps: true,
        },
        {
          label: 'Hitch', data: hitchPts, borderColor: METRIC.stutter,
          backgroundColor: 'transparent', fill: false, tension: 0,
          pointRadius: 0, borderWidth: 1.65, yAxisID: 'y', order: 1, spanGaps: true,
        },
      ];
      lockPctAxis(indexChart, 'y');
      if (!chartInteractActive) applyLiveTimeAxis(indexChart, chartViewSec);
      if (structKey === indexChart._pulseStructKey && indexChart.data.datasets.length === newDatasets.length) {
        newDatasets.forEach((ds, i) => {
          indexChart.data.datasets[i].data = ds.data;
          indexChart.data.datasets[i].label = ds.label;
          indexChart.data.datasets[i].borderColor = ds.borderColor;
          indexChart.data.datasets[i].backgroundColor = ds.backgroundColor;
        });
      } else {
        indexChart._pulseStructKey = structKey;
        indexChart.data.datasets = newDatasets;
      }
      if (!chartInteractActive) indexChart.update('none');
      const idxLabel = document.getElementById('indexChartLabel');
      if (idxLabel) {
        const viewLbl = CHART_VIEW_LABELS[chartViewSec] || 'window';
        idxLabel.textContent = anyHwFocus()
          ? `${hwFocusLabelText()} · hitch · ${viewLbl}`
          : `Index · hitch · ${viewLbl}`;
      }
    }

    function indexPartShortName(spec, part) {
      if (!part) return '—';
      if (spec.hw === 'memory') return part.kit || part.name || '—';
      return part.name || '—';
    }

    function indexRankFoot(spec, part) {
      if (!part) return '—';
      const vs = part.vs_enthusiast_pct != null ? `vs high-end ${vsFmt(part.vs_enthusiast_pct)}` : null;
      if (spec.id === 'cpu') {
        const head = part.headroom_pct != null ? `${Math.round(part.headroom_pct)}% headroom` : null;
        return [vs, head].filter(Boolean).join(' · ') || '—';
      }
      if (spec.id === 'gpu') {
        const vram = part.vram_gbps_live != null ? `${part.vram_gbps_live} GB/s VRAM` : null;
        const bw = part.vram_bw_busy_pct != null ? `${part.vram_bw_busy_pct}% BW` : null;
        return [vs, vram, bw].filter(Boolean).join(' · ') || '—';
      }
      const gbps = part.live_gbps_est != null ? `${part.live_gbps_est} GB/s est.` : null;
      const peak = part.peak_gbps != null ? `${part.peak_gbps} peak` : null;
      return [vs, gbps, peak].filter(Boolean).join(' · ') || '—';
    }

    function toggleIndexRankCard(card) {
      const list = card?.closest('.index-rank-list');
      if (!list || !card) return;
      const opening = !card.classList.contains('is-open');
      list.querySelectorAll('.index-rank-card.is-open').forEach(el => {
        el.classList.remove('is-open');
        el.setAttribute('aria-expanded', 'false');
      });
      if (opening) {
        card.classList.add('is-open');
        card.setAttribute('aria-expanded', 'true');
        list.dataset.openId = card.dataset.rankId || '';
      } else {
        delete list.dataset.openId;
      }
    }

    function bindIndexRankList(listEl) {
      if (!listEl || listEl.dataset.bound === '1') return;
      listEl.dataset.bound = '1';
      listEl.addEventListener('click', e => {
        const card = e.target.closest('.index-rank-card');
        if (!card || !listEl.contains(card)) return;
        toggleIndexRankCard(card);
      });
      listEl.addEventListener('keydown', e => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const card = e.target.closest('.index-rank-card');
        if (!card || !listEl.contains(card)) return;
        e.preventDefault();
        toggleIndexRankCard(card);
      });
    }

    function renderIndexRankings(c) {
      const listEl = document.getElementById('indexRankList');
      if (!listEl || !c) return;
      bindIndexRankList(listEl);

      const structKey = INDEX_RANK_SPECS.map(s => {
        const p = s.hw === 'memory' ? c.memory : c[s.hw];
        return `${s.id}:${p?.tier_rank}:${p?.tier_score}:${p?.name}`;
      }).join('|');

      if (listEl.dataset.structKey !== structKey) {
        const openId = listEl.dataset.openId || '';
        listEl.dataset.structKey = structKey;
        listEl.innerHTML = INDEX_RANK_SPECS.map(spec => `
          <div class="index-rank-card" data-rank-id="${spec.id}" data-hw="${spec.hw}"
            role="button" tabindex="0" aria-expanded="false"
            title="Show ${esc(spec.part)} ranking detail">
            <div class="index-rank-head">
              <span class="part">
                <span class="hw-icon-box ${spec.cls === 'mem' ? 'mem' : spec.cls}" data-rank-icon></span>
                <span class="index-rank-title">
                  <span class="index-rank-kind">${spec.part}</span>
                  <span class="index-rank-name" data-rank-name>—</span>
                </span>
              </span>
              <span class="index-rank-glance">
                <span class="index-rank-live-mini" data-live-val>—</span>
                <span data-rank-badge></span>
              </span>
            </div>
            <div class="index-rank-detail">
              <div class="index-rank-bars">
                <div class="index-rank-bar-row">
                  <span class="lbl">Class</span>
                  <div class="rank-bar tier"><span data-tier-fill style="width:0%"></span></div>
                  <span class="val" data-tier-val>—</span>
                </div>
                <div class="index-rank-bar-row">
                  <span class="lbl">Live</span>
                  <div class="rank-bar live ${spec.cls}"><span data-live-fill style="width:0%"></span></div>
                  <span class="val" data-live-val>—</span>
                </div>
              </div>
              <div class="index-rank-foot" data-rank-foot>—</div>
            </div>
          </div>`).join('');
        INDEX_RANK_SPECS.forEach(spec => {
          const card = listEl.querySelector(`[data-rank-id="${spec.id}"]`);
          const iconEl = card?.querySelector('[data-rank-icon]');
          if (iconEl) iconEl.innerHTML = hwIcon(spec.icon);
        });
        if (openId) {
          const keep = listEl.querySelector(`[data-rank-id="${openId}"]`);
          if (keep) {
            keep.classList.add('is-open');
            keep.setAttribute('aria-expanded', 'true');
          }
        }
      }

      INDEX_RANK_SPECS.forEach(spec => {
        const part = spec.hw === 'memory' ? c.memory : c[spec.hw];
        const card = listEl.querySelector(`[data-rank-id="${spec.id}"]`);
        if (!card || !part) return;
        const livePct = smoothDisplayPct(
          `index-rank-live-${spec.id}`,
          spec.hw === 'memory' ? part.live_pressure_pct : part.live_pct,
        );
        const tierScore = part.tier_score ?? 0;
        const badgeSlot = card.querySelector('[data-rank-badge]');
        if (badgeSlot) setTierBadge(badgeSlot, part.tier_rank, false);
        const nameEl = card.querySelector('[data-rank-name]');
        if (nameEl) nameEl.textContent = indexPartShortName(spec, part);
        setMeterWidth(card.querySelector('[data-tier-fill]'), tierScore);
        setMeterWidth(card.querySelector('[data-live-fill]'), livePct);
        const tierVal = card.querySelector('[data-tier-val]');
        if (tierVal) tierVal.textContent = Math.round(tierScore);
        card.querySelectorAll('[data-live-val]').forEach(el => {
          el.textContent = `${Math.round(livePct)}%`;
        });
        const footEl = card.querySelector('[data-rank-foot]');
        if (footEl) footEl.innerHTML = indexRankFoot(spec, part);
      });
    }

    function renderIndexMix(c) {
      const barEl = document.getElementById('indexMixBar');
      const legendEl = document.getElementById('indexMixLegend');
      const hintEl = document.getElementById('indexMixHint');
      if (!barEl || !legendEl || !c) return;
      const loads = {
        cpu: c.cpu?.live_pct ?? 0,
        gpu: c.gpu?.live_pct ?? 0,
        mem: c.memory?.live_pressure_pct ?? 0,
      };
      const weighted = INDEX_MIX_SPECS.map(s => ({
        ...s,
        raw: (loads[s.id] ?? 0) * s.weight,
      }));
      const total = weighted.reduce((a, s) => a + s.raw, 0) || 1;
      const segments = weighted.map(s => ({
        ...s,
        share: (s.raw / total) * 100,
      })).filter(s => s.share >= 1);
      const key = segments.map(s => `${s.id}:${Math.round(s.share)}`).join('|') || 'empty';
      if (barEl.dataset.key !== key) {
        barEl.dataset.key = key;
        barEl.innerHTML = segments.length
          ? segments.map(s => `<span class="stutter-mix-seg index-mix-seg ${s.id}" style="flex-grow:${s.share.toFixed(2)}"></span>`).join('')
          : '<span class="stutter-mix-seg index-mix-seg cpu" style="flex-grow:1;opacity:.25"></span>';
        legendEl.innerHTML = segments.length
          ? segments.map(s => `<span><i class="${s.id}"></i>${s.label} ${Math.round(loads[s.id])}%</span>`).join('')
          : '<span>No load yet</span>';
      }
      if (hintEl) {
        const top = [...segments].sort((a, b) => b.share - a.share)[0];
        hintEl.textContent = top ? `${top.label} leading` : '—';
      }
    }

    function renderIndexTimeline(sessionIdx) {
      const trackEl = document.getElementById('indexTimeline');
      const metaEl = document.getElementById('indexTimelineMeta');
      const detailEl = document.getElementById('indexSessionDetail');
      if (!trackEl) return;
      const last = rawHistory.at(-1)?.ts ?? 0;
      const windowSlice = rawHistory.filter(h => h.ts >= last - 300);
      const slotSec = 300 / 24;
      const t0 = last - 300;
      const buckets = [];
      for (let i = 0; i < 24; i++) {
        const start = t0 + i * slotSec;
        const slice = windowSlice.filter(h => h.ts >= start && h.ts < start + slotSec);
        const vals = slice.map(indexHistoryPick).filter(v => v != null && !isNaN(v));
        const v = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
        buckets.push(v);
      }
      const peak = Math.max(8, ...buckets);
      const key = buckets.map(v => Math.round(v)).join(',');
      if (trackEl.dataset.key !== key) {
        trackEl.dataset.key = key;
        trackEl.innerHTML = buckets.map(v => {
          const h = Math.max(12, Math.round((v / peak) * 100));
          const sev = indexLoadSev(v).cls;
          const sevCls = sev === 'severe' || sev === 'hot' ? 'sev-hot' : sev === 'warn' ? 'sev-warn' : 'sev-ok';
          return `<span class="stutter-tick index-tick ${sevCls}" style="height:${h}%" title="${Math.round(v)}/100"></span>`;
        }).join('');
      }
      if (metaEl) metaEl.textContent = `${windowSlice.length} samples`;
      if (detailEl) {
        const status = indexLoadSev(sessionIdx);
        detailEl.textContent = `${status.word} · index ${Math.round(sessionIdx)}`;
      }
    }

    function renderPulseIndexViz(c) {
      const block = document.getElementById('pulseIndexBlock');
      const emptyEl = document.getElementById('indexEmpty');
      const layoutEl = block?.querySelector('.index-layout');
      if (!block) return;

      if (!c) {
        if (emptyEl) emptyEl.hidden = false;
        if (layoutEl) layoutEl.style.display = 'none';
        block.classList.add('noc-hw-empty');
        return;
      }
      if (emptyEl) emptyEl.hidden = true;
      if (layoutEl) layoutEl.style.display = '';
      block.classList.remove('noc-hw-empty');

      const sessionIdx = smoothDisplayPct('session-index', c.session_index);
      const vsAvg = compositeVs(c, 'vs_avg_pct');
      const vsEnth = compositeVs(c, 'vs_enthusiast_pct');
      let gaugePct = sessionIdx;
      let headroom = leagueHeadroomPct(sessionIdx);
      let status = indexLoadSev(sessionIdx);
      let vsEnthVal = vsEnth;
      const soleIdx = soleHwFocus();
      let statusExtra = INDEX_STATUS_SUBS[soleIdx || 'default'] || INDEX_STATUS_SUBS.default;
      if (anyHwFocus() && !soleIdx) statusExtra = `${hwFocusLabelText()} focus`;

      if (soleIdx && c[soleIdx === 'memory' ? 'memory' : soleIdx]) {
        const part = c[soleIdx === 'memory' ? 'memory' : soleIdx];
        const live = soleIdx === 'memory' ? part.live_pressure_pct : part.live_pct;
        gaugePct = smoothDisplayPct(`index-head-${soleIdx}`, live ?? 0);
        headroom = leagueHeadroomPct(gaugePct, soleIdx === 'cpu' ? part.headroom_pct : null);
        status = indexLoadSev(gaugePct);
        vsEnthVal = part.vs_enthusiast_pct;
        statusExtra = INDEX_STATUS_SUBS[soleIdx];
      }

      setTierBadge(document.getElementById('indexBuildBadge'), c.composite_rank);
      const buildMeta = document.getElementById('indexBuildMeta');
      if (buildMeta) {
        const bits = [
          c.composite_tier != null ? `Composite ${Math.round(c.composite_tier)}/100` : null,
          vsAvg != null ? `vs typical ${vsFmt(vsAvg)}` : null,
          vsEnth != null ? `vs high-end ${vsFmt(vsEnth)}` : null,
        ].filter(Boolean);
        buildMeta.innerHTML = bits.join(' · ') || '—';
      }

      const scoreEl = document.getElementById('indexScoreVal');
      if (scoreEl) {
        scoreEl.textContent = Math.round(gaugePct);
        scoreEl.className = `score ${status.cls}`;
      }
      const gaugeEl = document.getElementById('indexGauge');
      if (gaugeEl) {
        gaugeEl.style.setProperty('--index-score', gaugePct);
        gaugeEl.style.setProperty('--index-color', INDEX_GAUGE_COLORS[status.cls] || INDEX_GAUGE_COLORS.ok);
        gaugeEl.classList.toggle('pushed-hard', gaugePct >= 71);
      }
      const subEl = document.getElementById('indexScoreSub');
      if (subEl) subEl.textContent = anyHwFocus() ? `${hwFocusLabelText()} live` : 'session index';

      const chartLabel = document.getElementById('indexChartLabel');
      if (chartLabel) {
        const viewLbl = CHART_VIEW_LABELS[chartViewSec] || 'window';
        chartLabel.textContent = anyHwFocus()
          ? `${hwFocusLabelText()} · hitch · ${viewLbl}`
          : `Index · hitch · ${viewLbl}`;
      }

      const statusEl = document.getElementById('indexStatus');
      if (statusEl) {
        const refBits = [
          vsAvg != null ? `vs typical ${vsFmt(vsAvg)}` : null,
          vsEnthVal != null ? `vs high-end ${vsFmt(vsEnthVal)}` : null,
        ].filter(Boolean);
        statusEl.innerHTML = [status.word, statusExtra, ...refBits].filter(Boolean).join(' · ');
        statusEl.className = `index-status ${status.cls}`;
      }

      const headEl = document.getElementById('indexHeadroom');
      if (headEl) {
        headEl.textContent = `${headroom}%`;
        headEl.className = `v ${headroom <= 15 ? 'severe' : headroom <= 30 ? 'warn' : 'ok'}`;
      }
      const headSub = document.getElementById('indexHeadroomSub');
      if (headSub) headSub.textContent = gaugePct >= 86 ? 'near max' : 'spare';

      const sessEl = document.getElementById('indexSessionKpi');
      if (sessEl) {
        sessEl.textContent = `${Math.round(sessionIdx)}/100`;
        sessEl.className = `v ${status.cls}`;
      }
      const sessSub = document.getElementById('indexSessionSub');
      if (sessSub) sessSub.textContent = anyHwFocus() ? `${hwFocusLabelText()} focus` : 'session index';

      const avgEl = document.getElementById('indexVsAvg');
      if (avgEl) {
        avgEl.innerHTML = vsAvg != null ? vsFmt(vsAvg) : '—';
        avgEl.className = `v ${vsAvg > 5 ? 'ok' : vsAvg < -5 ? 'severe' : ''}`;
      }
      const avgSub = document.getElementById('indexVsAvgSub');
      if (avgSub) avgSub.textContent = 'typical PC';

      renderIndexRankings(c);

      renderIndexChart();
      renderIndexMix(c);
      renderIndexTimeline(sessionIdx);
    }

    function renderQuickGlance(l) {
      const g = l.gpu?.discrete || {};
      const cpu = l.cpu || {};
      const gpuPower = g.power_w != null ? Math.round(g.power_w) : null;
      const cpuPower = cpu.power_w != null ? Math.round(cpu.power_w) : null;
      const fan = g.fan_rpm != null ? Math.round(g.fan_rpm) : null;
      const mhz = g.gfx_mhz != null ? Math.round(g.gfx_mhz) : null;
      const gpuCap = hwScales.gpu_power_max_w || 250;
      const cpuCap = hwScales.cpu_power_max_w || 125;
      const gpuPct = Math.min(100, ((gpuPower || 0) / gpuCap) * 100);
      const cpuPct = Math.min(100, ((cpuPower || 0) / cpuCap) * 100);
      const fanPct = Math.min(100, ((fan || 0) / 2800) * 100);
      const gpuText = gpuPower != null
        ? (mhz != null ? `${gpuPower}W` : `${gpuPower}W`)
        : '—';
      const cpuText = cpuPower != null ? `${cpuPower}W` : 'n/a';
      const cpuPowerEl = document.querySelector('#glanceGrid [data-dial="cpu-power"]');
      if (cpuPowerEl) {
        cpuPowerEl.title = cpuPower != null
          ? 'CPU package power (RAPL)'
          : 'CPU watts need RAPL udev — energy_uj is root-only. sudo cp deploy/99-rapl-readable.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger -s powercap';
        const kEl = cpuPowerEl.querySelector('.pulse-dial-k');
        if (kEl) kEl.textContent = cpuPower != null ? 'CPU' : 'CPU udev';
      }
      setPulseDial('glanceGrid', 'cpu-power', cpuPower != null ? cpuPct : 0, cpuText, {
        hot: cpuPct >= 92,
        warn: cpuPct >= 80 && cpuPct < 92,
        missing: cpuPower == null,
      });
      setPulseDial('glanceGrid', 'gpu-power', gpuPower != null ? gpuPct : 0, gpuText, {
        hot: gpuPct >= 92,
      });
      setPulseDial('tempMeters', 'fan', fanPct, fan != null ? `${fan}` : '—', { hot: fanPct >= 90 });
      const hitch = Number(l.stutter?.score);
      const hitchOk = Number.isFinite(hitch);
      setPulseDial('glanceGrid', 'hitch', hitchOk ? hitch : 0, hitchOk ? `${Math.round(hitch)}` : '—', {
        hot: hitchOk && hitch >= 50,
        warn: hitchOk && hitch >= 30 && hitch < 50,
      });
    }

    function shortDriveLabel(sensor) {
      const model = sensor.drive?.model || sensor.label || '';
      const brand = sensor.drive?.brand || '';
      if (/980\s*PRO/i.test(model)) return 'Samsung 980 PRO';
      if (/990\s*PRO/i.test(model)) return 'Samsung 990 PRO';
      if (/KXG60/i.test(model)) return 'Kioxia NVMe';
      if (/SN\d+/i.test(model)) {
        const sn = model.match(/SN\d+\w*/i)?.[0] || model;
        return `${brand || 'Samsung'} ${sn}`.trim().slice(0, 22);
      }
      const trimmed = model.replace(new RegExp(`^${brand}\\s*`, 'i'), '').trim();
      const friendly = (trimmed || model).slice(0, 22);
      if (brand && !new RegExp(brand, 'i').test(friendly)) return `${brand} ${friendly}`.trim().slice(0, 24);
      return friendly;
    }

    function buildHwStatusGroups(sensors) {
      // Default Temps row: CPU + GPU + VRAM + disks only (not NIC/CCD/iGPU noise).
      const byId = {};
      (sensors || []).forEach(s => { byId[s.id] = s; });
      const temps = [];

      const cpu = byId.cpu_pkg || ['ccd1', 'ccd2']
        .map(id => byId[id])
        .filter(Boolean)
        .sort((a, b) => (b.value ?? 0) - (a.value ?? 0))[0];
      if (cpu) {
        temps.push({
          id: cpu.id, sensor: cpu, display: 'CPU', icon: 'cpu', iconCls: 'cpu',
          tooltip: cpu.label, isGpuJunc: false, hw: 'cpu',
        });
      }

      const gpu = byId.gpu_junc || byId.gpu_edge;
      if (gpu) {
        temps.push({
          id: gpu.id, sensor: gpu, display: 'GPU', icon: 'gpu', iconCls: 'gpu',
          tooltip: gpu.label, isGpuJunc: gpu.id === 'gpu_junc', hw: 'gpu',
        });
      }
      if (byId.gpu_memt) {
        temps.push({
          id: byId.gpu_memt.id, sensor: byId.gpu_memt, display: 'VRAM', icon: 'gpu', iconCls: 'gpu',
          tooltip: byId.gpu_memt.label, isGpuJunc: false, hw: 'gpu',
        });
      }

      (sensors || []).filter(s => s.kind === 'temp' && s.id?.startsWith('nvme_')).forEach(s => {
        temps.push({
          id: s.id, sensor: s, display: shortDriveLabel(s), icon: 'storage', iconCls: 'storage',
          tooltip: s.label, isGpuJunc: false, hw: 'storage',
        });
      });

      return { temps, storage: [], network: [] };
    }

    function hwStatusCardAccent(item) {
      if (item.id?.startsWith('io_')) return 'accent-io';
      if (item.id?.startsWith('net_') || item.id === 'network_combined'
          || item.id?.startsWith('nic_') || item.id === 'wifi') return 'accent-net';
      if (item.hw === 'storage' || item.id?.startsWith('nvme_')) return 'accent-storage';
      if (item.iconCls === 'gpu') return 'accent-gpu';
      if (item.iconCls === 'cpu') return 'accent-cpu';
      return 'accent-storage';
    }

    function hwStatusCardHtml(item) {
      const hw = item.hw ?? (item.hw === '' ? '' : sensorHwFocus(item.sensor));
      const hwAttr = hw ? ` data-hw="${hw}"` : ' data-hw-keep';
      const accent = hwStatusCardAccent(item);
      return `<div class="hw-status-card ${accent}" data-sid="${esc(item.id)}"${hwAttr} title="${esc(item.tooltip || '')}">
        <span class="hw-icon-box ${item.iconCls}">${hwIcon(item.icon)}</span>
        <div class="hw-status-card-body">
          <span class="hw-status-card-name">${esc(item.display)}</span>
          <span class="hw-status-card-val" data-sval>—</span>
        </div>
      </div>`;
    }

    function renderHwStatusRow(label, items, opts = {}) {
      const { secondary = false } = opts;
      if (!items.length) return '';
      return `<div class="hw-status-row${secondary ? ' hw-status-row-secondary' : ''}">
        <span class="hw-status-label">${esc(label)}</span>
        <div class="hw-status-cards">${items.map(hwStatusCardHtml).join('')}</div>
      </div>`;
    }

    function diskIoWaitPct(l) {
      const m = l?.bandwidth?.memory || {};
      return m.io_wait_pct ?? m.psi_io_avg10 ?? null;
    }

    function buildIoStatusGroup(l) {
      const disk = l?.disk || {};
      const mem = l?.bandwidth?.memory || {};
      const ioWait = diskIoWaitPct(l);
      const busy = disk.busy_pct;
      const zramNote = mem.io_wait_zram_dominated ? ' (swap churn hidden)' : '';
      return [
        {
          id: 'io_read', display: 'Read', icon: 'storage', iconCls: 'storage', hw: 'storage',
          tooltip: 'Aggregate disk read throughput',
          sensor: { value: disk.read_mbps, unit: ' MB/s', kind: 'rate' },
        },
        {
          id: 'io_write', display: 'Write', icon: 'storage', iconCls: 'storage', hw: 'storage',
          tooltip: 'Aggregate disk write throughput',
          sensor: { value: disk.write_mbps, unit: ' MB/s', kind: 'rate' },
        },
        {
          id: 'io_stall', display: 'I/O wait', icon: 'cpu', iconCls: 'storage', hw: 'storage',
          tooltip: `Disk wait — CPU iowait + queue busy${zramNote}`,
          sensor: { value: ioWait, unit: '%', kind: 'pct' },
          warnAt: 8, hotAt: 15,
        },
        {
          id: 'io_busy', display: 'Busy', icon: 'storage', iconCls: 'storage', hw: 'storage',
          tooltip: 'Time disk queue was busy',
          sensor: { value: busy, unit: '%', kind: 'pct' },
          warnAt: 70, hotAt: 90,
        },
      ];
    }

    /** Format bit-rate (Mbps float) for compact status cards — stable width units. */
    function fmtNetRate(mbps) {
      if (mbps == null || Number.isNaN(mbps)) return '—';
      const v = Number(mbps);
      if (v >= 1000) return `${(v / 1000).toFixed(1)}G`;
      if (v >= 10) return `${v.toFixed(0)}M`;
      if (v >= 1) return `${v.toFixed(1)}M`;
      if (v > 0.05) return `${(v * 1000).toFixed(0)}K`;
      if (v > 0) return '<50K';
      return '0';
    }

    function fmtDiskRate(mbps) {
      if (mbps == null || Number.isNaN(mbps)) return '—';
      const v = Number(mbps);
      if (v >= 100) return `${v.toFixed(0)} MB/s`;
      if (v >= 10) return `${v.toFixed(1)} MB/s`;
      if (v > 0) return `${v.toFixed(1)} MB/s`;
      return '0';
    }

    function fmtLinkSpeed(mbps) {
      if (mbps == null || mbps <= 0) return '—';
      if (mbps >= 1000) {
        const g = mbps / 1000;
        return Number.isInteger(g) ? `${g}G` : `${g.toFixed(1)}G`;
      }
      return `${mbps}M`;
    }

    function buildNetStatusGroup(l) {
      const net = l?.network || {};
      const down = net.down_mbps ?? 0;
      const up = net.up_mbps ?? 0;
      const primary = net.primary || '—';
      const speed = net.primary_speed_mbps;
      const linkLabel = net.primary_up === false ? 'Down' : fmtLinkSpeed(speed);
      const per = net.per_nic || {};
      const nicTip = Object.keys(per).length
        ? Object.entries(per).map(([n, v]) => {
            const st = v.is_up === false ? 'down' : 'up';
            return `${n} (${st}): ↓${fmtNetRate(v.down_mbps)} ↑${fmtNetRate(v.up_mbps)}`;
          }).join(' · ')
        : 'No tracked interfaces';
      return [
        {
          id: 'net_down', display: 'Down', icon: 'net', iconCls: 'cpu', hw: '',
          tooltip: `Aggregate download · ${nicTip}`,
          sensor: { value: down, unit: '', kind: 'net_rate', display: fmtNetRate(down) },
        },
        {
          id: 'net_up', display: 'Up', icon: 'net', iconCls: 'cpu', hw: '',
          tooltip: `Aggregate upload · ${nicTip}`,
          sensor: { value: up, unit: '', kind: 'net_rate', display: fmtNetRate(up) },
        },
        {
          id: 'net_link', display: primary === '—' ? 'Link' : primary,
          icon: 'net', iconCls: 'cpu', hw: '',
          tooltip: primary !== '—'
            ? `${primary} · ${net.primary_up === false ? 'link down' : `link ${fmtLinkSpeed(speed)}`} · ${net.up_count ?? 0}/${net.nic_count ?? 0} up`
            : 'Primary network interface',
          sensor: {
            value: speed ?? (net.primary_up ? 1 : 0),
            unit: '',
            kind: 'net_link',
            display: linkLabel,
          },
          warnAt: net.primary_up === false ? -1 : undefined,
          hotAt: undefined,
          linkDown: net.primary_up === false,
        },
      ];
    }

    function renderSensorStrip(sensors, l) {
      const wrap = document.querySelector('.sensor-strip-wrap');
      if (wrap && !wrap.offsetParent) return;
      const groups = buildHwStatusGroups(sensors);
      const io = buildIoStatusGroup(l);
      const network = buildNetStatusGroup(l);
      // Temps = all °C sensors (always visible). Show more = throughput only.
      const flat = [...groups.temps, ...io, ...network];
      const sig = JSON.stringify(flat.map(i => [
        i.id,
        i.sensor?.value,
        i.sensor?.unit,
        i.sensor?.display,
        i.linkDown,
      ]));
      const el = document.getElementById('sensorStrip');
      if (!el) return;
      if (!flat.length) {
        if (el.dataset.mode !== 'empty') {
          el.innerHTML = '<div class="hw-status-empty">No live hardware sensors</div>';
          el.dataset.mode = 'empty';
          delete el.dataset.structKey;
        }
        return;
      }
      const structKey = flat.map(i => i.id).join('|');
      if (el.dataset.structKey !== structKey) {
        el.dataset.structKey = structKey;
        el.innerHTML =
          renderHwStatusRow('Temps', groups.temps)
          + renderHwStatusRow('I/O', io, { secondary: true })
          + renderHwStatusRow('Network', network, { secondary: true });
        el.dataset.mode = 'live';
        lastSensorStripKey = '';
      }
      if (sig === lastSensorStripKey) return;
      lastSensorStripKey = sig;
      flat.forEach(item => {
        const card = el.querySelector(`[data-sid="${CSS.escape(item.id)}"]`);
        if (!card) return;
        const s = item.sensor;
        card.classList.remove('hot', 'warn');
        if (item.linkDown) card.classList.add('warn');
        if (s?.kind === 'temp') {
          const tc = item.isGpuJunc ? gpuJuncUiClass(s.value).trim() : tempClass(s.value);
          if (tc) card.classList.add(tc);
        } else if (s?.value != null && s?.kind !== 'net_rate' && s?.kind !== 'net_link') {
          if (item.hotAt != null && s.value >= item.hotAt) card.classList.add('hot');
          else if (item.warnAt != null && s.value >= item.warnAt) card.classList.add('warn');
        }
        const valEl = card.querySelector('[data-sval]');
        if (valEl) {
          if (s?.display != null) {
            valEl.textContent = s.display;
          } else {
            const unit = s?.unit || (s?.kind === 'temp' ? '°C' : '');
            valEl.textContent = s?.value != null ? `${s.value}${unit}` : '—';
          }
        }
      });
    }

    function renderVisualDashboard(l, comparison) {
      ensureMetricList('utilMeters', UTIL_SPECS);
      syncMetricHwTags('utilMeters', UTIL_SPECS);
      // Temps / bus / storage / power use unified .pulse-dials (not metric bars)
      ensureMetricList('netMeters', NET_SPECS);
      syncMetricHwTags('netMeters', NET_SPECS);

      const c = l.cpu || {}, m = l.memory || {}, g = l.gpu?.discrete || {}, gt = l.game_totals;
      const bw = l.bandwidth || {};
      const disk = l.disk || {};
      const net = l.network || {};

      setMetricBar('utilMeters', 'cpu', c.overall_pct, `${c.overall_pct}%`, `Load ${c.load?.join(' / ') ?? '—'}`, 'cpu');
      setMetricBar('utilMeters', 'ram', m.pct, `${m.pct}%`, `${m.used_gb} / ${m.total_gb} GB used`, 'mem');
      setMetricBar('utilMeters', 'gpu', g.busy_pct ?? 0, `${g.busy_pct ?? '—'}%`, `${g.power_w ?? '—'} W · ${g.gfx_mhz ?? '—'} MHz`, 'gpu');
      setMetricBar('utilMeters', 'vram', g.vram_pct ?? 0, `${g.vram_pct ?? '—'}%`, `${g.vram_used_mb ?? '—'} / ${g.vram_total_mb ?? '—'} MB`, 'vram');
      setMetricBar('utilMeters', 'swap', m.swap_pct, `${m.swap_pct}%`, `${m.swap_used_gb ?? '—'} GB swap used`, '');
      setMetricBar('utilMeters', 'game', gt?.running ? gt.cpu_pct : 0, gt?.running ? `${gt.cpu_pct}%` : 'Idle',
        gt?.running ? `${gt.primary_name || gt.game_name}` : 'No game', 'game');

      const temps = c.temps || {};
      const cpuT = temps.package;
      const gpuT = g.junction_c;
      const vramT = g.mem_temp_c;
      const cpuTMax = hwScales.cpu_temp_max_c || 105;
      const gpuTMax = hwScales.gpu_temp_max_c || 105;
      setPulseDial('tempMeters', 'cpu-pkg', tempPct(cpuT, cpuTMax), cpuT != null ? `${Math.round(cpuT)}°` : '—', {
        hot: cpuT != null && cpuT >= cpuTMax * 0.86,
        warn: cpuT != null && cpuT >= cpuTMax * 0.71 && cpuT < cpuTMax * 0.86,
      });
      setPulseDial('tempMeters', 'gpu-junc', gpuTempPct(gpuT), gpuT != null ? `${Math.round(gpuT)}°` : '—', {
        hot: gpuT != null && gpuT >= gpuTMax * 0.90,
        warn: gpuT != null && gpuT >= gpuTMax * 0.76 && gpuT < gpuTMax * 0.90,
      });

      const clk = cpuClockStats(c.per_core);
      const cpuBoost = Math.max(5500, clk.peak || 0);
      const gpuBoost = Number(g.thermal_profile?.boost_mhz) || 2500;
      const gpuClk = g.gfx_mhz != null ? Number(g.gfx_mhz) : null;
      const cpuClkEl = document.querySelector('#clockMeters [data-dial="cpu-clk"]');
      if (cpuClkEl && clk.peak != null) {
        cpuClkEl.title = `CPU clocks · avg ${fmtClockMhz(clk.avg)} · peak ${fmtClockMhz(clk.peak)}`;
      }
      const gpuClkEl = document.querySelector('#clockMeters [data-dial="gpu-clk"]');
      if (gpuClkEl && gpuClk != null) {
        gpuClkEl.title = `GPU shader clock ${Math.round(gpuClk)} MHz · boost ${gpuBoost} MHz`;
      }
      setPulseDial('clockMeters', 'cpu-clk', clk.avg != null ? (clk.avg / cpuBoost) * 100 : 0,
        fmtClockMhz(clk.avg), { hot: clk.avg != null && clk.avg >= cpuBoost * 0.98 });
      setPulseDial('clockMeters', 'gpu-clk', gpuClk != null ? Math.min(100, (gpuClk / gpuBoost) * 100) : 0,
        fmtClockMhz(gpuClk), { hot: gpuClk != null && gpuClk >= gpuBoost * 0.96 });
      const vramPct = g.vram_pct != null ? Number(g.vram_pct) : null;
      const vramFillEl = document.querySelector('#clockMeters [data-dial="vram-fill"]');
      if (vramFillEl && g.vram_used_mb != null) {
        vramFillEl.title = `VRAM ${g.vram_used_mb} / ${g.vram_total_mb} MB`;
      }
      setPulseDial('clockMeters', 'vram-fill', vramPct ?? 0,
        vramPct != null ? `${Math.round(vramPct)}%` : '—',
        { hot: vramPct != null && vramPct >= 90, warn: vramPct != null && vramPct >= 75 && vramPct < 90 });

      const memWait = Number(bw.memory?.psi_avg10) || 0;
      const ioWait = Number(bw.memory?.io_wait_pct) || 0;
      const waitPct = Math.max(memWait, ioWait);
      const waitFill = Math.min(100, waitPct * 5);
      setPulseDial('pressureMeters', 'dram-psi', waitFill,
        `${waitPct.toFixed(1)}%`,
        { hot: waitFill >= 40, warn: waitFill >= 20 && waitFill < 40 });
      const swapPct = Number(m.swap_pct);
      setPulseDial('pressureMeters', 'swap', Number.isFinite(swapPct) ? swapPct : 0,
        Number.isFinite(swapPct) ? `${Math.round(swapPct)}%` : '—',
        { hot: swapPct >= 20, warn: swapPct >= 8 && swapPct < 20 });

      const diskRead = disk.read_mbps ?? 0;
      const diskWrite = disk.write_mbps ?? 0;
      const diskBusy = disk.busy_pct ?? 0;
      updateIoCompact(diskRead, diskWrite, diskBusy);

      const netDown = net.down_mbps ?? 0;
      const netUp = net.up_mbps ?? 0;
      const linkSpeed = net.primary_speed_mbps || 0;
      const netCeil = Math.max(NET_RATE_CEIL_DEFAULT, linkSpeed > 0 ? linkSpeed : NET_RATE_CEIL_DEFAULT);
      const primaryName = net.primary || 'nic';
      setMetricBar('netMeters', 'net-down', Math.min(100, (netDown / netCeil) * 100),
        fmtNetRate(netDown), primaryName, '', 'net-down');
      setMetricBar('netMeters', 'net-up', Math.min(100, (netUp / netCeil) * 100),
        fmtNetRate(netUp), primaryName, '', 'net-up');
      setMetricBar('netMeters', 'net-link',
        net.primary_up === false ? 0 : (linkSpeed > 0 ? 100 : (net.primary_up ? 100 : 0)),
        net.primary_up === false ? 'Down' : fmtLinkSpeed(linkSpeed),
        net.primary_up === false ? 'link down' : 'up', '', 'net-link');
      renderCoreStrip(l.cpu.per_core || []);
      renderGpuEngineStrip(l.gpu?.discrete?.engines || [
        { id: 'gfx', label: 'Shaders', pct: g.busy_pct },
        { id: 'vram', label: 'Memory bus', pct: g.mem_busy_pct },
        { id: 'mm', label: 'Video', pct: null },
      ]);
      renderRigInsight(l);
      renderQuickGlance(l);
      renderPulseIndexViz(comparison);
      renderSensorStrip(l.sensors || [], l);
      renderStutterViz(l);
      renderSparkChart();
      syncVizTabBadges(l, comparison);
    }

    const SEV_LABEL = { hot: 'Critical', warn: 'Important', info: 'Moderate', ok: 'Healthy' };

    function esc(s) {
      return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    const ICON_PATHS = {
      health: '<path d="M12 3.5 18 6.5v5.2c0 4.2-2.8 7.2-6 8.3-3.2-1.1-6-4.1-6-8.3V6.5L12 3.5z"/><path d="m9.2 12.2 2.1 2.1 3.8-4"/>',
      cpu: '<rect x="7.5" y="7.5" width="9" height="9" rx="1.5"/><path d="M10.5 4.5v2.5M13.5 4.5v2.5M10.5 17v2.5M13.5 17v2.5M4.5 10.5h2.5M4.5 13.5h2.5M17 10.5h2.5M17 13.5h2.5"/>',
      ram: '<path d="M5 8.5h14v7H5z"/><path d="M8.5 8.5V6.5M12 8.5V6.5M15.5 8.5V6.5"/><path d="M7.5 11.5h2M11 11.5h2M14.5 11.5h2"/>',
      mem: '<path d="M5 8.5h14v7H5z"/><path d="M8.5 8.5V6.5M12 8.5V6.5M15.5 8.5V6.5"/><path d="M7.5 11.5h2M11 11.5h2M14.5 11.5h2"/>',
      gpu: '<path d="M4.5 9.5h15v6.5H4.5z"/><circle cx="9" cy="12.8" r="1.6"/><path d="M12.5 12.8H17"/><path d="M6.5 9.5V7.5M17.5 9.5V7.5"/>',
      game: '<path d="M8.5 11.8a2.6 2.6 0 0 1 2.6-2.6h1.3a2.6 2.6 0 0 1 2.6 2.6v.8a2.6 2.6 0 0 1-2.6 2.6h-1.3a2.6 2.6 0 0 1-2.6-2.6z"/><path d="M16.2 11.2h4.3M18.3 9.1v4.2"/><circle cx="10.2" cy="12.1" r=".7" fill="currentColor" stroke="none"/><circle cx="12.4" cy="10.8" r=".55" fill="currentColor" stroke="none"/>',
      /* Pulse Index — balance (fair class), not trophy */
      league: '<path d="M12 3.75v15.5M8.25 20.5h7.5"/><path d="M4.5 8.25h15"/><path d="M7.25 8.25 5.35 14.1a2.45 2.45 0 0 0 2.35 3.15h0a2.45 2.45 0 0 0 2.35-3.15L8.15 8.25"/><path d="M15.85 8.25 13.95 14.1a2.45 2.45 0 0 0 2.35 3.15h0a2.45 2.45 0 0 0 2.35-3.15L16.75 8.25"/><circle cx="12" cy="8.25" r="1.1" fill="currentColor" stroke="none"/>',
      fan: '<circle cx="12" cy="12" r="1.5"/><path d="M12 5.5c1.2 1.6 1.7 2.8 1.9 4.5M12 18.5c-1.2-1.6-1.7-2.8-1.9-4.5M5.5 12c1.6 1.2 2.8 1.7 4.5 1.9M18.5 12c-1.6-1.2-2.8-1.7-4.5-1.9"/>',
      temp: '<path d="M14.2 15.8V7.2a2.2 2.2 0 1 0-4.4 0v8.6"/><circle cx="12" cy="17.2" r="2.3"/>',
      storage: '<ellipse cx="12" cy="7.5" rx="6.5" ry="2.5"/><path d="M5.5 7.5v9c0 1.5 2.9 2.7 6.5 2.7s6.5-1.2 6.5-2.7v-9"/><path d="M5.5 12c0 1.5 2.9 2.7 6.5 2.7S18.5 13.5 18.5 12"/>',
      hot: '<path d="M12 5.2 19.5 18H4.5z"/><path d="M12 10.2v3.8"/><circle cx="12" cy="16.2" r=".8" fill="currentColor" stroke="none"/>',
      warn: '<circle cx="12" cy="12" r="8.5"/><path d="M12 8.5v4.2"/><circle cx="12" cy="15.8" r=".8" fill="currentColor" stroke="none"/>',
      info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11.2v4.5"/><circle cx="12" cy="8.5" r=".8" fill="currentColor" stroke="none"/>',
      ok: '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.2 2.6 2.6 4.8-5.6"/>',
      /* Live metrics — waveform (brand identity at glyph scale) */
      activity: '<path d="M3.5 12.5h3.2l1.6-4.2 2.3 9.2L14 6.2l1.9 6.3 1.5-2.8H20.5"/>',
      stutter: '<path d="M3.5 12h3.5l2-5 3 10 2.5-6H20"/>',
      chip: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 3.5v2M15 3.5v2M9 18.5v2M15 18.5v2M3.5 9h2M3.5 15h2M18.5 9h2M18.5 15h2"/>',
      /* Chassis / cosmic motif — orbit */
      chassis: '<circle cx="12" cy="12" r="4.6"/><ellipse cx="12" cy="12" rx="9.6" ry="3.5" transform="rotate(-28 12 12)"/>',
      orbit: '<circle cx="12" cy="12" r="4.6"/><ellipse cx="12" cy="12" rx="9.6" ry="3.5" transform="rotate(-28 12 12)"/>',
      pen: '<path d="M13.6 5.35 18.65 10.4"/><path d="M5.2 18.9 4.35 20.1l1.35-.55 8.9-8.9-2.2-2.2z"/><path d="m12.85 4.6 1.9-1.05 5.7 5.7-1.05 1.9"/><path d="M4.5 20.25h6.5" opacity=".55"/>',
      grid: '<rect x="3.75" y="3.75" width="7" height="7" rx="1.5"/><rect x="13.25" y="3.75" width="7" height="7" rx="1.5"/><rect x="3.75" y="13.25" width="7" height="7" rx="1.5"/><rect x="13.25" y="13.25" width="7" height="7" rx="1.5"/>',
      power: '<path d="M13 2.8 4.8 13.8h6.8l-.9 7.4L19 10.2h-6.8z"/>',
      net: '<circle cx="12" cy="12" r="2"/><path d="M5.5 8.5a10 10 0 0 1 13 0M8 11a6.5 6.5 0 0 1 8 0"/>',
    };

    function hwIcon(name, extraCls = '') {
      const paths = ICON_PATHS[name] || ICON_PATHS.chip;
      const svg = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
      return `<span class="hw-glyph ${extraCls}">${svg}</span>`;
    }

    function initStaticGlyphs() {
      document.querySelectorAll('[data-glyph]').forEach(el => {
        el.innerHTML = hwIcon(el.dataset.glyph);
      });
    }

    function tierBadgeClass(rank) {
      const r = String(rank ?? '').toUpperCase().trim();
      if (!r || r === '—') return '';
      if (r.startsWith('S')) return 'tier-s';
      if (r.startsWith('A')) return 'tier-a';
      if (r.startsWith('B')) return 'tier-b';
      if (r.startsWith('C')) return 'tier-c';
      return 'tier-d';
    }

    function tierBadge(rank, showTrophy = true) {
      const label = esc(rank ?? '—');
      const cls = tierBadgeClass(rank);
      return `<span class="rank-badge ${cls}">${showTrophy ? hwIcon('league', 'hw-badge-glyph') : ''}${label}</span>`;
    }

    function setTierBadge(el, rank, showTrophy = true) {
      if (!el) return;
      const r = String(rank ?? '');
      const key = `${r}|${showTrophy ? 1 : 0}`;
      if (el.dataset.tierKey === key) return;
      el.dataset.tierKey = key;
      el.innerHTML = r ? tierBadge(rank, showTrophy) : '';
    }

    function sevBadge(lv, label) {
      const icon = lv === 'hot' ? 'hot' : lv;
      return `<span class="rec-sev ${lv}">${hwIcon(icon, 'hw-sev-glyph')}${esc(label)}</span>`;
    }

    function partLabel(part) {
      const map = { CPU: 'cpu', GPU: 'gpu', RAM: 'ram' };
      const icon = map[part] || 'cpu';
      return `<span class="rank-part">${hwIcon(icon, 'hw-part-glyph')}<span>${esc(part)}</span></span>`;
    }

    function sensorKindIcon(s) {
      if (s.kind === 'temp') return 'temp';
      if (/fan/i.test(s.label)) return 'fan';
      if (/psi|load/i.test(s.label)) return 'cpu';
      return 'temp';
    }

    const MFR_LABELS = {
      amd: 'AMD', intel: 'Intel', nvidia: 'NVDA', xfx: 'XFX',
      gskill: 'G.SKILL', system76: 'S76', sapphire: 'SAPPHIRE',
      asus: 'ASUS', msi: 'MSI', corsair: 'CORSAIR', generic: 'HW',
    };

    const RIG_MEMORY_BRANDS = {
      gskill: 'G.SKILL', corsair: 'Corsair', kingston: 'Kingston', crucial: 'Crucial',
      teamgroup: 'TeamGroup', patriot: 'Patriot', adata: 'ADATA', samsung: 'Samsung',
      skhynix: 'SK hynix', micron: 'Micron', pny: 'PNY',
    };
    const RIG_STORAGE_BRANDS = {
      samsung: 'Samsung', wd: 'WD', toshiba: 'Toshiba', crucial: 'Crucial',
      kingston: 'Kingston', sandisk: 'SanDisk', seagate: 'Seagate', skhynix: 'SK hynix',
    };

    function rigNeutralBrand(slug, label) {
      if (!label) return null;
      return { slug: slug || 'generic', label, neutral: true };
    }

    function rigTopBrand(kind, part) {
      if (!part) return null;
      if (kind === 'cpu') {
        const b = part.brand;
        if (b === 'AMD') return { slug: 'amd', label: 'AMD' };
        if (b === 'Intel') return { slug: 'intel', label: 'Intel' };
      }
      if (kind === 'gpu') {
        const hay = `${part.maker || ''} ${part.brand || ''} ${part.model || ''}`.toLowerCase();
        if (hay.includes('nvidia') || hay.includes('geforce')) return { slug: 'nvidia', label: 'NVIDIA' };
        if (hay.includes('amd') || hay.includes('radeon') || /\brx\s*\d/.test(hay)) return { slug: 'amd', label: 'AMD' };
      }
      if (kind === 'chassis' && part.brand) {
        const slug = brandSlug(part.brand);
        if (slug === 'system76') return { slug: 'system76', label: 'System76', mark: 'S76' };
        return rigNeutralBrand(slug, String(part.brand).trim());
      }
      if (kind === 'memory' && part.brand) {
        const slug = brandSlug(part.brand);
        const label = RIG_MEMORY_BRANDS[slug] || String(part.brand).trim();
        return rigNeutralBrand(slug, label);
      }
      if (kind === 'storage' && part.brand) {
        const n = String(part.brand).toLowerCase();
        let slug = brandSlug(part.brand);
        if (n.includes('samsung')) slug = 'samsung';
        else if (n.includes('western') || n === 'wd') slug = 'wd';
        else if (n.includes('toshiba')) slug = 'toshiba';
        else if (n.includes('sandisk')) slug = 'sandisk';
        else if (n.includes('seagate')) slug = 'seagate';
        else if (n.includes('hynix')) slug = 'skhynix';
        const label = RIG_STORAGE_BRANDS[slug] || String(part.brand).trim();
        return rigNeutralBrand(slug, label);
      }
      return null;
    }

    function rigBrandHtml(brand) {
      if (!brand?.label) return '';
      const cls = `${esc(brand.slug)}${brand.neutral ? ' neutral' : ''}`;
      return `<span class="rig-tile-brand ${cls}">${esc(brand.label)}</span>`;
    }

    function rigBrandMarkHtml(brand) {
      if (!brand?.label || brand.neutral) return '';
      const text = brand.mark || brand.label;
      return `<span class="rig-brand-mark">${esc(text)}</span>`;
    }

    function brandSlug(name) {
      if (!name) return 'generic';
      const n = String(name).toLowerCase();
      if (n.includes('g.skill') || n.includes('gskill')) return 'gskill';
      if (n.includes('teamgroup') || n.includes('t-force') || n.includes('t-create')) return 'teamgroup';
      if (n.includes('patriot') || n.includes('viper')) return 'patriot';
      if (n.includes('adata') || n.includes('xpg')) return 'adata';
      if (n.includes('kingston') || n.includes('fury')) return 'kingston';
      if (n.includes('crucial') || n.includes('ballistix')) return 'crucial';
      if (n.includes('system76')) return 'system76';
      if (n.includes('dell') || n.includes('alienware')) return 'dell';
      if (n.includes('lenovo')) return 'lenovo';
      if (n.includes('framework')) return 'framework';
      if (/\bhp\b/.test(n) || n.includes('hewlett')) return 'hp';
      if (n.includes('nvidia') || n.includes('geforce')) return 'nvidia';
      if (n.includes('sapphire')) return 'sapphire';
      if (n.includes('corsair')) return 'corsair';
      if (n.includes('xfx')) return 'xfx';
      if (n.includes('asus')) return 'asus';
      if (n.includes('msi')) return 'msi';
      if (n.includes('amd') || n.includes('ryzen') || n.includes('radeon')) return 'amd';
      if (n.includes('intel') || n.includes('core i')) return 'intel';
      return 'generic';
    }

    function mfrMark(slug, size = '') {
      const label = MFR_LABELS[slug] || MFR_LABELS.generic;
      const sm = size === 'sm' ? ' sm' : '';
      return `<span class="mfr-mark ${slug}${sm}" aria-hidden="true">${esc(label)}</span>`;
    }

    function sensorHwFocus(sensor) {
      const id = (sensor?.id || '').toLowerCase();
      const lbl = (sensor?.label || '').toLowerCase();
      if (id.startsWith('nvme_') || /nvme|ssd|disk|drive/i.test(lbl)) return 'storage';
      if (/gpu|vram|amdgpu|gfx|igpu|edge|junction/i.test(id + ' ' + lbl)) return 'gpu';
      if (/psi|swap|ram|mem|dram|fault/i.test(lbl)) return 'memory';
      if (/cpu|k10|ccd|package|core|load/i.test(id + ' ' + lbl)) return 'cpu';
      return '';
    }

    function syncChipToggles() {
      document.querySelectorAll('.chip[data-g][data-k]').forEach(el => {
        const on = !!enabled[el.dataset.g]?.[el.dataset.k];
        el.classList.toggle('on', on);
        el.classList.toggle('off', !on);
      });
    }

    function applyChartFocus() {
      if (!anyHwFocus()) {
        if (enabledBeforeFocus) {
          Object.keys(enabled).forEach(g => {
            Object.assign(enabled[g], enabledBeforeFocus[g]);
          });
          enabledBeforeFocus = null;
          syncChipToggles();
        }
        return;
      }
      if (!enabledBeforeFocus) {
        enabledBeforeFocus = {
          util: { ...enabled.util },
          bw: { ...enabled.bw },
          io: { ...enabled.io },
        };
      }
      // Start dark, then OR-in series for each selected focus
      Object.assign(enabled.util, { cpu: false, gpu: false, ram: false, swap: false, gameCpu: false });
      Object.assign(enabled.bw, { vramBw: false, dramBw: false, gtt: false });
      Object.assign(enabled.io, { netDn: false, netUp: false, diskR: false, diskW: false });
      if (hwFocusHas('cpu')) {
        Object.assign(enabled.util, { cpu: true, gameCpu: true });
      }
      if (hwFocusHas('gpu')) {
        Object.assign(enabled.util, { gpu: true, gameCpu: true });
        Object.assign(enabled.bw, { vramBw: true, gtt: true });
      }
      if (hwFocusHas('memory')) {
        Object.assign(enabled.util, { ram: true, swap: true });
        Object.assign(enabled.bw, { dramBw: true });
      }
      if (hwFocusHas('storage')) {
        Object.assign(enabled.io, { diskR: true, diskW: true });
      }
      syncChipToggles();
    }

    /** Brand marks under /assets/brand/ (real logos where available). */
    const HOST_BADGE_LOGOS = {
      pop: 'pop.svg',
      system76: 'system76.svg',
      cosmic: 'cosmic.svg',
      kde: 'kde.svg',
      gnome: 'gnome.svg',
      xfce: 'xfce.svg',
      cinnamon: 'cinnamon.svg',
      hyprland: 'hyprland.svg',
      gamescope: 'gamescope.svg',
      nvidia: 'nvidia.svg',
      kernel: 'kernel.svg',
      mesa: 'mesa.svg',
      de: 'de.svg',
      linux: 'linux.svg',
    };

    function hostBadgeMark(id, deId) {
      const key = (id === 'de' && deId && HOST_BADGE_LOGOS[deId]) ? deId : id;
      const file = HOST_BADGE_LOGOS[key] || HOST_BADGE_LOGOS[id];
      if (file) {
        return {
          logo: true,
          html: `<img src="/assets/brand/${file}?v=2" alt="" width="18" height="18" decoding="async" />`,
        };
      }
      return { logo: false, html: '·' };
    }

    function renderPlatformBadges(s) {
      const host = document.getElementById('hostBadges');
      if (!host) return;
      const plat = s?.platform;
      const badges = plat?.badges || [];
      const deId = plat?.desktop?.id || null;
      document.body.classList.toggle('is-pop', !!plat?.is_pop);
      document.body.classList.toggle('is-system76', !!plat?.is_system76);
      // Only when COSMIC is the *running* session — not merely installed
      document.body.classList.toggle('is-cosmic', !!plat?.is_cosmic);
      document.body.classList.toggle('is-kde', deId === 'kde');
      document.body.classList.toggle('is-gnome', deId === 'gnome');
      document.body.classList.toggle('is-xfce', deId === 'xfce');
      document.body.classList.toggle('is-cinnamon', deId === 'cinnamon');
      document.body.classList.toggle('is-hyprland', deId === 'hyprland');
      document.body.classList.toggle('is-gamescope', deId === 'gamescope');
      document.body.classList.toggle('is-nvidia', !!plat?.is_nvidia);
      document.body.classList.toggle('is-amd-gpu', !!plat?.is_amd_gpu);
      if (!badges.length) {
        host.hidden = true;
        host.innerHTML = '';
        return;
      }
      const key = 'logo-v2|' + badges.map(b => `${b.id}:${b.detail || ''}`).join('|');
      if (host.dataset.key === key) {
        host.hidden = false;
        return;
      }
      host.dataset.key = key;
      host.hidden = false;
      host.innerHTML = badges.map(b => {
        const detail = b.detail
          ? `<span class="host-badge-detail">${esc(b.detail)}</span>`
          : '';
        const mark = hostBadgeMark(b.id, b.de_id);
        const markCls = mark.logo ? 'host-badge-mark logo' : 'host-badge-mark';
        return `<span class="host-badge ${esc(b.id)}" title="${esc(b.title || b.label)}">`
          + `<span class="${markCls}" aria-hidden="true">${mark.html}</span>`
          + `<span class="host-badge-label">${esc(b.label)}</span>${detail}</span>`;
      }).join('');
    }

    function updateMetaLine(s, l) {
      const metaEl = document.getElementById('meta');
      if (!metaEl) return;
      // Full inventory line is redundant with host badges + rig tiles — hide by default.
      // When a hardware filter is active, show a compact live readout for the focus.
      if (!anyHwFocus()) {
        metaEl.hidden = true;
        metaEl.textContent = '';
        return;
      }
      const rig = s.rig || {};
      const mem = s.memory || {};
      const c = l?.cpu || {};
      const g = l?.gpu?.discrete || {};
      const parts = [];
      if (hwFocusHas('cpu')) {
        parts.push(`${rig.cpu?.model || 'CPU'} · ${c.overall_pct ?? '—'}% · ${c.temps?.package ?? '—'}°C`);
      }
      if (hwFocusHas('gpu')) {
        const tp = s.gpu_thermal || g.thermal_profile || {};
        const arch = tp.label ? ` (${tp.label})` : '';
        parts.push(`${rig.gpu?.model || s.gpu_model}${arch} · ${g.busy_pct ?? '—'}% · ${g.junction_c ?? '—'}°C`);
      }
      if (hwFocusHas('memory')) {
        parts.push(`${rig.memory?.kit || mem.label || 'RAM'} · ${l?.memory?.pct ?? '—'}% · swap ${l?.memory?.swap_pct ?? '—'}%`);
      }
      if (hwFocusHas('storage')) {
        const disk = l?.disk || {};
        const ioWait = diskIoWaitPct(l) ?? '—';
        const drives = rig.storage || s.storage || [];
        const driveLabel = drives.length === 1
          ? (drives[0].model || drives[0].brand || 'NVMe')
          : `${drives.length} NVMe drives`;
        parts.push(`${driveLabel} · R ${disk.read_mbps ?? '—'} · W ${disk.write_mbps ?? '—'} MB/s · ${ioWait}% I/O`);
      }
      const text = parts.join(' · ') || hwFocusLabelText();
      metaEl.textContent = text;
      metaEl.hidden = !text;
    }

    function hwItemVisible(el) {
      if (!anyHwFocus()) return true;
      if (el.hasAttribute('data-hw-keep')) return true;
      const hw = el.getAttribute('data-hw') || '';
      if (!hw) return true;
      const tags = hw.split(/\s+/).filter(Boolean);
      return tags.some(t => hwFocusHas(t));
    }

    function clearHwFilterHide(el) {
      const pending = hwFilterHideHandlers.get(el);
      if (!pending) return;
      if (pending.timer) clearTimeout(pending.timer);
      if (pending.onEnd) el.removeEventListener('transitionend', pending.onEnd);
      hwFilterHideHandlers.delete(el);
    }

    function finishHwFilterHide(el) {
      clearHwFilterHide(el);
      el.classList.add('hw-filtered-hidden');
    }

    function setHwFilterVisible(el, visible) {
      if (!el || el.hasAttribute('data-hw-keep')) return;
      if (el.matches('#warningList .warn-row[data-hw]')) {
        clearHwFilterHide(el);
        el.classList.remove('hw-filtered-out');
        el.style.maxHeight = '';
        el.classList.toggle('hw-filtered-hidden', !visible);
        return;
      }
      if (visible) {
        clearHwFilterHide(el);
        el.classList.remove('hw-filtered-hidden');
        if (el.classList.contains('hw-filtered-out')) {
          requestAnimationFrame(() => el.classList.remove('hw-filtered-out'));
        }
        if (el.matches('.warn-row[data-hw]')) el.style.maxHeight = '';
        return;
      }
      if (el.classList.contains('hw-filtered-hidden')) return;
      if (el.classList.contains('hw-filtered-out') && hwFilterHideHandlers.has(el)) return;
      clearHwFilterHide(el);
      if (prefersReducedMotion) {
        el.classList.add('hw-filtered-out', 'hw-filtered-hidden');
        return;
      }
      if (el.matches('.warn-row[data-hw]')) {
        el.style.maxHeight = `${Math.max(el.scrollHeight, el.offsetHeight)}px`;
      }
      el.classList.add('hw-filtered-out');
      const onEnd = (e) => {
        if (e.target !== el || (e.propertyName !== 'opacity' && e.propertyName !== 'max-height')) return;
        finishHwFilterHide(el);
      };
      const timer = setTimeout(() => finishHwFilterHide(el), HW_FILTER_HIDE_MS);
      hwFilterHideHandlers.set(el, { onEnd, timer });
      el.addEventListener('transitionend', onEnd);
    }

    function applyHwFilterClasses() {
      document.querySelectorAll('#summaryBar [data-hw], #vizPanel [data-hw], #pulseIndexBlock [data-hw]').forEach(el => {
        setHwFilterVisible(el, hwItemVisible(el));
      });
    }

    function applyWarningFilterClasses() {
      document.querySelectorAll('#warningList .warn-row[data-hw]').forEach(el => {
        setHwFilterVisible(el, hwItemVisible(el));
      });
    }

    function updateVizTitles() {
      document.querySelectorAll('#vizPanel .viz-block').forEach(block => {
        const areaClass = [...block.classList].find(c => c.startsWith('viz-area-'));
        if (!areaClass) return;
        const map = VIZ_BLOCK_TITLES[areaClass];
        if (!map) return;
        const h3 = block.querySelector('.viz-block-head h3');
        if (!h3) return;
        const soleViz = soleHwFocus();
        const title = soleViz && map[soleViz]
          ? map[soleViz]
          : (anyHwFocus() ? `${map.default} · ${hwFocusLabelText()}` : map.default);
        if (h3.textContent !== title) h3.textContent = title;
        const iconMap = VIZ_BLOCK_ICONS[areaClass];
        const iconEl = block.querySelector('.viz-block-head .hw-icon-box[data-glyph]');
        if (iconEl && iconMap) {
          const glyph = soleViz && iconMap[soleViz] ? iconMap[soleViz] : iconMap.default;
          if (iconEl.dataset.glyph !== glyph) {
            iconEl.dataset.glyph = glyph;
            iconEl.className = `hw-icon-box ${VIZ_ICON_BOX_CLS[glyph] || glyph}`;
            iconEl.innerHTML = hwIcon(glyph);
          }
        }
      });
    }

    function hintHwFocus(hint) {
      const id = hint?.insight_id || '';
      if (HINT_HW_MAP[id]) return HINT_HW_MAP[id];
      const blob = `${id} ${hint?.title || ''} ${hint?.text || ''}`.toLowerCase();
      const tags = new Set();
      if (/cpu|governor|ccd|core|ryzen|package|powersave/.test(blob)) tags.add('cpu');
      if (/gpu|vram|gtt|junction|shader|radeon|geforce|amdgpu/.test(blob)) tags.add('gpu');
      if (/\bgpu\b.*thermal|thermal.*\bgpu\b|overheating|getting warm/.test(blob)) tags.add('gpu');
      if (/memory|ram|swap|dram|expo|page.?fault|swappiness/.test(blob)) tags.add('memory');
      if (/disk|nvme|storage|i\/o wait|io stall/.test(blob)) tags.add('storage');
      if (/stutter|hitch/.test(blob)) {
        tags.add('cpu');
        tags.add('memory');
      }
      if (/balanced|looking good|no major/.test(blob)) return ['cpu', 'gpu', 'memory'];
      return tags.size ? [...tags] : ['cpu', 'gpu', 'memory'];
    }

    function hintVisibleForFocus(hint) {
      if (!anyHwFocus()) return true;
      const tags = hintHwFocus(hint);
      return tags.some(t => hwFocusHas(t));
    }

    function updateWarningsFocusUI() {
      const { all: active } = warningsWidgetData(lastWarningsHints);
      const visible = active.filter(h => hintVisibleForFocus(h));
      const sessionHits = lastActiveGameId
        ? visible.filter(h => hintForActiveGame(h, lastActiveGameId)).length
        : 0;
      const counts = { hot: 0, warn: 0, info: 0 };
      visible.forEach(h => { if (counts[h.level] !== undefined) counts[h.level]++; });
      const nAttn = visible.length;

      const metaEl = document.getElementById('tuningMeta');
      if (metaEl) {
        if (!nAttn) {
          metaEl.innerHTML = anyHwFocus()
            ? `No ${hwFocusLabelText()} warnings for this rig focus`
            : '<span style="color:var(--m-mem)">✓ No outstanding issues</span> · Guidance has scripts and step-by-step help';
        } else {
          const parts = [`${nAttn} need${nAttn === 1 ? 's' : ''} attention`];
          if (anyHwFocus()) parts.push(`${hwFocusLabelText()} focus`);
          if (sessionHits && lastActiveGameId) {
            parts.push(`${sessionHits} for ${gameLabel(lastActiveGameId)}`);
          }
          metaEl.textContent = parts.join(' · ');
        }
      }

      // Compact collapsed preview (matches other drill cards)
      const rollEl = document.getElementById('drillWarningsSum');
      const warnDrill = document.getElementById('warningsSection');
      if (rollEl) {
        if (!nAttn) {
          rollEl.textContent = anyHwFocus()
            ? `Clear for ${hwFocusLabelText()}`
            : 'All clear';
        } else {
          const bits = [];
          if (counts.hot) bits.push(`${counts.hot} critical`);
          if (counts.warn) bits.push(`${counts.warn} important`);
          if (counts.info) bits.push(`${counts.info} moderate`);
          let line = bits.join(' · ') || `${nAttn} open`;
          if (sessionHits && lastActiveGameId) {
            line += ` · ${sessionHits} for ${gameLabel(lastActiveGameId)}`;
          } else if (anyHwFocus()) {
            line += ` · ${hwFocusLabelText()}`;
          }
          rollEl.textContent = line;
        }
      }
      if (warnDrill) {
        warnDrill.classList.toggle('warn-all-clear', nAttn === 0);
        warnDrill.classList.toggle('warn-has-hot', counts.hot > 0);
      }

      const pillsKey = JSON.stringify({ counts, focus: hwFocusKey() });
      if (pillsKey !== lastWarningsPillsKey) {
        lastWarningsPillsKey = pillsKey;
        const summaryEl = document.getElementById('tuningSummary');
        if (summaryEl) {
          const pills = [
            ['hot', 'Critical', counts.hot],
            ['warn', 'Important', counts.warn],
            ['info', 'Moderate', counts.info],
          ].filter(([, , n]) => n > 0);
          summaryEl.innerHTML = pills.length ? stablePillsHtml(pills) : '';
        }
      }
      applyWarningFilterClasses();
      const listEl = document.getElementById('warningList');
      if (!listEl) return;
      let focusEmptyEl = listEl.querySelector('.warn-focus-empty');
      if (active.length && !visible.length && anyHwFocus()) {
        if (!focusEmptyEl) {
          focusEmptyEl = document.createElement('p');
          focusEmptyEl.className = 'warn-empty warn-focus-empty';
          listEl.appendChild(focusEmptyEl);
        }
        focusEmptyEl.textContent =
          `No ${hwFocusLabelText()} warnings — reset with Chassis or change filters.`;
        focusEmptyEl.hidden = false;
      } else if (focusEmptyEl) {
        focusEmptyEl.hidden = true;
      }
    }

    function scheduleNocEmptyStates() {
      if (nocEmptyTimer) clearTimeout(nocEmptyTimer);
      nocEmptyTimer = setTimeout(() => {
        nocEmptyTimer = null;
        updateNocEmptyStates();
      }, prefersReducedMotion ? 0 : HW_FILTER_HIDE_MS);
    }

    function updateNocEmptyStates() {
      const label = anyHwFocus() ? hwFocusLabelText() : '';
      document.querySelectorAll('#vizPanel .viz-block').forEach(block => {
        const note = block.querySelector('.viz-empty-note');
        const filterable = [...block.querySelectorAll('[data-hw]')].filter(el =>
          !el.classList.contains('viz-empty-note') && !el.hasAttribute('data-hw-keep'));
        const keepers = [...block.querySelectorAll('[data-hw-keep]')].filter(el =>
          !el.classList.contains('viz-empty-note'));
        if (!anyHwFocus() || !filterable.length) {
          block.classList.remove('noc-hw-empty');
          if (note) note.hidden = true;
          return;
        }
        const anyFilterableShown = filterable.some(el =>
          hwItemVisible(el) && !el.classList.contains('hw-filtered-hidden'));
        const hasKeeperContent = keepers.length > 0;
        const isEmpty = !anyFilterableShown && !hasKeeperContent;
        block.classList.toggle('noc-hw-empty', isEmpty);
        if (note) {
          note.hidden = !isEmpty;
          note.textContent = `No ${label} metrics in this widget`;
        }
      });
    }

    function syncHwFocusDOM() {
      if (anyHwFocus()) document.body.dataset.hwFocus = hwFocusKey();
      else delete document.body.dataset.hwFocus;
      document.querySelectorAll('[data-hw-filter]').forEach(btn => {
        const f = btn.dataset.hwFilter;
        const active = (f === 'chassis' && !anyHwFocus()) || hwFocusHas(f);
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
      Object.entries(HW_FOCUS_SUM_CELLS).forEach(([focus, id]) => {
        const cell = document.getElementById(id);
        if (cell) cell.classList.toggle('hw-focus-hero', hwFocusHas(focus));
      });
      const banner = document.getElementById('rigFocusBanner');
      const text = document.getElementById('rigFocusText');
      if (banner && text) {
        if (!anyHwFocus()) {
          banner.hidden = true;
        } else {
          banner.hidden = false;
          const names = [...hwFocusSet].map(f => {
            const tile = document.querySelector(`[data-hw-filter="${f}"] .rig-tile-name`);
            return tile?.textContent?.trim() || HW_FOCUS_LABELS[f];
          });
          text.textContent = `NOC filtered to ${hwFocusLabelText()} · ${names.join(' · ')}`;
        }
      }
      const chassisBtn = document.querySelector('[data-hw-filter="chassis"]');
      const chassis = lastStatic?.rig?.chassis;
      if (chassisBtn && chassis?.label) {
        chassisBtn.title = anyHwFocus()
          ? `${chassis.label} · Click to reset filters (full rig)`
          : `${chassis.label} · Full rig view`;
      }
      updateVizTitles();
      applyChartFocus();
      applyHwFilterClasses();
      updateWarningsFocusUI();
      scheduleNocEmptyStates();
    }

    function setHwFocus(part) {
      // Chassis / null → reset all filters
      if (!part || part === 'chassis') {
        hwFocusSet.clear();
      } else if (HW_FOCUS_PARTS.includes(part)) {
        // Toggle part on/off (multi-select)
        if (hwFocusSet.has(part)) hwFocusSet.delete(part);
        else hwFocusSet.add(part);
      }
      persistHwFocus();
      syncHwFocusDOM();
      if (lastStatic) updateMetaLine(lastStatic, lastLatest);
      if (lastLatest) {
        renderSummaryBar(lastLatest, lastWarningsHints, lastComparison);
        renderRigInsight(lastLatest);
        renderPulseIndexViz(lastComparison);
      }
      renderCharts();
      renderSparkChart();
    }

    const RIG_TILE_ICON_CLS = {
      chassis: 'chassis', cpu: 'cpu', gpu: 'gpu', memory: 'mem', storage: 'storage',
    };

    /** Filled, type-obvious icons for the rig strip (not the thin shared set). */
    const RIG_TILE_ICONS = {
      // Tower PC with front panel + power LED
      chassis: `
        <rect class="rf-fill" x="6.5" y="3.2" width="11" height="17.6" rx="1.6"/>
        <rect x="6.5" y="3.2" width="11" height="17.6" rx="1.6" fill="none"/>
        <path d="M9 6.4h6M9 9h6M9 11.6h4.5"/>
        <circle class="rf-core" cx="12" cy="17.2" r="1.15" stroke="none"/>
        <path d="M8.2 21.4h7.6" stroke-width="1.8"/>`,
      // CPU package with pins + core grid
      cpu: `
        <rect class="rf-fill" x="7.2" y="7.2" width="9.6" height="9.6" rx="1.4"/>
        <rect x="7.2" y="7.2" width="9.6" height="9.6" rx="1.4" fill="none"/>
        <rect class="rf-solid" x="9" y="9" width="2.4" height="2.4" rx=".35" stroke="none"/>
        <rect class="rf-solid" x="12.6" y="9" width="2.4" height="2.4" rx=".35" stroke="none"/>
        <rect class="rf-solid" x="9" y="12.6" width="2.4" height="2.4" rx=".35" stroke="none"/>
        <rect class="rf-solid" x="12.6" y="12.6" width="2.4" height="2.4" rx=".35" stroke="none"/>
        <path d="M9.5 4.2v2.5M12 4.2v2.5M14.5 4.2v2.5M9.5 17.3v2.5M12 17.3v2.5M14.5 17.3v2.5"/>
        <path d="M4.2 9.5h2.5M4.2 12h2.5M4.2 14.5h2.5M17.3 9.5h2.5M17.3 12h2.5M17.3 14.5h2.5"/>`,
      // Dual-slot graphics card + fan
      gpu: `
        <rect class="rf-fill" x="3.4" y="8.2" width="17.2" height="8.2" rx="1.3"/>
        <rect x="3.4" y="8.2" width="17.2" height="8.2" rx="1.3" fill="none"/>
        <circle class="rf-core" cx="8.6" cy="12.3" r="2.35" fill="none"/>
        <circle class="rf-solid" cx="8.6" cy="12.3" r="1" stroke="none"/>
        <path d="M12.4 10.4h6.2M12.4 12.3h5.2M12.4 14.2h4"/>
        <path d="M5.2 8.2V6.4M18.8 8.2V6.4M5.2 16.4v1.8M18.8 16.4v1.8"/>
        <path d="M3.4 10.2H2.2M3.4 14.4H2.2"/>`,
      // DIMM stick (not a generic bar)
      memory: `
        <path class="rf-fill" d="M5 7.2h14v9.2c0 .7-.5 1.3-1.2 1.3H6.2c-.7 0-1.2-.6-1.2-1.3z"/>
        <path d="M5 7.2h14v9.2c0 .7-.5 1.3-1.2 1.3H6.2c-.7 0-1.2-.6-1.2-1.3z" fill="none"/>
        <path d="M7.2 7.2V5.5M10 7.2V5.5M12.8 7.2V5.5M15.6 7.2V5.5M18.4 7.2V5.5"/>
        <rect class="rf-solid" x="7" y="9.2" width="2.2" height="5.6" rx=".35" stroke="none"/>
        <rect class="rf-solid" x="10.4" y="9.2" width="2.2" height="5.6" rx=".35" stroke="none"/>
        <rect class="rf-solid" x="13.8" y="9.2" width="2.2" height="5.6" rx=".35" stroke="none"/>
        <path d="M5 14.8h14"/>`,
      // SSD / drive with connector pins
      storage: `
        <rect class="rf-fill" x="4.2" y="7.5" width="15.6" height="9" rx="1.4"/>
        <rect x="4.2" y="7.5" width="15.6" height="9" rx="1.4" fill="none"/>
        <path d="M7 10.2h6.5M7 12.5h4.5"/>
        <circle class="rf-core" cx="17" cy="12" r="1.35" stroke="none"/>
        <path d="M6 16.5v1.8M8.2 16.5v1.8M10.4 16.5v1.8M12.6 16.5v1.8"/>
        <path d="M4.2 9.5H3M4.2 14.5H3"/>`,
    };

    function rigTileIcon(kind) {
      const body = RIG_TILE_ICONS[kind];
      if (!body) return hwIcon('chip', 'rig-art-glyph');
      const svg = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.45" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
      return `<span class="hw-glyph rig-fill rig-art-glyph ${RIG_TILE_ICON_CLS[kind] || kind}">${svg}</span>`;
    }

    function rigBrandLogoHtml(brand) {
      // Corner logo when we have a real mark (System76); AMD/Intel stay as text chips for now
      if (brand?.slug === 'system76') {
        return `<span class="rig-brand-logo" title="System76"><img src="/assets/brand/system76.svg" alt="" width="16" height="16" decoding="async"></span>`;
      }
      return '';
    }

    function rigTileHtml(t) {
      const icon = rigTileIcon(t.kind);
      const brandHtml = rigBrandHtml(t.brand);
      const brandCls = t.brand?.slug && !t.brand.neutral ? ` brand-${t.brand.slug}` : '';
      const brandMark = rigBrandMarkHtml(t.brand);
      const brandLogo = rigBrandLogoHtml(t.brand);
      return `<button type="button" class="rig-tile ${t.kind}${brandCls}${t.active ? ' active' : ''}" data-rig-id="${esc(t.id)}"
        data-hw-filter="${t.filter}" aria-pressed="${t.active ? 'true' : 'false'}" title="${esc(t.tooltip)}">
        <span class="rig-tile-body">
          <span class="rig-tile-meta">
            <span class="rig-tile-type">${esc(t.type)}</span>
            ${brandHtml}
          </span>
          <span class="rig-tile-name">${esc(t.name)}</span>
        </span>
        <span class="rig-tile-hint">${t.filter === 'chassis' ? 'Reset filters' : 'Toggle filter'}</span>
        <span class="rig-tile-art" aria-hidden="true">${brandMark}${icon}${brandLogo}</span>
      </button>`;
    }

    function bindRigTiles(el) {
      el.querySelectorAll('[data-rig-id]').forEach(btn => {
        btn.onclick = () => {
          const f = btn.dataset.hwFilter;
          if (f === 'chassis') setHwFocus(null);
          else setHwFocus(f);
        };
      });
    }

    function buildRigTiles(s) {
      const r = s.rig || {};
      const tiles = [];
      if (r.chassis?.label || r.chassis?.model) {
        const plat = s.platform || {};
        const kind = r.chassis.kind || '';
        const s76 = plat.is_system76 || r.chassis.brand === 'System76' || kind === 'system76';
        const chassisName = r.chassis.model || r.chassis.label;
        let chassisType = 'Desktop';
        if (s76) chassisType = 'System76';
        else if (r.chassis.brand) chassisType = r.chassis.brand;
        const thelioLove = s76
          ? ` · ${chassisName} — built for Linux${plat.is_pop ? ' · Pop!_OS' : ''}`
          : '';
        tiles.push({
          id: 'chassis', filter: 'chassis', kind: 'chassis',
          type: chassisType, name: chassisName,
          brand: rigTopBrand('chassis', r.chassis),
          tooltip: anyHwFocus()
            ? `${r.chassis.label} · Click to reset filters (full rig)`
            : `${r.chassis.label} · Full rig view${thelioLove}`,
          active: !anyHwFocus(),
        });
      }
      if (r.cpu?.model) {
        tiles.push({
          id: 'cpu', filter: 'cpu', kind: 'cpu',
          type: 'Processor', name: r.cpu.model,
          brand: rigTopBrand('cpu', r.cpu),
          tooltip: `${r.cpu.label} · ${hwFocusHas('cpu') ? 'Remove CPU filter' : 'Add CPU filter'}`,
          active: hwFocusHas('cpu'),
        });
      }
      if (r.gpu?.model) {
        const tp = s.gpu_thermal || {};
        const rdna3Note = tp.arch === 'rdna3' ? ' · Hotspot 95–108°C is normal on RDNA3' : '';
        tiles.push({
          id: 'gpu', filter: 'gpu', kind: 'gpu',
          type: 'Graphics', name: r.gpu.model,
          brand: rigTopBrand('gpu', r.gpu),
          tooltip: `${r.gpu.board || r.gpu.label || r.gpu.model}${rdna3Note} · ${hwFocusHas('gpu') ? 'Remove GPU filter' : 'Add GPU filter'}`,
          active: hwFocusHas('gpu'),
        });
      }
      if (r.memory?.kit || r.memory?.label) {
        tiles.push({
          id: 'memory', filter: 'memory', kind: 'memory',
          type: 'Memory', name: r.memory.kit || r.memory.label || 'RAM',
          brand: rigTopBrand('memory', r.memory),
          tooltip: `${r.memory.label} · ${hwFocusHas('memory') ? 'Remove memory filter' : 'Add memory filter'}`,
          active: hwFocusHas('memory'),
        });
      }
      const drives = r.storage || s.storage || [];
      if (drives.length) {
        const name = drives.length === 1
          ? (drives[0].model || drives[0].brand || 'NVMe').slice(0, 28)
          : `${drives.length} NVMe drives`;
        tiles.push({
          id: 'storage', filter: 'storage', kind: 'storage',
          type: 'Storage', name,
          brand: rigTopBrand('storage', drives[0]),
          tooltip: `${drives.map(d => `${d.brand} ${d.model} (${d.size})`).join('\n')} · ${hwFocusHas('storage') ? 'Remove storage filter' : 'Add storage filter'}`,
          active: hwFocusHas('storage'),
        });
      }
      return tiles;
    }

    function renderRigStrip(s) {
      const el = document.getElementById('rigStrip');
      const tiles = buildRigTiles(s);
      // v2 = filled type icons; force rebuild once after upgrade
      const structKey = 'icons-v3|' + tiles.map(t => `${t.id}:${t.type}:${t.name}`).join('|');
      if (el.dataset.structKey !== structKey) {
        el.dataset.structKey = structKey;
        el.innerHTML = tiles.map(rigTileHtml).join('');
        bindRigTiles(el);
      }
    }

    function hwIdentityCell(row) {
      const name = row.name || '—';
      const maker = row.maker || row.brand;
      const board = row.board;
      const slug = brandSlug(maker || row.brand || row.kit || row.label || '');
      if (row.label && row.label !== name && (maker || row.kit || row.brand)) {
        return `<div class="hw-identity">
          <span class="hw-id-primary hw-id-row">${mfrMark(slug, 'sm')}<span>${esc(row.label)}</span></span>
          <span class="hw-id-sub">Build tier · ${esc(name)}</span>
        </div>`;
      }
      if (maker && maker !== name) {
        return `<div class="hw-identity">
          <span class="hw-id-primary hw-id-row">${mfrMark(slug, 'sm')}<span>${esc(name)}</span></span>
          ${board ? `<span class="hw-id-sub">${esc(board)}</span>` : ''}
        </div>`;
      }
      if (row.brand && brandSlug(row.brand) !== 'generic') {
        return `<div class="hw-identity">
          <span class="hw-id-primary hw-id-row">${mfrMark(brandSlug(row.brand), 'sm')}<span>${esc(name)}</span></span>
        </div>`;
      }
      return `<span class="hw-id-primary">${esc(name)}</span>`;
    }

    function legacyGameIds() {
      return lastStatic?.legacy_game_ids || {};
    }
    function normalizeGameId(id) {
      if (!id) return id;
      const legacy = legacyGameIds();
      return legacy[id] || id;
    }

    function gameLabel(id) {
      const norm = normalizeGameId(id);
      const cat = lastStatic?.games_catalog?.[norm] || lastStatic?.games_catalog?.[id];
      if (cat?.short) return cat.short;
      if (cat?.name) return cat.name;
      if (norm && /^\d+$/.test(norm)) return `App ${norm}`;
      return norm || id || 'Game';
    }

    /* --- Guidance tab (index + detail + dashboard warnings) ---
       Outstanding hints stay in the list; live is a badge only. See docs/ARCHITECTURE.md */
    const WARN_WIDGET_MAX = 10;

    const GUIDANCE_STEAM_IDS = new Set([
      'game-libs-missing', 'steam-disk-low', 'vulkan-broken',
      'game-files-corrupt', 'game-update-pending', 'game-prefix-reset',
    ]);

    const guidanceSectionCounts = {
      steam: 0, system: 0, resolutions: 0, games: 0, scan: 0, fixed: 0,
      steam_hot: false, system_hot: false, resolutions_hot: false, scan_hot: false,
      scan_always: false,
    };

    function guidanceCategory(h) {
      if (h.bucket === 'resolutions') return 'resolutions';
      if (h.bucket === 'steam') return 'steam';
      const id = h.insight_id || '';
      if (GUIDANCE_STEAM_IDS.has(id) || id.startsWith('game-') || id.startsWith('steam-')) return 'steam';
      return 'system';
    }

    let lastGuidanceSummaryHints = [];
    let lastSelectedGuidanceId = null;
    let guidanceIndexFilter = 'all';
    let guidanceGameFilter = null;
    let guidancePickableHints = [];

    function guidanceHintCount(arr) {
      return (arr || []).filter(h => h.level !== 'ok').length;
    }

    function hintMatchesGameFilter(h, gameId) {
      if (!gameId) return true;
      const scope = h.games || ['all'];
      if (scope.includes('all')) return true;
      if (scope.includes(gameId)) return true;
      return (h.games_affected || []).includes(gameId);
    }

    const GUIDANCE_GROUP_ORDER = { steam: 0, system: 1, resolutions: 2, scan: 3, fixed: 4 };

    function guidanceScanLogPreview(f, max = 80) {
      const raw = (f?.detail || '').trim();
      if (!raw) return '';
      const line = raw.split('\n').map(l => l.trim()).find(l => l.length > 0) || '';
      if (!line) return '';
      return line.length <= max ? line : `${line.slice(0, max - 1)}…`;
    }

    function guidanceScanEvidenceHtml(f) {
      const detail = (f?.detail || '').trim();
      const source = (f?.source || '').trim();
      if (!detail && !source) return '';
      const detailBlock = detail ? `
        <div class="rec-section">
          <h4 class="rec-section-title">Log excerpt</h4>
          <pre class="diag-pre">${esc(detail)}</pre>
        </div>` : '';
      const sourceBlock = source ? `
        <p class="diag-source"><span class="rec-meta">Source</span> <code>${esc(source)}</code></p>` : '';
      return detailBlock + sourceBlock;
    }

    function guidanceSeverityRank(lv) {
      return { hot: 0, warn: 1, info: 2, ok: 3 }[lv] ?? 9;
    }

    function sortGuidanceHints(hints) {
      return [...hints].sort((a, b) => {
        const sev = guidanceSeverityRank(a.level) - guidanceSeverityRank(b.level);
        if (sev) return sev;
        const ps = warningPriority(b) - warningPriority(a);
        if (ps) return ps;
        const fs = (a.first_seen || 0) - (b.first_seen || 0);
        if (fs) return fs;
        return (a.insight_id || a.title || '').localeCompare(b.insight_id || b.title || '');
      });
    }

    function sortGuidanceGroups(groups) {
      return [...groups].sort((a, b) => {
        const order = (GUIDANCE_GROUP_ORDER[a.key] ?? 9) - (GUIDANCE_GROUP_ORDER[b.key] ?? 9);
        if (order) return order;
        const worst = (g) => Math.min(...g.hints.map(h => guidanceSeverityRank(h.level || h.severity)));
        return worst(a) - worst(b);
      });
    }

    function guidanceScanPickId(f) {
      return `diag:${f.id}`;
    }

    function guidanceSevTag(lv) {
      const label = SEV_LABEL[lv] || lv || 'info';
      return `<span class="guidance-tag sev-${esc(lv || 'info')}">${esc(label)}</span>`;
    }

    function guidanceIndexRowHtml(h, selected) {
      const lv = h.level || 'info';
      const sid = h.insight_id || 'insight';
      const resolved = hintUserStatus(h) === 'resolved';
      const live = h.condition_live && !resolved;
      const why = (h.text || '').trim();
      const stepN = (h.actions || []).length;
      const tags = [
        guidanceSevTag(lv),
        live ? '<span class="guidance-tag live">Live</span>' : '',
        resolved ? '<span class="guidance-tag fixed">Fixed</span>' : '',
        stepN ? `<span class="guidance-tag steps-n">${stepN} step${stepN === 1 ? '' : 's'}</span>` : '',
      ].filter(Boolean).join('');
      return `<button type="button" class="guidance-idx-row rec-${lv}${selected ? ' selected' : ''}${resolved ? ' resolved' : ''}${live ? ' is-live' : ''}" data-guidance-pick="${esc(sid)}" id="guidance-pick-${esc(sid)}" aria-label="${esc(h.title)}">
        <span class="guidance-idx-sev" aria-hidden="true"></span>
        <span class="guidance-idx-main">
          <span class="guidance-idx-title">${esc(h.title)}</span>
          ${why ? `<span class="guidance-idx-why">${esc(why)}</span>` : ''}
          <span class="guidance-idx-tags">${tags}</span>
        </span>
      </button>`;
    }

    function guidanceScanIndexRowHtml(f, selected) {
      const lv = f.severity || 'info';
      const pickId = guidanceScanPickId(f);
      const why = (f.text || '').trim();
      const tags = [
        guidanceSevTag(lv),
        '<span class="guidance-tag">Scan</span>',
      ].join('');
      return `<button type="button" class="guidance-idx-row guidance-idx-scan rec-${lv}${selected ? ' selected' : ''}" data-guidance-pick="${esc(pickId)}" id="guidance-pick-${esc(pickId)}" aria-label="${esc(f.title)}">
        <span class="guidance-idx-sev" aria-hidden="true"></span>
        <span class="guidance-idx-main">
          <span class="guidance-idx-title">${esc(f.title)}</span>
          ${why ? `<span class="guidance-idx-why">${esc(why)}</span>` : ''}
          <span class="guidance-idx-tags">${tags}</span>
        </span>
      </button>`;
    }

    function getScanIndexGroup() {
      if (!lastGuidanceScanFindings.length) return null;
      return { key: 'scan', label: 'System scan', hints: lastGuidanceScanFindings, isScan: true };
    }

    function renderGuidanceFilters() {
      const el = document.getElementById('guidanceIndexFilterChips');
      if (!el) return;
      const c = guidanceSectionCounts;
      const liveN = (lastGuidanceSummaryHints || []).filter(h => h.condition_live && hintUserStatus(h) === 'outstanding').length;
      const allN = (c.steam || 0) + (c.system || 0) + (c.resolutions || 0);
      const filters = [
        { key: 'all', label: 'All issues', n: allN || null, always: true },
        { key: 'live', label: 'Live now', n: liveN, always: liveN > 0 },
        { key: 'steam', label: 'Steam', n: c.steam, hot: c.steam_hot },
        { key: 'system', label: 'Performance', n: c.system, hot: c.system_hot },
        { key: 'resolutions', label: 'Tips', n: c.resolutions, hot: c.resolutions_hot },
        // Scan stays available after first run even when quiet
        { key: 'scan', label: 'System scan', n: c.scan, hot: c.scan_hot, always: c.scan_always },
        { key: 'fixed', label: 'Fixed', n: c.fixed },
      ].filter(f => f.key === 'all' || f.always || (f.n || 0) > 0);
      el.innerHTML = filters.map(f => {
        const cls = ['btn', guidanceIndexFilter === f.key ? 'active' : ''].filter(Boolean).join(' ');
        const hotDot = f.hot ? '<span class="guidance-filter-hot" aria-hidden="true"></span>' : '';
        const count = (f.n != null && f.n > 0) ? `<span class="n">${f.n}</span>` : '';
        return `<button type="button" class="${cls}" data-guidance-filter="${f.key}">${hotDot}${f.label}${count}</button>`;
      }).join('');
      el.querySelectorAll('[data-guidance-filter]').forEach(btn => {
        btn.onclick = () => {
          guidanceIndexFilter = btn.dataset.guidanceFilter;
          renderGuidanceFilters();
          renderGuidanceHero(lastGuidanceSummaryHints);
          renderGuidanceIndex(lastGuidanceIndexGroups, lastGuidanceFixedHints, lastSelectedGuidanceId);
          selectGuidanceHint(lastSelectedGuidanceId, { scroll: false });
        };
      });
    }

    let lastGuidanceIndexGroups = [];
    let lastGuidanceFixedHints = [];

    function renderGuidanceIndex(groups, fixedHints, selectedId) {
      lastGuidanceIndexGroups = groups;
      lastGuidanceFixedHints = fixedHints;
      const listEl = document.getElementById('guidanceIndexList');
      if (!listEl) return;

      const scanGroup = getScanIndexGroup();
      let visibleGroups = groups.filter(g => g.hints.length);
      if (guidanceIndexFilter === 'fixed') {
        visibleGroups = fixedHints.length
          ? [{ key: 'fixed', label: 'Marked fixed', hints: sortGuidanceHints(fixedHints), isScan: false }]
          : [];
      } else if (guidanceIndexFilter === 'scan') {
        visibleGroups = scanGroup ? [scanGroup] : [];
      } else if (guidanceIndexFilter === 'live') {
        visibleGroups = visibleGroups
          .map(g => ({
            ...g,
            hints: sortGuidanceHints(g.hints.filter(h => h.condition_live && hintUserStatus(h) === 'outstanding')),
            isScan: false,
          }))
          .filter(g => g.hints.length);
      } else if (guidanceIndexFilter === 'hot' || guidanceIndexFilter === 'warn' || guidanceIndexFilter === 'info') {
        const want = guidanceIndexFilter;
        visibleGroups = visibleGroups
          .map(g => ({
            ...g,
            hints: sortGuidanceHints(g.hints.filter(h => (h.level || 'info') === want)),
            isScan: false,
          }))
          .filter(g => g.hints.length);
        // Include matching scan findings under severity filters
        if (scanGroup) {
          const scanHits = scanGroup.hints.filter(f => (f.severity || 'info') === want);
          if (scanHits.length) {
            visibleGroups.push({ key: 'scan', label: 'System scan', hints: scanHits, isScan: true });
          }
        }
      } else if (guidanceIndexFilter !== 'all') {
        visibleGroups = visibleGroups
          .filter(g => g.key === guidanceIndexFilter)
          .map(g => ({ ...g, hints: sortGuidanceHints(g.hints), isScan: false }));
      } else {
        visibleGroups = visibleGroups.map(g => ({ ...g, hints: sortGuidanceHints(g.hints), isScan: false }));
        if (scanGroup) visibleGroups.push(scanGroup);
        if (visibleGroups.length > 1) visibleGroups = sortGuidanceGroups(visibleGroups);
      }

      if (guidanceGameFilter && guidanceIndexFilter !== 'scan') {
        visibleGroups = visibleGroups
          .filter(g => !g.isScan)
          .map(g => ({
            ...g,
            hints: g.hints.filter(h => hintMatchesGameFilter(h, guidanceGameFilter)),
          }))
          .filter(g => g.hints.length);
        if (guidanceIndexFilter === 'all' && scanGroup) visibleGroups.push(scanGroup);
      }

      guidancePickableHints = visibleGroups.filter(g => !g.isScan).flatMap(g => g.hints);
      if (guidanceIndexFilter === 'fixed') {
        guidancePickableHints = fixedHints.slice();
      }

      if (!visibleGroups.length) {
        let title = 'Nothing here';
        let body = 'Try another filter, or run <strong>Scan system</strong>.';
        if (guidanceIndexFilter === 'scan') {
          if (diagCache?.job?.running || diagCache?.pending) {
            title = 'Scanning…';
            body = 'Checking journals, Steam logs, libraries, and Vulkan.';
          } else if (diagHasScanned || diagCache?.scanned_at) {
            title = 'Scan is clean';
            body = 'No actionable system findings right now.';
          } else {
            title = 'No scan yet';
            body = 'Press <strong>Scan system</strong> when something feels wrong.';
          }
        } else if (guidanceIndexFilter === 'live') {
          title = 'Nothing live';
          body = 'No issues firing right this second. Outstanding items may still need attention.';
        } else if (guidanceIndexFilter === 'fixed') {
          title = 'No fixed items';
          body = 'Mark something fixed from the detail pane and it shows up here.';
        } else if (!lastGuidanceSummaryHints?.length && !lastGuidanceScanFindings.length) {
          title = 'All clear';
          body = 'No outstanding recommendations. Run a system scan anytime for a deeper check.';
        }
        listEl.innerHTML = `<div class="guidance-index-empty"><strong>${title}</strong>${body}</div>`;
        lastSelectedGuidanceId = null;
        renderGuidanceDetail(null);
        return;
      }

      const visiblePicks = visibleGroups.flatMap(g =>
        g.isScan ? g.hints.map(f => guidanceScanPickId(f)) : g.hints.map(h => h.insight_id),
      );
      const allHintIds = new Set([
        ...groups.flatMap(g => g.hints.map(h => h.insight_id)),
        ...fixedHints.map(h => h.insight_id),
        ...(scanGroup ? scanGroup.hints.map(f => guidanceScanPickId(f)) : []),
      ]);
      let activeId = selectedId;
      const selectedStillExists = activeId && allHintIds.has(activeId);
      if (!activeId || (!visiblePicks.includes(activeId) && !selectedStillExists)) {
        activeId = visiblePicks[0] || null;
        lastSelectedGuidanceId = activeId;
      } else if (selectedStillExists) {
        lastSelectedGuidanceId = activeId;
      }

      const showGroupLabels = guidanceIndexFilter === 'all' && visibleGroups.length > 1;
      listEl.innerHTML = visibleGroups.map(g => {
        const label = showGroupLabels
          ? `<div class="guidance-idx-group-label" id="guidanceGroup-${g.key}">${g.label}</div>`
          : '';
        const rows = g.isScan
          ? g.hints.map(f => guidanceScanIndexRowHtml(f, guidanceScanPickId(f) === activeId)).join('')
          : g.hints.map(h => guidanceIndexRowHtml(h, h.insight_id === activeId)).join('');
        return label + rows;
      }).join('');

      listEl.querySelectorAll('[data-guidance-pick]').forEach(btn => {
        btn.onclick = () => selectGuidanceHint(btn.dataset.guidancePick, { scroll: false });
      });
    }

    function renderGuidanceScanDetail(f) {
      const empty = document.getElementById('guidanceDetailEmpty');
      const card = document.getElementById('guidanceDetailCard');
      if (!empty || !card) return;
      if (!f) {
        empty.hidden = false;
        empty.innerHTML = `
          <span class="gd-empty-icon" aria-hidden="true"></span>
          <strong>Select a recommendation</strong>
          Why it matters and what to do show here.`;
        card.innerHTML = '';
        return;
      }
      empty.hidden = true;
      const hint = (f.primary_hint || '').trim();
      const fix = (f.fix || '').trim();
      // What to do first — never bury copy-paste under a log dump
      const primaryBlock = (hint || fix) ? `
        <div class="diag-primary">
          <span class="diag-primary-label">What to do</span>
          ${hint ? `<p class="diag-primary-text">${esc(hint)}</p>` : ''}
          ${fix ? `<div class="diag-fix"><code>${esc(fix)}</code><button class="copy-btn" type="button" data-copy="${esc(fix)}">Copy command</button></div>` : ''}
        </div>` : '';
      card.innerHTML = `
        <article class="diag-scan diag-item ${f.severity}">
          <div class="diag-head">
            <span class="diag-cat">${DIAG_CAT_LABEL[f.category] || f.category || 'Scan'}</span>
            ${sevBadge(f.severity, SEV_LABEL[f.severity] || f.severity)}
            <h3 class="diag-title">${esc(f.title)}</h3>
          </div>
          ${primaryBlock}
          <div class="rec-section rec-why">
            <h4 class="rec-section-title">Why it matters</h4>
            <p class="diag-body">${esc(f.text)}</p>
          </div>
          ${guidanceScanEvidenceHtml(f)}
        </article>`;
      card.querySelectorAll('.diag-fix .copy-btn').forEach(btn => {
        btn.onclick = () => copyText(btn.dataset.copy, btn);
      });
    }

    function renderGuidanceDetail(h) {
      const empty = document.getElementById('guidanceDetailEmpty');
      const card = document.getElementById('guidanceDetailCard');
      if (!empty || !card) return;
      if (!h) {
        const clear = !(lastGuidanceSummaryHints || []).length && !lastGuidanceScanFindings.length;
        empty.hidden = false;
        empty.innerHTML = clear
          ? `<span class="gd-empty-icon" aria-hidden="true"></span>
             <strong>You're in good shape</strong>
             No outstanding recommendations. Run <em>Scan system</em> if something feels off.`
          : `<span class="gd-empty-icon" aria-hidden="true"></span>
             <strong>Select a recommendation</strong>
             Why it matters and what to do show here.`;
        card.innerHTML = '';
        return;
      }
      empty.hidden = true;
      card.innerHTML = recCardHtml(h, 'detail-');
      bindHintActions(card, [h]);
    }

    function selectGuidanceHint(insightId, { scroll = false } = {}) {
      lastSelectedGuidanceId = insightId || null;
      document.querySelectorAll('.guidance-idx-row').forEach(row => {
        row.classList.toggle('selected', row.dataset.guidancePick === insightId);
      });
      if (insightId?.startsWith('diag:')) {
        const fid = insightId.slice(5);
        const f = lastGuidanceScanFindings.find(x => x.id === fid);
        renderGuidanceScanDetail(f);
        if (scroll && insightId) {
          document.getElementById(`guidance-pick-${insightId}`)
            ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
        return;
      }
      const fullPool = lastGuidanceIndexGroups.flatMap(g => g.hints).concat(lastGuidanceFixedHints);
      const h = hintById(guidancePickableHints, insightId)
        || hintById(fullPool, insightId)
        || hintById(lastGuidanceFixedHints, insightId);
      renderGuidanceDetail(h);
      if (scroll && insightId) {
        document.getElementById(`guidance-pick-${insightId}`)
          ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }

    function renderGuidanceHero(issues) {
      if (issues) lastGuidanceSummaryHints = issues;
      issues = lastGuidanceSummaryHints || [];
      const open = guidanceOpenCounts(issues);
      const hot = open.hot;
      const warn = open.warn;
      const info = open.info;
      const liveN = open.live;
      const total = open.total;

      const hero = document.getElementById('guidanceHero');
      const titleEl = document.getElementById('guidanceHeroTitle');
      const subEl = document.getElementById('guidanceHeroSub');
      const statsEl = document.getElementById('guidanceHeroStats');
      if (!hero || !titleEl || !subEl || !statsEl) return;

      let health = 'ok';
      let title = 'All clear';
      let sub = 'Nothing outstanding. Optional system scan is available anytime.';
      if (hot > 0) {
        health = 'hot';
        title = hot === 1 ? '1 critical issue' : `${hot} critical issues`;
        sub = 'Handle critical items first — they usually block smooth play.';
      } else if (warn > 0) {
        health = 'warn';
        title = warn === 1 ? '1 item needs attention' : `${warn} items need attention`;
        sub = info
          ? `${warn} important · ${info} moderate`
          : 'Review important items when you have a moment.';
      } else if (total > 0) {
        health = 'ok';
        title = total === 1 ? '1 optional tip' : `${total} optional tips`;
        sub = 'No critical problems — tips only.';
      }
      if (liveN > 0) {
        sub += ` · <span class="live-count">${liveN} live now</span>`;
      }
      hero.dataset.health = health;
      titleEl.textContent = title;
      subEl.innerHTML = sub;

      const stats = [
        { key: 'hot', n: hot, label: 'Critical', cls: 'hot' },
        { key: 'warn', n: warn, label: 'Important', cls: 'warn' },
        { key: 'info', n: info, label: 'Moderate', cls: 'info' },
        { key: 'live', n: liveN, label: 'Live now', cls: 'live' },
      ];
      statsEl.innerHTML = stats.map(s => {
        const active = guidanceIndexFilter === s.key ? ' is-active' : '';
        return `<button type="button" class="guidance-stat ${s.cls}${active}" data-guidance-sev="${s.key}" title="Show ${s.label.toLowerCase()}">
          <span class="n">${s.n}</span>
          <span class="lbl">${s.label}</span>
        </button>`;
      }).join('');
      statsEl.querySelectorAll('[data-guidance-sev]').forEach(btn => {
        btn.onclick = () => {
          const key = btn.dataset.guidanceSev;
          // Toggle: click active severity → back to all
          guidanceIndexFilter = guidanceIndexFilter === key ? 'all' : key;
          renderGuidanceFilters();
          renderGuidanceHero(lastGuidanceSummaryHints);
          renderGuidanceIndex(lastGuidanceIndexGroups, lastGuidanceFixedHints, lastSelectedGuidanceId);
          selectGuidanceHint(lastSelectedGuidanceId, { scroll: false });
        };
      });
    }

    function updateGuidanceHeadStat(issues) {
      // Back-compat name used by renderFixes / patch path
      renderGuidanceHero(issues);
    }

    function guidanceOutstanding(hints) {
      return (hints || []).filter(h => hintUserStatus(h) === 'outstanding');
    }

    function guidanceOpenCounts(hints) {
      const outstanding = guidanceOutstanding(hints);
      const scan = lastGuidanceScanFindings || [];
      const hot = outstanding.filter(h => h.level === 'hot').length
        + scan.filter(f => f.severity === 'hot').length;
      const warn = outstanding.filter(h => h.level === 'warn').length
        + scan.filter(f => f.severity === 'warn').length;
      const info = outstanding.filter(h => h.level === 'info' || !h.level).length
        + scan.filter(f => f.severity === 'info' || !f.severity).length;
      return {
        hot,
        warn,
        info,
        live: outstanding.filter(h => h.condition_live).length,
        cards: outstanding.length,
        scan: scan.length,
        total: outstanding.length + scan.length,
      };
    }

    function guidanceLiveOutstanding(hints) {
      return guidanceOutstanding(hints).filter(h => h.condition_live);
    }

    function guidanceResolved(hints) {
      return (hints || []).filter(h => hintUserStatus(h) === 'resolved');
    }

    function guidanceSummaryHints(hints) {
      return guidanceOutstanding(hints).filter(h => h.level !== 'ok');
    }

    const WARNING_LIVE_DWELL_SEC = 45;
    const warningLiveDwellUntil = new Map();

    function warningsForDisplay(hints) {
      const now = Date.now() / 1000;
      const outstanding = guidanceOutstanding(hints).filter(h =>
        h.level !== 'ok' && !isInsightSuppressed(h.insight_id),
      );
      const validIds = new Set(outstanding.map(h => h.insight_id).filter(Boolean));
      for (const id of warningLiveDwellUntil.keys()) {
        if (!validIds.has(id)) warningLiveDwellUntil.delete(id);
      }
      for (const h of outstanding) {
        if (h.condition_live && h.insight_id) {
          warningLiveDwellUntil.set(h.insight_id, now + WARNING_LIVE_DWELL_SEC);
        }
      }
      return outstanding.filter(h => {
        if (h.condition_live) return true;
        const until = warningLiveDwellUntil.get(h.insight_id);
        return until != null && until > now;
      });
    }

    function warningsLayoutKey(hints) {
      return JSON.stringify((hints || []).map(h => [h.insight_id, h.level, h.title, h.text]));
    }

    function warningPriority(h) {
      if (h.priority_score != null) return h.priority_score;
      return { hot: 100, warn: 70, info: 40 }[h.level] ?? 40;
    }

    function sortWarningsByPriority(hints) {
      return [...hints].sort((a, b) => {
        const ps = warningPriority(b) - warningPriority(a);
        if (ps) return ps;
        return (b.last_seen || 0) - (a.last_seen || 0);
      });
    }

    function warningsWidgetData(hints) {
      const all = sortWarningsByPriority(warningsForDisplay(hints));
      return { all, shown: all.slice(0, WARN_WIDGET_MAX), total: all.length };
    }

    function hintForActiveGame(h, gameId) {
      if (!gameId) return false;
      if ((h.games_affected || []).includes(gameId)) return true;
      const scope = h.games || ['all'];
      return scope.includes('all') || scope.includes(gameId);
    }

    function activeGameName(gt, catalog) {
      if (!gt?.running) return null;
      return gt.primary_name || gt.game_name || catalog?.[gt.game_id]?.name || null;
    }

    function updateGameContext(s, l) {
      const gt = l?.game_totals || {};
      const catalog = s?.games_catalog || {};
      const gid = gt.running ? gt.game_id : null;
      const short = gid ? gameLabel(gid) : 'Game';

      const sumLbl = document.getElementById('sumGameLabel');
      if (sumLbl) sumLbl.textContent = gt.running ? short : 'Game';

      const gameDef = utilDefs.find(d => d.key === 'gameCpu');
      if (gameDef) {
        gameDef.label = gt.running ? short : 'Game process';
        const chip = document.querySelector('.chip[data-g="util"][data-k="gameCpu"]');
        if (chip) chip.textContent = gameDef.label;
      }

      const ctx = document.getElementById('warnGameCtx');
      if (ctx) {
        if (gid) {
          const name = activeGameName(gt, catalog) || short;
          const switched = lastActiveGameId && lastActiveGameId !== gid;
          ctx.hidden = false;
          ctx.textContent = switched ? `Now monitoring ${name}` : `Monitoring ${name}`;
          ctx.classList.toggle('warn-session-switch', switched);
        } else {
          ctx.hidden = true;
          ctx.textContent = '';
          ctx.classList.remove('warn-session-switch');
        }
      }

      if (gid) lastActiveGameId = gid;
    }

    function gameTag(h) {
      const ids = h.games_affected || [];
      if (!ids.length) return '';
      const names = ids.map(gameLabel);
      const label = h.multi_game
        ? (names.length <= 2 ? names.join(' + ') : `${names.length} games`)
        : names[0];
      return `<span class="rec-game" title="Seen in: ${esc(names.join(', '))}">${hwIcon('game', 'hw-pill-glyph')}${esc(label)}</span>`;
    }

    function hintById(list, iid) {
      return (list || []).find(h => h.insight_id === iid);
    }

    /** Shell / Steam launch lines are copyable. Notes and in-game UI steps are not commands. */
    function actionKind(a) {
      return String(a?.kind || (a?.cmd ? 'cmd' : 'note')).toLowerCase();
    }
    function actionIsCopyable(a) {
      const k = actionKind(a);
      return !!(a?.cmd && (k === 'cmd' || k === 'steam'));
    }
    function actionIsShell(a) {
      return !!(a?.cmd && actionKind(a) === 'cmd');
    }

    function recCardHtml(h, idPrefix = '', rank = 0) {
      const isDetail = idPrefix === 'detail-';
      const lv = h.level || 'info';
      const status = hintUserStatus(h);
      const resolved = status === 'resolved';
      const outstanding = status === 'outstanding';
      const sid = h.insight_id || 'insight';
      const domId = `${idPrefix}insight-${sid}`;
      const suppressed = isInsightSuppressed(sid);
      const rankBadge = rank ? `<span class="rec-rank">#${rank}</span>` : '';
      const when = h.last_seen ? `Last seen ${fmtAgo(h.last_seen)}` : '';
      const statusBadge = resolved
        ? '<span class="rec-status resolved">Fixed</span>'
        : h.condition_live
          ? '<span class="rec-status live">Live now</span>'
          : '<span class="rec-status outstanding">Outstanding</span>';
      const markFixedBtn = outstanding
        ? `<button class="btn warn-hide" type="button" data-resolve-iid="${esc(sid)}" title="Mark as fixed">Mark fixed</button>`
        : '';
      const ignoreBtn = outstanding && !suppressed
        ? `<button class="btn warn-hide" type="button" data-hide-iid="${esc(sid)}" title="Ignore — hide from dashboard and Guidance">Ignore</button>`
        : '';
      const reopenBtn = resolved
        ? `<button class="btn warn-hide" type="button" data-reopen-iid="${esc(sid)}" title="Move back to outstanding">Reopen</button>`
        : '';
      const headActions = `${markFixedBtn}${ignoreBtn}${reopenBtn}`;
      const actions = h.actions || [];
      const hasShell = actions.some(actionIsShell);
      const steps = actions.map((a, ai) => {
        const copyable = actionIsCopyable(a);
        const body = a.cmd
          ? (copyable ? `<code>${esc(a.cmd)}</code>` : `<div class="rec-step-do">${esc(a.cmd)}</div>`)
          : '';
        return `
        <div class="rec-step${copyable ? '' : ' rec-step-manual'}">
          <div class="rec-step-label">${esc(a.label)}</div>
          ${body}
          ${a.note ? `<div class="rec-step-note">${esc(a.note)}</div>` : ''}
          ${copyable ? `<button class="copy-btn" type="button" data-iid="${esc(sid)}" data-a="${ai}">Copy</button>` : ''}
        </div>`;
      }).join('');
      const stepCount = actions.length;
      const riskNote = hasShell
        ? `<p class="fix-risk-warn">Review each command before pasting into a terminal.</p>`
        : '';
      const stepsBlock = steps ? (isDetail ? `
        <div class="rec-section" style="order:1">
          <h4 class="rec-section-title">What to do${stepCount ? ` · ${stepCount}` : ''}</h4>
          ${riskNote}
          ${h.requires_root ? '<p class="fix-root-note">Some steps need sudo.</p>' : ''}
          <div class="rec-steps rec-steps-open">${steps}</div>
        </div>` : `
        <details class="rec-more" data-open-key="hint-${domId}-steps">
          <summary>${stepCount} steps</summary>
          <div class="rec-steps">${steps}</div>
        </details>`) : '';
      const whyBlock = isDetail
        ? `<div class="rec-section rec-why" style="order:2">
            <h4 class="rec-section-title">Why it matters</h4>
            <p class="rec-body">${esc(h.text)}</p>
            ${when ? `<p class="rec-meta" data-rec-meta>${when}</p>` : ''}
          </div>`
        : `<p class="rec-body">${esc(h.text)}</p>${when ? `<p class="rec-meta" data-rec-meta>${when}</p>` : ''}`;
      const detailHead = isDetail
        ? `<header class="rec-head" style="order:0">
            ${statusBadge}
            ${sevBadge(lv, SEV_LABEL[lv] || lv)}
            ${gameTag(h)}
            ${headActions ? `<span class="rec-actions-head">${headActions}</span>` : ''}
            <h3 class="rec-title">${esc(h.title)}</h3>
          </header>`
        : `<header class="rec-head">
            ${rankBadge}
            ${statusBadge}
            ${sevBadge(lv, SEV_LABEL[lv] || lv)}
            ${gameTag(h)}
            <h3 class="rec-title">${esc(h.title)}</h3>
            ${headActions ? `<span class="rec-actions-head">${headActions}</span>` : ''}
          </header>`;
      // Detail: title → steps (copyable) → why. No fix scripts.
      return `<article class="rec-card rec-${lv}${resolved ? ' rec-stale' : ''}" data-level="${lv}" data-iid="${esc(sid)}" id="${domId}">
        ${detailHead}
        ${isDetail ? `${stepsBlock}${whyBlock}` : `${whyBlock}${stepsBlock}`}
      </article>`;
    }

    function bindHintActions(el, list) {
      el.querySelectorAll('.copy-btn[data-iid]').forEach(btn => {
        const h = hintById(list, btn.dataset.iid);
        const a = h?.actions?.[+btn.dataset.a];
        if (actionIsCopyable(a)) btn.onclick = () => copyText(a.cmd, btn);
      });
      el.querySelectorAll('.copy-btn').forEach(btn => {
        btn.addEventListener('click', e => e.stopPropagation());
      });
      el.querySelectorAll('.warn-hide[data-hide-iid]').forEach(btn => {
        btn.onclick = e => {
          e.stopPropagation();
          suppressInsight(btn.dataset.hideIid);
        };
      });
      el.querySelectorAll('[data-resolve-iid]').forEach(btn => {
        btn.onclick = e => {
          e.stopPropagation();
          resolveInsight(btn.dataset.resolveIid);
        };
      });
      el.querySelectorAll('[data-reopen-iid]').forEach(btn => {
        btn.onclick = e => {
          e.stopPropagation();
          reopenInsight(btn.dataset.reopenIid);
        };
      });
    }

    function warningRowHtml(h) {
      const lv = h.level || 'info';
      const sid = h.insight_id || 'insight';
      const domId = `insight-${sid}`;
      const hwTags = hintHwFocus(h).join(' ');
      const sessionCls = lastActiveGameId && hintForActiveGame(h, lastActiveGameId) ? ' warn-row-session' : '';
      const game = gameTag(h);
      const hideBtn = lv === 'info'
        ? `<button class="btn warn-hide" type="button" data-hide-iid="${esc(sid)}" title="Ignore this issue">Ignore</button>`
        : '';
      return `<div class="warn-row rec-${lv}${sessionCls}" data-iid="${esc(sid)}" data-hw="${esc(hwTags)}" id="warn-${domId}">
        <div class="warn-row-top">
          <div class="warn-row-badges">${sevBadge(lv, SEV_LABEL[lv] || lv)}${game}</div>
          <h4 class="warn-title">${esc(h.title)}</h4>
          <button class="btn warn-go" type="button" data-goto-fix="${esc(sid)}">See Details</button>${hideBtn}
        </div>
        <p class="warn-text">${esc(h.text)}</p>
      </div>`;
    }

    async function postInsightAction(body) {
      const res = await fetch('/api/store', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      return res.json();
    }

    function refreshHintStatuses(hints) {
      return (hints || []).map(h => {
        const iid = h.insight_id;
        const user_status = isInsightSuppressed(iid) ? 'ignored'
          : isInsightResolved(iid) ? 'resolved' : 'outstanding';
        return { ...h, user_status, active: user_status === 'outstanding' };
      });
    }

    function applyInsightConfig(data) {
      if (!data?.ok || !lastStatic) return false;
      lastStatic.suppressed_insights = data.suppressed_insights || [];
      lastStatic.resolved_insights = data.resolved_insights || [];
      lastWarningsHints = refreshHintStatuses(lastWarningsHints);
      lastFixesKey = '';
      lastGameIssuesKey = '';
      renderWarnings(lastWarningsHints);
      renderFixes(lastWarningsHints);
      renderSummaryBar(lastLatest, lastWarningsHints, lastComparison);
      updateWarningsFocusUI();
      return true;
    }

    async function suppressInsight(insightId) {
      if (!insightId) return;
      try {
        applyInsightConfig(await postInsightAction({ suppress_insight: insightId }));
      } catch (_) { /* ignore */ }
    }

    async function resolveInsight(insightId) {
      if (!insightId) return;
      try {
        applyInsightConfig(await postInsightAction({ resolve_insight: insightId }));
      } catch (_) { /* ignore */ }
    }

    async function reopenInsight(insightId) {
      if (!insightId) return;
      try {
        applyInsightConfig(await postInsightAction({ unresolve_insight: insightId }));
      } catch (_) { /* ignore */ }
    }

    function bindWarningActions(list) {
      document.querySelectorAll('.warn-go[data-goto-fix]').forEach(btn => {
        btn.onclick = () => {
          const sid = btn.dataset.gotoFix;
          setTab('fixes', `insight-${sid}`);
        };
      });
      document.querySelectorAll('.warn-hide[data-hide-iid]').forEach(btn => {
        btn.onclick = e => {
          e.stopPropagation();
          suppressInsight(btn.dataset.hideIid);
        };
      });
      const warnGuide = document.getElementById('warnGuidanceLink');
      if (warnGuide) warnGuide.onclick = () => setTab('fixes', 'insightsSection');
    }

    function updateWarningsMoreLink(total) {
      const wrap = document.getElementById('warnMoreFixes');
      const btn = document.getElementById('warnMoreFixesBtn');
      if (!wrap || !btn) return;
      if (!total) {
        wrap.hidden = true;
        return;
      }
      wrap.hidden = false;
      const extra = total - WARN_WIDGET_MAX;
      btn.textContent = extra > 0
        ? `View all ${total} issues in Guidance →`
        : 'Open Guidance for scripts and step-by-step help →';
    }

    function renderWarnings(hints) {
      const list = hints || [];
      lastWarningsHints = list;
      const { all, shown, total } = warningsWidgetData(list);
      const layoutKey = warningsLayoutKey(shown);

      const listEl = document.getElementById('warningList');
      if (layoutKey !== lastWarningsKey) {
        lastWarningsKey = layoutKey;
        capturePanelState();
        listEl.innerHTML = shown.length
          ? shown.map(h => warningRowHtml(h)).join('')
          : `<div class="warn-empty warn-clear-state">
              <span class="hw-icon-box health" data-glyph="ok"></span>
              <div>
                <strong>No outstanding issues</strong>
                <p>Your rig looks good. <button type="button" class="warn-clear-link" id="warnGuidanceLink">Open Guidance</button> for steps, commands, and scans.</p>
              </div>
            </div>`;
        bindWarningActions(shown);
        restorePanelState();
      }
      updateWarningsMoreLink(total);
      updateWarningsFocusUI();
    }

    /** Guidance index: all outstanding hints (not live-only). Rebuild on layoutKey change only. */
    function renderFixes(hints) {
      const list = hints || [];
      const outstanding = guidanceOutstanding(list);
      const fixed = guidanceResolved(list);
      const resolutionHints = sortGuidanceHints(
        outstanding.filter(h => h.bucket === 'resolutions' && h.level !== 'ok'),
      );
      const priorityPool = outstanding.filter(h => h.bucket !== 'resolutions');
      const priority = sortGuidanceHints(priorityPool.filter(h => h.level !== 'ok'));
      const okOnly = priorityPool.filter(h => h.level === 'ok');
      const steamPriority = priority.filter(h => guidanceCategory(h) === 'steam');
      const systemPriority = priority.filter(h => guidanceCategory(h) === 'system');
      const steamOk = okOnly.filter(h => guidanceCategory(h) === 'steam');
      const systemOk = okOnly.filter(h => guidanceCategory(h) === 'system');
      const steamDisplay = steamPriority.length ? steamPriority : steamOk;
      const systemDisplay = systemPriority.length ? systemPriority : systemOk;
      const layoutKey = hintsLayoutKey(list) + '|' + suppressedInsights().join(',') + '|' + resolvedInsights().join(',');
      const summaryHints = guidanceSummaryHints(list);
      const indexGroups = [
        { key: 'steam', label: 'Steam', hints: steamDisplay },
        { key: 'system', label: 'Performance', hints: systemDisplay },
        { key: 'resolutions', label: 'Resolutions', hints: resolutionHints },
      ].map(g => ({
        ...g,
        hints: sortGuidanceHints(
          g.hints.filter(h => h.level !== 'ok').length ? g.hints.filter(h => h.level !== 'ok') : g.hints,
        ),
      })).filter(g => g.hints.length);

      if (layoutKey === lastFixesKey) {
        patchGuidanceLiveState(list);
        updateRecMetas(list);
        updateGuidanceHeadStat(summaryHints);
        return;
      }
      lastFixesKey = layoutKey;
      capturePanelState();
      updateGuidanceHeadStat(summaryHints);

      const countHot = (arr) => arr.filter(h => h.level === 'hot').length;
      guidanceSectionCounts.steam = guidanceHintCount(steamDisplay);
      guidanceSectionCounts.steam_hot = countHot(steamPriority) > 0;
      guidanceSectionCounts.system = guidanceHintCount(systemDisplay);
      guidanceSectionCounts.system_hot = countHot(systemPriority) > 0;
      guidanceSectionCounts.resolutions = resolutionHints.length;
      guidanceSectionCounts.resolutions_hot = countHot(resolutionHints) > 0;
      guidanceSectionCounts.fixed = fixed.length;

      const pickable = indexGroups.flatMap(g => g.hints);
      const scanPickable = lastGuidanceScanFindings.map(f => guidanceScanPickId(f));
      const allKnownIds = new Set([
        ...outstanding.map(h => h.insight_id),
        ...fixed.map(h => h.insight_id),
        ...scanPickable,
      ]);
      const stillSelected = lastSelectedGuidanceId?.startsWith('diag:')
        ? scanPickable.includes(lastSelectedGuidanceId)
        : allKnownIds.has(lastSelectedGuidanceId);
      if (!lastSelectedGuidanceId || !stillSelected) {
        lastSelectedGuidanceId = pickable[0]?.insight_id || scanPickable[0] || null;
      }
      if (guidanceIndexFilter === 'fixed' && !fixed.length) {
        guidanceIndexFilter = 'all';
      }

      renderGuidanceFilters();
      renderGuidanceIndex(indexGroups, fixed, lastSelectedGuidanceId);
      selectGuidanceHint(lastSelectedGuidanceId, { scroll: false });

      restorePanelState();
    }

    function patchIssuesRunning(byGame, games) {
      if (!byGame) return byGame;
      const running = new Set(
        Object.entries(games || {}).filter(([, g]) => g?.running).map(([id]) => id),
      );
      const out = {};
      for (const [gid, block] of Object.entries(byGame)) {
        const entry = { ...block, running: running.has(gid) };
        if (entry.issue_count > 0 || entry.running) out[gid] = entry;
      }
      return out;
    }

    async function refreshIssuesByGame(tuningHints) {
      const key = hintsStructKey(tuningHints);
      if (key === lastIssuesFetchKey && cachedIssuesByGame) return cachedIssuesByGame;
      try {
        const res = await fetch('/api/issues-by-game');
        const data = await res.json();
        cachedIssuesByGame = data.issues_by_game || {};
        lastIssuesFetchKey = key;
      } catch (_) { /* keep cached snapshot */ }
      return cachedIssuesByGame;
    }

    let lastGuidanceGameBlocks = [];
    let guidanceGameMenuOpen = false;
    let guidanceGamePickerBound = false;

    function setGuidanceGameMenuOpen(open) {
      guidanceGameMenuOpen = !!open;
      const trigger = document.getElementById('guidanceGameTrigger');
      const menu = document.getElementById('guidanceGameMenu');
      if (!trigger || !menu) return;
      trigger.classList.toggle('open', guidanceGameMenuOpen);
      trigger.setAttribute('aria-expanded', guidanceGameMenuOpen ? 'true' : 'false');
      menu.hidden = !guidanceGameMenuOpen;
    }

    function guidanceGameMenuItemHtml(g) {
      const isAll = !g;
      const pick = isAll ? '' : g.id;
      const selected = (guidanceGameFilter || '') === pick;
      const label = isAll ? 'All games' : g.name;
      const dot = (!isAll && g.running)
        ? '<span class="guidance-game-menu-dot" title="Running now" aria-hidden="true"></span>' : '';
      const count = (!isAll && g.issue_count > 0)
        ? `<span class="guidance-game-menu-count">${g.issue_count}</span>` : '';
      return `<button type="button" class="guidance-game-menu-item${selected ? ' selected' : ''}" role="option" aria-selected="${selected}" data-game-filter="${esc(pick)}">
        <span class="guidance-game-menu-check" aria-hidden="true">✓</span>
        <span class="guidance-game-menu-label">${esc(label)}</span>
        <span class="guidance-game-menu-meta">${dot}${count}</span>
      </button>`;
    }

    function renderGuidanceGameMenu(games) {
      const menu = document.getElementById('guidanceGameMenu');
      if (!menu) return;
      menu.innerHTML = [
        guidanceGameMenuItemHtml(null),
        games.length ? '<div class="guidance-game-menu-divider" role="separator"></div>' : '',
        ...games.map(g => guidanceGameMenuItemHtml(g)),
      ].filter(Boolean).join('');
      menu.querySelectorAll('[data-game-filter]').forEach(btn => {
        btn.onclick = () => {
          guidanceGameFilter = btn.dataset.gameFilter || null;
          setGuidanceGameMenuOpen(false);
          updateGuidanceGamePickerUI(games);
          renderGuidanceIndex(lastGuidanceIndexGroups, lastGuidanceFixedHints, lastSelectedGuidanceId);
        };
      });
    }

    function updateGuidanceGamePickerUI(games) {
      const trigger = document.getElementById('guidanceGameTrigger');
      const labelEl = document.getElementById('guidanceGameTriggerLabel');
      const dotEl = document.getElementById('guidanceGameTriggerDot');
      const countEl = document.getElementById('guidanceGameTriggerCount');
      if (!trigger || !labelEl || !dotEl || !countEl) return;
      const list = games || lastGuidanceGameBlocks || [];
      if (guidanceGameFilter && !list.some(g => g.id === guidanceGameFilter)) {
        guidanceGameFilter = null;
      }
      const active = guidanceGameFilter ? list.find(g => g.id === guidanceGameFilter) : null;
      trigger.classList.toggle('filtered', !!active);
      if (!active) {
        labelEl.textContent = 'All games';
        dotEl.hidden = true;
        countEl.hidden = true;
        trigger.title = 'Show guidance for every game';
        renderGuidanceGameMenu(list);
        return;
      }
      labelEl.textContent = active.name;
      dotEl.hidden = !active.running;
      if (active.issue_count > 0) {
        countEl.textContent = active.issue_count;
        countEl.hidden = false;
      } else {
        countEl.hidden = true;
      }
      trigger.title = `${active.name} — ${active.issue_count} issue${active.issue_count === 1 ? '' : 's'}`;
      renderGuidanceGameMenu(list);
    }

    function bindGuidanceGamePicker() {
      if (guidanceGamePickerBound) return;
      const trigger = document.getElementById('guidanceGameTrigger');
      const wrap = document.querySelector('.guidance-game-picker-wrap');
      if (!trigger || !wrap) return;
      trigger.onclick = (e) => {
        e.stopPropagation();
        setGuidanceGameMenuOpen(!guidanceGameMenuOpen);
        if (guidanceGameMenuOpen) renderGuidanceGameMenu(lastGuidanceGameBlocks);
      };
      document.addEventListener('click', (e) => {
        if (!guidanceGameMenuOpen) return;
        if (!wrap.contains(e.target)) setGuidanceGameMenuOpen(false);
      });
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && guidanceGameMenuOpen) setGuidanceGameMenuOpen(false);
      });
      guidanceGamePickerBound = true;
    }

    function renderGameIssues(byGame) {
      const blocks = Object.values(byGame || {})
        .map(g => {
          const issues = (g.issues || []).filter(h =>
            hintUserStatus(h) === 'outstanding' && h.condition_live,
          );
          return { ...g, issues, issue_count: issues.length };
        })
        .filter(g => g.issue_count > 0 || g.running);
      const structKey = JSON.stringify(blocks.map(g => [g.id, g.running, g.issue_count, hintsStructKey(g.issues)]));
      const withIssues = blocks.filter(g => g.issue_count > 0);
      guidanceSectionCounts.games = withIssues.length;

      const dock = document.getElementById('guidanceGamesDock');
      if (!dock) return;
      if (!withIssues.length) {
        dock.hidden = true;
        lastGuidanceGameBlocks = [];
        guidanceGameFilter = null;
        setGuidanceGameMenuOpen(false);
        return;
      }
      dock.hidden = false;
      bindGuidanceGamePicker();
      lastGuidanceGameBlocks = withIssues;

      if (structKey === lastGameIssuesKey) {
        updateGuidanceGamePickerUI(withIssues);
        return;
      }
      lastGameIssuesKey = structKey;
      updateGuidanceGamePickerUI(withIssues);
      if (guidanceGameMenuOpen) renderGuidanceGameMenu(withIssues);
    }

    function sensorDrillName(s) {
      const byId = {
        cpu_pkg: 'CPU package', ccd1: 'CCD 1', ccd2: 'CCD 2',
        gpu_junc: 'GPU hotspot', gpu_edge: 'GPU edge', gpu_memt: 'VRAM',
        igpu_edge: 'iGPU', wifi: 'WiFi radio',
      };
      if (byId[s.id]) return byId[s.id];
      if (s.id?.startsWith('nvme_')) return shortDriveLabel(s);
      if (s.id?.startsWith('nic_phy')) return 'NIC PHY';
      if (s.id?.startsWith('nic_mac')) return 'NIC MAC';
      return s.label || s.id || 'Sensor';
    }

    function sensorDrillAccent(s) {
      if (/^cpu|^ccd/.test(s.id)) return 'accent-cpu';
      if (/^gpu|^igpu|vram/i.test(`${s.id} ${s.label}`)) return 'accent-gpu';
      if (/^nvme|disk/i.test(s.id)) return 'accent-storage';
      if (/^nic_|^wifi/.test(s.id)) return 'accent-net';
      if (/psi|swap|pgfault|pgmaj|ram_avail|dram/i.test(`${s.id} ${s.label}`)) return 'accent-mem';
      return 'accent-sys';
    }

    function sensorDrillSeverity(s) {
      if (s.kind === 'temp') {
        const isGpuJunc = s.id === 'gpu_junc';
        return isGpuJunc ? gpuJuncUiClass(s.value).trim() : tempClass(s.value);
      }
      if (s.kind === 'psi' && s.value > 20) return 'hot';
      if (s.kind === 'psi' && s.value > 8) return 'warn';
      if (s.kind === 'pct' && s.value >= 85) return 'hot';
      if (s.kind === 'pct' && s.value >= 70) return 'warn';
      return '';
    }

    function sensorDrillValText(s) {
      if (s.value == null || s.value === '') return '—';
      const v = Number(s.value);
      if (s.kind === 'temp') return `${Number.isInteger(v) ? v : v.toFixed(1)}°`;
      if (s.unit === '%' || s.kind === 'psi' || s.kind === 'pct') {
        return `${v >= 100 ? Math.round(v) : (Number.isInteger(v) ? v : v.toFixed(1))}%`;
      }
      return `${s.value}${s.unit || ''}`;
    }

    function sensorDrillUnitText(s) {
      if (s.kind === 'temp') return 'Celsius';
      if (!s.unit || s.unit === '%') return '';
      return s.unit.replace(/^\s*/, '');
    }

    function renderSensorGroups(sensors) {
      if (!isDrillOpen('drill-sensors')) return;
      const sensorKey = JSON.stringify((sensors || []).map(s => [s.id, s.value]));
      if (sensorKey === lastSensorKey) return;
      lastSensorKey = sensorKey;
      const used = new Set();
      const html = [];
      for (const [name, pred] of Object.entries(SENSOR_GROUPS)) {
        const items = (sensors || []).filter(s => !used.has(s.id) && pred(s));
        items.forEach(s => used.add(s.id));
        if (!items.length) continue;
        html.push(`<div class="sensor-group"><h3>${esc(name)}</h3><div class="drill-sensor-grid">${items.map(s => {
          const sev = sensorDrillSeverity(s);
          const unit = sensorDrillUnitText(s);
          return `<div class="drill-sensor-card ${sensorDrillAccent(s)}${sev ? ` ${sev}` : ''}" title="${esc(s.label || '')}">
            <span class="ds-name">${esc(sensorDrillName(s))}</span>
            <span class="ds-val">${esc(sensorDrillValText(s))}</span>
            ${unit ? `<span class="ds-unit">${esc(unit)}</span>` : ''}
          </div>`;
        }).join('')}</div></div>`);
      }
      document.getElementById('sensorGroups').innerHTML = html.join('') || '<p class="section-lead" style="margin:0">No sensors reporting.</p>';
    }

    function renderCores(cores) {
      const el = document.getElementById('coreBars');
      if (!el || (!el.offsetParent && !isDrillOpen('drill-compute'))) return;
      if (!el.dataset.init) {
        el.innerHTML = cores.map(c => `<div><div class="core-bar" data-core="${c.id}"><div class="core-fill"></div></div><div class="core-label">${c.id}</div></div>`).join('');
        el.dataset.init = '1';
      }
      cores.forEach(c => {
        const f = el.querySelector(`[data-core="${c.id}"] .core-fill`);
        if (f) setMeterHeight(f, c.pct, 2);
      });
    }

    const RATING_TIER_LABEL = {
      excellent: 'Excellent', good: 'Good', fair: 'Fair', poor: 'Poor', bad: 'Bad',
    };

    function fmtDuration(sec) {
      if (!sec || sec < 60) return `${Math.round(sec || 0)}s`;
      const m = Math.floor(sec / 60);
      const s = Math.round(sec % 60);
      return s ? `${m}m ${s}s` : `${m}m`;
    }

    let gameSessionsCache = null;
    let gameSessionsKey = '';
    let gameSessionsTick = 0;
    let lastSeenSessionEnd = 0;

    function sessionHasMangoHud(s) {
      if (!s) return false;
      return !!(s.mangohud || s.fps_avg != null || s.mangohud_path
        || s.hitch_source === 'mangohud');
    }

    function hitchStatSub(s, hitchEvents) {
      if (sessionHasMangoHud(s)) {
        const fps1 = s.fps_1pct != null ? `${s.fps_1pct} FPS 1%` : 'measured';
        return `MangoHud · ${fps1}`;
      }
      const n = hitchEvents ?? s?.hitch_events ?? 0;
      return `${n} hitches · proxy`;
    }

    function resolveLastSession(gp, gid) {
      const sessions = gameSessionsCache?.sessions || [];
      const cached = (gid && sessions.find(s => s.game_id === gid))
        || sessions[0]
        || null;
      let base = null;
      if (!gid) base = gp?.last_session || cached || null;
      else if (gp?.last_session?.game_id === gid) base = gp.last_session;
      else if (cached?.game_id === gid) base = cached;
      else base = gp?.last_session || cached || null;
      // Steady metrics omit last_session.trend (~64 KB); merge from /api/game-sessions.
      if (base && !(base.trend && base.trend.length) && sessions.length) {
        const match = sessions.find(s =>
          (base.ended_ts && s.ended_ts === base.ended_ts)
          || (base.started_ts && s.started_ts === base.started_ts)
          || (base.game_id && s.game_id === base.game_id && s.trend?.length)
        );
        if (match?.trend?.length) {
          return { ...base, trend: match.trend };
        }
      }
      return base;
    }

    function applyGamePerfTrendChart(trend, title) {
      const lead = document.getElementById('gamePerfTrendLead');
      const points = trend || [];
      const ts = points.map(p => p.ts);
      gamePerfChart.data.datasets = [
        {
          label: 'Smooth %',
          data: xySeries(ts, points.map(p => p.smoothness ?? null)),
          borderColor: METRIC.mem,
          backgroundColor: sparkAreaFill(METRIC.mem, 0.16, 0.02),
          fill: true,
          borderWidth: 2.5,
          pointRadius: 0,
          tension: 0.2,
        },
        {
          label: 'Stutter',
          data: xySeries(ts, points.map(p => p.stutter_score ?? null)),
          borderColor: METRIC.stutter,
          backgroundColor: 'transparent',
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.2,
        },
        {
          label: 'Game process',
          data: xySeries(ts, points.map(p => p.game_cpu ?? null)),
          borderColor: METRIC.cpu,
          backgroundColor: 'transparent',
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.2,
        },
      ];
      lockPctAxis(gamePerfChart, 'y');
      if (!chartInteractActive) {
        if (chartsPaused || chartZoomed) {
          if (chartRange) {
            gamePerfChart.options.scales.x.min = chartRange.min;
            gamePerfChart.options.scales.x.max = chartRange.max;
          }
        } else if (ts.length >= 2) {
          const tMin = Math.min(...ts.filter(Number.isFinite));
          const tMax = Math.max(...ts.filter(Number.isFinite));
          // Pad to at least 60s so short sessions don't look "sped up"
          const pad = Math.max(60, (tMax - tMin) * 0.02);
          gamePerfChart.options.scales.x.min = tMin - pad * 0.05;
          gamePerfChart.options.scales.x.max = Math.max(tMax, tMin + pad);
        }
        if (canvasVisible(gamePerfChart)) gamePerfChart.update('none');
      }
      if (lead) lead.textContent = title;
    }

    /** Frametime display: MangoHud FPS → ms, else hitch proxy. */
    function gameFrametimeCard(src, mh) {
      if (mh && src?.fps_avg != null && src.fps_avg > 0) {
        return {
          k: 'Frametime',
          v: `${(1000 / src.fps_avg).toFixed(1)}ms`,
          s: 'avg (from FPS)',
          cls: 'ok',
          primary: true,
          mh: true,
        };
      }
      const hitch = src?.hitch_ms_1pct;
      if (hitch != null) {
        const hot = hitch >= 50;
        return {
          k: 'Frametime',
          v: `${hitch}ms`,
          s: mh ? '1% worst (MH)' : '1% hitch est.',
          cls: hot ? 'poor' : 'ok',
          primary: true,
          card: hot ? 'hero-warn' : 'hero-primary',
        };
      }
      return { k: 'Frametime', v: '—', s: 'waiting…', cls: 'muted', primary: true };
    }

    function gameFpsCard(src, mh) {
      if (mh && src?.fps_avg != null) {
        return {
          k: 'FPS',
          v: src.fps_avg,
          s: src.fps_1pct != null ? `1% low ${src.fps_1pct}` : 'MangoHud',
          cls: 'ok',
          primary: true,
          mh: true,
        };
      }
      return {
        k: 'FPS',
        v: '—',
        s: mh ? 'no samples yet' : 'enable MangoHud log',
        cls: 'muted',
        primary: true,
      };
    }

    function gameOnePctCard(src, mh) {
      if (mh && src?.fps_1pct != null) {
        return {
          k: '1% lows',
          v: src.fps_1pct,
          s: 'FPS (MangoHud)',
          cls: 'ok',
          primary: true,
          mh: true,
        };
      }
      const hitch = src?.hitch_ms_1pct;
      if (hitch != null) {
        const hot = hitch >= 50;
        return {
          k: '1% lows',
          v: `${hitch}ms`,
          s: mh ? 'frametime MH' : 'hitch proxy',
          cls: hot ? 'poor' : 'ok',
          primary: true,
          card: hot ? 'hero-warn' : 'hero-primary',
        };
      }
      return { k: '1% lows', v: '—', s: 'waiting…', cls: 'muted', primary: true };
    }

    /**
     * Patch KPI cards in place (textContent) to avoid 1 Hz layout thrash from full
     * innerHTML rebuilds. Only rebuilds structure when card keys change.
     */
    function patchGamePerfKpis(el, items) {
      if (!el) return;
      const keys = items.map((it, i) => it.id || `k${i}`);
      const keySig = keys.join('|');
      if (el.dataset.kpiSig !== keySig) {
        el.dataset.kpiSig = keySig;
        el.innerHTML = items.map((it, i) => {
          const id = it.id || `k${i}`;
          const cardCls = [
            'game-perf-kpi',
            it.primary ? 'hero-primary' : '',
            it.card || '',
            it.mh ? 'mh-live' : '',
          ].filter(Boolean).join(' ');
          return `<div class="${cardCls}" data-kpi="${esc(id)}"><span class="k"></span><span class="v"></span><span class="s"></span></div>`;
        }).join('');
      }
      items.forEach((it, i) => {
        const id = it.id || `k${i}`;
        const card = el.querySelector(`[data-kpi="${CSS.escape(id)}"]`);
        if (!card) return;
        card.className = [
          'game-perf-kpi',
          it.primary ? 'hero-primary' : '',
          it.card || '',
          it.mh ? 'mh-live' : '',
        ].filter(Boolean).join(' ');
        const kEl = card.querySelector('.k');
        const vEl = card.querySelector('.v');
        const sEl = card.querySelector('.s');
        if (kEl && kEl.textContent !== String(it.k || '')) kEl.textContent = it.k || '';
        const vStr = it.v == null ? '—' : String(it.v);
        if (vEl) {
          if (vEl.textContent !== vStr) vEl.textContent = vStr;
          const vCls = `v ${it.cls || ''}`.trim();
          if (vEl.className !== vCls) vEl.className = vCls;
        }
        const sStr = it.s == null ? '' : String(it.s);
        if (sEl && sEl.textContent !== sStr) sEl.textContent = sStr;
      });
    }

    /**
     * Game strip between summary hero and Live lab.
     * No active game → minimized one-line strip (“No game running”).
     * Active / loading → expanded KPIs + charts.
     */
    function renderGamePerfKpis(gp, gt, st) {
      const el = document.getElementById('gamePerfKpis');
      const statusEl = document.getElementById('gamePerfStatus');
      const nameEl = document.getElementById('gamePerfGameName');
      const idleBadge = document.getElementById('gamePerfIdleBadge');
      const hero = document.getElementById('gamePerformanceHero');
      if (!el || !hero) return;

      const activeGame = !!(gp?.active || gt?.running);
      const hitchScore = st?.score ?? st?.session?.score;
      const stuttery = activeGame && hitchScore != null && hitchScore >= 42;

      hero.classList.toggle('is-minimized', !activeGame);
      hero.classList.toggle('is-live', activeGame && !!gp?.recording);
      hero.classList.toggle('is-stutter', !!stuttery);
      hero.setAttribute('aria-expanded', activeGame ? 'true' : 'false');

      if (!activeGame) {
        if (nameEl && nameEl.textContent) nameEl.textContent = '';
        if (statusEl) {
          statusEl.className = 'game-perf-hero-status is-listening';
          const msg = 'No game running';
          if (statusEl.textContent !== msg) statusEl.textContent = msg;
        }
        if (idleBadge) {
          const b = 'No game running';
          if (idleBadge.textContent !== b) idleBadge.textContent = b;
        }
        // Keep charts mounted but hidden via CSS; clear KPI grid noise
        if (el.dataset.kpiSig !== 'idle') {
          el.dataset.kpiSig = 'idle';
          el.innerHTML = '';
        }
        return;
      }

      const gname = gp.game_name || gt?.game_name || 'Game';
      if (nameEl && nameEl.textContent !== gname) nameEl.textContent = gname;

      if (!gp.recording) {
        const remain = Math.ceil(gp.load_remaining_sec ?? 0);
        if (statusEl) {
          statusEl.className = 'game-perf-hero-status is-live';
          const msg = `${gname} detected — load grace ${remain}s`;
          if (statusEl.textContent !== msg) statusEl.textContent = msg;
        }
        patchGamePerfKpis(el, [
          { id: 'fps', k: 'FPS', v: '—', s: 'not scoring yet', cls: 'muted', primary: true },
          { id: 'onepct', k: '1% lows', v: '—', s: 'not scoring yet', cls: 'muted', primary: true },
          { id: 'ft', k: 'Frametime', v: '—', s: 'not scoring yet', cls: 'muted', primary: true },
          { id: 'status', k: 'Status', v: 'Loading', s: `${remain}s until recording`, cls: 'fair' },
          { id: 'gproc', k: 'Game process', v: `${gt?.cpu_pct ?? '—'}%`, s: 'live (not scored)', cls: '' },
          { id: 'grace', k: 'Grace', v: `${gp.load_grace_sec ?? 45}s`, s: 'skip menus / boot', cls: '' },
        ]);
        requestAnimationFrame(() => {
          try { gamePerfChart?.resize(); gamePerfSessionsChart?.resize(); } catch (_) { /* */ }
        });
        return;
      }

      const tier = gp.rating_tier || 'fair';
      const sess = st?.session || {};
      const mh = sessionHasMangoHud(gp);
      if (statusEl) {
        statusEl.className = 'game-perf-hero-status' + (stuttery ? ' is-warn' : ' is-live');
        const msg = `Live · session ${fmtDuration(gp.duration_sec)}`
          + (mh ? ' · MangoHud' : '');
        if (statusEl.textContent !== msg) statusEl.textContent = msg;
      }
      const hitchHot = (gp.hitch_ms_1pct || 0) >= 50;
      const hitchMany = (gp.hitch_events || 0) >= 5;
      patchGamePerfKpis(el, [
        { id: 'fps', ...gameFpsCard(gp, mh) },
        { id: 'onepct', ...gameOnePctCard(gp, mh) },
        { id: 'ft', ...gameFrametimeCard(gp, mh) },
        { id: 'rating', k: 'Rating', v: gp.rating ?? '—', s: RATING_TIER_LABEL[tier] || tier, cls: tier },
        { id: 'smooth', k: 'Smooth', v: `${gp.smoothness_avg ?? '—'}%`, s: 'session avg', cls: '' },
        {
          id: 'hitches',
          k: 'Hitches',
          v: gp.hitch_events ?? 0,
          s: `${sess.hitch_rate_per_min ?? 0}/min (5m)`,
          cls: hitchMany ? 'fair' : 'ok',
          card: hitchMany ? 'hero-warn' : '',
        },
        { id: 'gproc', k: 'Game process', v: `${gp.game_cpu_avg ?? '—'}%`, s: `now ${gt?.cpu_pct ?? '—'}%`, cls: '' },
        { id: 'gpu', k: 'GPU', v: `${gp.gpu_busy_avg ?? '—'}%`, s: 'session avg', cls: hitchHot ? 'fair' : '' },
      ]);
      requestAnimationFrame(() => {
        try { gamePerfChart?.resize(); gamePerfSessionsChart?.resize(); } catch (_) { /* */ }
      });
    }

    function renderGamePerfLiveTrend(history, gp, gt) {
      const gid = gp.game_id || gt?.game_id || gp.last_session?.game_id || lastActiveGameId;
      if (gp.recording && gid) {
        let trend = (gp.trend && gp.trend.length) ? gp.trend : null;
        if (!trend && gp.started_ts) {
          const slice = (history || []).filter(h =>
            h.game_totals?.game_id === gid && (h.ts || 0) >= gp.started_ts
          );
          trend = slice.map(h => ({
            ts: h.ts,
            smoothness: h.stutter?.smoothness,
            stutter_score: h.stutter?.score,
            game_cpu: h.game_totals?.cpu_pct,
          }));
        }
        const n = trend?.length || 0;
        const title = n
          ? `This session — ${n} samples since recording started`
          : 'This session — collecting first samples…';
        applyGamePerfTrendChart(trend || [], title);
        return;
      }
      if (gp.active && !gp.recording) {
        gamePerfChart.data.labels = [];
        gamePerfChart.data.datasets = [];
        gamePerfChart.update('none');
        const lead = document.getElementById('gamePerfTrendLead');
        if (lead) {
          lead.textContent = `This session — recording in ${Math.ceil(gp.load_remaining_sec ?? 0)}s (load grace)`;
        }
        return;
      }
      const last = resolveLastSession(gp, gid);
      if (last?.trend?.length) {
        const name = last.game_name || gameLabel(last.game_id);
        applyGamePerfTrendChart(
          last.trend,
          `Last session — ${name} · ended ${fmtStoreSpan(last.ended_ts)} · rating ${last.rating ?? '—'}/100`,
        );
        return;
      }
      gamePerfChart.data.labels = [];
      gamePerfChart.data.datasets = [];
      gamePerfChart.update('none');
      const lead = document.getElementById('gamePerfTrendLead');
      if (lead) lead.textContent = 'Last session trend — appears after you finish a game (45s load + 30s play)';
    }

    function renderGamePerfSessionChart(sessions, markers) {
      const ordered = [...(sessions || [])].reverse().slice(-24);
      const labels = ordered.map(s => {
        const d = new Date((s.started_ts || 0) * 1000);
        return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
      });
      const ratings = ordered.map(s => s.rating ?? 0);
      const colors = ordered.map(s => {
        const t = s.rating_tier || 'fair';
        if (t === 'excellent') return '#6fcf97';
        if (t === 'good') return '#8fd49a';
        if (t === 'fair') return '#f5c882';
        if (t === 'poor') return '#ff9f7a';
        return '#ff8a7a';
      });
      gamePerfSessionsChart.data.labels = labels;
      gamePerfSessionsChart.data.datasets = [{
        label: 'Rating',
        data: ratings,
        backgroundColor: colors,
        borderRadius: 6,
        sessionMeta: ordered,
      }];
      if (canvasVisible(gamePerfSessionsChart)) gamePerfSessionsChart.update('none');

      const markersEl = document.getElementById('gamePerfMarkers');
      const fixMarkers = (markers || []).filter(m => m.kind === 'fix').slice(0, 8);
      markersEl.innerHTML = fixMarkers.length
        ? fixMarkers.map(m =>
            `<span class="game-perf-marker" title="${m.meta || ''}">${fmtStoreSpan(m.ts)} · fix · ${m.insight_id || m.label}</span>`
          ).join('')
        : '<span class="game-perf-marker">Session markers appear when issues are live during a game</span>';
    }

    function renderGamePerfHistory(sessions) {
      const body = document.getElementById('gamePerfHistory');
      const rows = (sessions || []).slice(0, 12);
      body.innerHTML = rows.length
        ? rows.map(s => {
            const mh = sessionHasMangoHud(s);
            const fpsCell = mh && s.fps_avg != null
              ? `<strong>${s.fps_avg}</strong>${s.fps_1pct != null ? ` <span style="color:var(--muted)">1% ${s.fps_1pct}</span>` : ''}`
              : '<span style="color:var(--muted)">—</span>';
            const hitchNote = mh ? ' title="MangoHud measured frametime"' : ' title="Kernel stutter proxy"';
            return `<tr>
            <td>${fmtStoreSpan(s.started_ts)}${mh ? ' <span class="mh-badge">MH</span>' : ''}</td>
            <td><strong>${s.rating ?? '—'}</strong> <span style="color:var(--muted)">${RATING_TIER_LABEL[s.rating_tier] || s.rating_tier || ''}</span></td>
            <td>${s.smoothness_avg ?? '—'}%</td>
            <td>${fpsCell}</td>
            <td${hitchNote}>${s.hitch_ms_1pct ?? '—'}ms</td>
            <td>${s.hitch_events ?? 0}</td>
            <td>${fmtDuration(s.duration_sec)}</td>
          </tr>`;
          }).join('')
        : '<tr><td colspan="7" style="color:var(--muted)">No completed sessions yet — after the 45s load wait, play ~30s+; ratings save when you quit. Enable MangoHud logging for real FPS.</td></tr>';
    }

    async function fetchGameSessions(gameId) {
      if (!gameId) {
        gameSessionsCache = { sessions: [], markers: [] };
        renderGamePerfSessionChart([], []);
        renderGamePerfHistory([]);
        return;
      }
      const key = gameId;
      if (gameSessionsKey === key && gameSessionsCache && gameSessionsTick % 30 !== 0) {
        renderGamePerfSessionChart(gameSessionsCache.sessions, gameSessionsCache.markers);
        renderGamePerfHistory(gameSessionsCache.sessions);
        return;
      }
      try {
        const data = await (await fetch(`/api/game-sessions?game=${encodeURIComponent(gameId)}&days=30`)).json();
        gameSessionsCache = data;
        gameSessionsKey = key;
        renderGamePerfSessionChart(data.sessions, data.markers);
        renderGamePerfHistory(data.sessions);
        renderGamePerfLiveTrend(rawHistory, lastLatest?.game_performance || {}, lastLatest?.game_totals || {});
      } catch (_) {
        document.getElementById('gamePerfHistory').innerHTML =
          '<tr><td colspan="7" style="color:var(--muted)">Session history unavailable</td></tr>';
      }
    }

    function syncGameHeroFocus(gp, gt) {
      /** Soft focus when a game appears — never open/close accordion tabs. */
      const running = !!(gt?.running || gp?.active);
      if (running && !gameWasRunning) {
        const hero = document.getElementById('gamePerformanceHero');
        if (hero) {
          // Brief highlight only; second-monitor users should not need to click.
          hero.classList.add('is-live');
          requestAnimationFrame(() => {
            try { gamePerfChart?.resize(); gamePerfSessionsChart?.resize(); } catch (_) { /* */ }
          });
        }
      }
      gameWasRunning = running;
    }

    function renderGamePerformance(l, s) {
      const gp = l.game_performance || {};
      const gt = l.game_totals || {};
      // active_game null ⇒ listening empty state inside renderGamePerfKpis
      syncGameHeroFocus(gp, gt);
      if (gp.last_session?.ended_ts && gp.last_session.ended_ts !== lastSeenSessionEnd) {
        lastSeenSessionEnd = gp.last_session.ended_ts;
        gameSessionsKey = '';
      }
      renderGamePerfKpis(gp, gt, l.stutter);
      const heroLive = !document.getElementById('gamePerformanceHero')?.classList.contains('is-minimized');
      if (heroLive || isDrillOpen('drill-game')) {
        renderGamePerfLiveTrend(rawHistory, gp, gt);
        const gid = gp.active ? gp.game_id
          : (gt?.running ? gt.game_id : (gp.last_session?.game_id || lastActiveGameId));
        if (gid !== gameSessionsKey || ++gameSessionsTick % 30 === 0) fetchGameSessions(gid);
        else if (gameSessionsCache) {
          renderGamePerfSessionChart(gameSessionsCache.sessions, gameSessionsCache.markers);
          renderGamePerfHistory(gameSessionsCache.sessions);
        }
      }
    }

    function renderProcs(procs, totals) {
      const body = document.getElementById('procBody');
      const lead = document.getElementById('gameProcLead');
      if (lead) {
        const gname = totals?.primary_name || totals?.game_name || 'Game';
        lead.textContent = totals?.running
          ? `${gname} (PID ${totals.primary_pid}) · ${totals.proc_count} related process${totals.proc_count === 1 ? '' : 'es'} · ${(totals.tree_rss_mb / 1024).toFixed(1)} GB tree total`
          : 'No Steam game running — any installed title is detected automatically.';
      }
      const structKey = JSON.stringify(procs.map(p => [p.pid, p.name, p.tier]));
      if (structKey === lastProcKey && body.dataset.init) {
        procs.forEach(p => {
          const row = body.querySelector(`tr[data-pid="${p.pid}"]`);
          if (!row) return;
          row.children[3].textContent = p.cpu_pct;
          row.children[4].textContent = p.rss_mb;
        });
        return;
      }
      lastProcKey = structKey;
      body.innerHTML = procs.length
        ? procs.map(p => `<tr data-pid="${p.pid}"><td>${p.pid}</td><td>${p.name}</td><td>${p.tier === 'main' ? 'Game' : 'Child'}</td><td>${p.cpu_pct}</td><td>${p.rss_mb}</td></tr>`).join('')
        : '<tr><td colspan="5" style="color:var(--muted)">No game processes detected</td></tr>';
      body.dataset.init = '1';
    }

    let storeCache = null;
    let storeTick = 0;
    let optionsMsgTimer = null;
    let uiScaleBusy = false;
    let uiScalePending = null; // last { scale, silent }

    function optionsThemeLocked() {
      return !!(themeSaveBusy || themeSavePending);
    }
    function optionsUiScaleLocked() {
      if (uiScaleBusy || uiScalePending) return true;
      return document.activeElement?.id === 'uiScaleRange';
    }
    function optionsHwScaleLocked() {
      if (hwScaleBusy || hwScalePending) return true;
      return !!document.activeElement?.dataset?.hwScale;
    }

    const UI_SCALE_DEFAULT = 1;

    function fmtStoreSpan(ts) {
      if (!ts) return '—';
      return new Date(ts * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }

    function clampUiScale(scale) {
      const s = Number(scale);
      if (!Number.isFinite(s)) return UI_SCALE_DEFAULT;
      return Math.max(1, Math.min(2, Math.round(s / 0.05) * 0.05));
    }

    /** Update the % readout (and aria) without reflowing the whole page. */
    function updateUiScaleLabel(scale, { syncRange = false } = {}) {
      const clamped = clampUiScale(scale);
      const range = document.getElementById('uiScaleRange');
      const val = document.getElementById('uiScaleVal');
      if (range && (syncRange || document.activeElement !== range)) {
        range.value = String(clamped);
      }
      if (range) range.setAttribute('aria-valuenow', String(clamped));
      if (val) val.textContent = `${Math.round(clamped * 100)}%`;
      return clamped;
    }

    function currentUiScale() {
      const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale');
      return clampUiScale(parseFloat(String(raw).trim()) || UI_SCALE_DEFAULT);
    }

    /** Chart.js uses px fonts — scale from a 100% baseline size. */
    function chartPx(baseAt100) {
      return Math.max(10, Math.round(Number(baseAt100) * currentUiScale()));
    }

    function applyChartFontScale() {
      const tick = chartPx(10);
      const legend = chartPx(11);
      const charts = [
        typeof utilChart !== 'undefined' ? utilChart : null,
        typeof bwChart !== 'undefined' ? bwChart : null,
        typeof ioChart !== 'undefined' ? ioChart : null,
        typeof sparkChart !== 'undefined' ? sparkChart : null,
        typeof stutterChart !== 'undefined' ? stutterChart : null,
        typeof indexChart !== 'undefined' ? indexChart : null,
        typeof gamePerfChart !== 'undefined' ? gamePerfChart : null,
        typeof gamePerfSessionsChart !== 'undefined' ? gamePerfSessionsChart : null,
      ].filter(Boolean);
      for (const ch of charts) {
        try {
          const lab = ch.options?.plugins?.legend?.labels;
          if (lab?.font) lab.font.size = legend;
          const scales = ch.options?.scales || {};
          for (const sc of Object.values(scales)) {
            if (sc?.ticks?.font) sc.ticks.font.size = tick;
          }
          ch.update('none');
        } catch (_) { /* chart not ready */ }
      }
    }

    function applyUiScale(scale) {
      const clamped = clampUiScale(scale);
      // Drives html rem root via --ui-root (calc on --ui-scale).
      document.documentElement.style.setProperty('--ui-scale', String(clamped));
      updateUiScaleLabel(clamped);
      applyChartFontScale();
      try { syncUiWrap(); } catch (_) { /* ignore */ }
      requestAnimationFrame(() => {
        try { syncLabStage(); } catch (_) { /* ignore */ }
        try { sparkChart?.resize(); } catch (_) { /* ignore */ }
        try { indexChart?.resize(); } catch (_) { /* ignore */ }
        try { stutterChart?.resize(); } catch (_) { /* ignore */ }
      });
      return clamped;
    }

    function showOptionsMsg(text, ok = true) {
      const el = document.getElementById('optionsMsg');
      if (!el) return;
      el.textContent = text;
      el.classList.toggle('ok', ok && !!text);
      el.classList.toggle('err', !ok && !!text);
      clearTimeout(optionsMsgTimer);
      if (text) optionsMsgTimer = setTimeout(() => {
        el.textContent = '';
        el.classList.remove('ok', 'err');
      }, 4000);
    }

    const HW_SCALE_LABEL = {
      cpu_temp_min_c: v => `${v}°C`,
      cpu_temp_max_c: v => `${v}°C`,
      gpu_temp_max_c: v => `${v}°C`,
      cpu_power_max_w: v => `${v} W`,
      gpu_power_max_w: v => `${v} W`,
    };

    function applyHwScalesFromStore(s) {
      const incoming = s?.hw_scales || s?.pulse_config?.hw_scales;
      if (incoming && typeof incoming === 'object') {
        hwScales = { ...HW_SCALE_DEFAULTS, ...incoming };
      }
      const bounds = s?.hw_scale_bounds || {};
      const steps = s?.hw_scale_step || {};
      document.querySelectorAll('[data-hw-scale]').forEach(el => {
        const key = el.dataset.hwScale;
        const b = bounds[key];
        if (Array.isArray(b) && b.length === 2) {
          el.min = String(b[0]);
          el.max = String(b[1]);
        }
        if (steps[key] != null) el.step = String(steps[key]);
        const v = hwScales[key];
        if (v != null && document.activeElement !== el) el.value = String(v);
        const lab = document.getElementById(el.id + 'Val');
        if (lab && v != null) lab.textContent = (HW_SCALE_LABEL[key] || (x => String(x)))(v);
      });
      fillHwScaleHints();
    }

    function fillHwScaleHints() {
      const cpu = (lastLatest?.comparison?.cpu?.name
        || lastStatic?.cpu_model
        || '').replace(/^AMD\s+/i, '').trim();
      const gpu = (lastLatest?.comparison?.gpu?.name
        || lastLatest?.gpu?.discrete?.name
        || lastStatic?.gpu_model
        || '').replace(/^AMD\s+/i, '').trim();
      const pwr = document.getElementById('hwPowerHint');
      if (pwr) {
        const bits = [];
        if (cpu) bits.push(`${cpu} package`);
        if (gpu) bits.push(`${gpu} board`);
        pwr.textContent = bits.length
          ? `Dial 100% is full ${bits.join(' / ')} power. Raise if the ring pegs; lower if it never fills.`
          : 'Dial 100% is the watt ceiling you set. Raise if the ring pegs; lower if it never fills.';
      }
    }

    let hwScaleBusy = false;
    let hwScalePending = null; // last { key: n, ... } merged while a POST is in flight
    async function applyHwScaleSetting(key, value) {
      const n = Number(value);
      if (!key || !Number.isFinite(n)) return;
      hwScales = { ...hwScales, [key]: n };
      try { if (typeof renderSparkChart === 'function') renderSparkChart(); } catch (_) { /* */ }
      hwScalePending = { ...(hwScalePending || {}), [key]: n };
      flushHwScaleSave();
    }

    async function flushHwScaleSave() {
      if (hwScaleBusy) return;
      hwScaleBusy = true;
      try {
        while (hwScalePending) {
          const job = hwScalePending;
          hwScalePending = null;
          storeWriteGen += 1;
          try {
            const res = await fetch('/api/store', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ hw_scales: job }),
            });
            const data = await res.json();
            if (!data.ok) throw new Error(data.error || 'failed');
            storeCache = data;
            storeWriteGen += 1;
            if (!hwScalePending) {
              applyHwScalesFromStore(data);
              const keys = Object.keys(job);
              const lastKey = keys[keys.length - 1];
              const pretty = (HW_SCALE_LABEL[lastKey] || (x => String(x)))(
                data.hw_scales?.[lastKey] ?? job[lastKey],
              );
              showOptionsMsg(`Saved ${pretty} hardware scale`, true);
            } else {
              hwScales = { ...hwScales, ...hwScalePending };
            }
          } catch (e) {
            if (!hwScalePending) showOptionsMsg('Could not save hardware scale', false);
          }
        }
      } finally {
        hwScaleBusy = false;
        if (hwScalePending) flushHwScaleSave();
      }
    }

    function renderUiScaleControls(s) {
      const scale = s?.ui_scale ?? s?.pulse_config?.ui_scale ?? UI_SCALE_DEFAULT;
      const min = s?.ui_scale_min ?? 1;
      const max = s?.ui_scale_max ?? 2;
      const step = s?.ui_scale_step ?? 0.05;
      const range = document.getElementById('uiScaleRange');
      if (range) {
        range.min = String(min);
        range.max = String(max);
        range.step = String(step);
      }
      applyUiScale(scale);
    }

    function renderTuningLogControls(s) {
      const maxCards = s.tuning_log_max ?? s.pulse_config?.tuning_log_max ?? 48;
      const presets = s.tuning_log_presets || [24, 48, 96, 200];
      const min = s.tuning_log_min ?? 8;
      const cap = s.tuning_log_max_cap ?? 500;
      const custom = document.getElementById('tuningLogCustom');
      if (custom) {
        custom.min = min;
        custom.max = cap;
        if (document.activeElement !== custom) custom.value = maxCards;
      }
      const host = document.getElementById('tuningLogPresets');
      if (host) {
        host.innerHTML = presets.map(n =>
          `<button class="btn${n === maxCards ? ' active' : ''}" type="button" data-logmax="${n}">${n}</button>`
        ).join('');
        host.querySelectorAll('[data-logmax]').forEach(btn => {
          btn.onclick = () => applyTuningLogMax(+btn.dataset.logmax, btn);
        });
      }
      const logStats = document.getElementById('optLogStats');
      if (logStats) {
        const entries = s.tuning_log_entries ?? 0;
        const kb = s.tuning_log_size_kb ?? 0;
        logStats.innerHTML = [
          `<span><strong>${entries.toLocaleString()}</strong> cards in log</span>`,
          `<span>cap <strong>${maxCards}</strong></span>`,
          `<span><strong>${kb}</strong> KB on disk</span>`,
        ].join('');
      }
    }

    function renderResetStats(s) {
      const el = document.getElementById('optResetStats');
      if (!el) return;
      el.innerHTML = [
        `<span><strong>${(s.samples || 0).toLocaleString()}</strong> samples</span>`,
        `<span><strong>${s.game_sessions ?? 0}</strong> sessions</span>`,
        `<span><strong>${s.tuning_log_entries ?? 0}</strong> guidance cards</span>`,
        `<span><strong>${s.suppressed_count ?? 0}</strong> ignored</span>`,
        `<span><strong>${s.resolved_count ?? 0}</strong> marked fixed</span>`,
      ].join('');
    }

    function insightPrefLabel(id) {
      const sid = String(id || '');
      const rules = ruleCatalogCache || [];
      const r = rules.find(x => x.insight_id === sid || x.rule_id === sid);
      if (r?.title) return { title: r.title, meta: r.pack_id ? `${r.pack_id} · ${sid}` : sid };
      const hints = []
        .concat(lastWarningsHints || [])
        .concat(lastGuidanceFixedHints || [])
        .concat((lastGuidanceIndexGroups || []).flatMap(g => g.hints || []));
      const h = hints.find(x => x.insight_id === sid);
      if (h?.title) return { title: h.title, meta: sid };
      return { title: sid.replace(/-/g, ' '), meta: sid };
    }

    function renderPrefList(el, ids, actionKey, emptyText) {
      if (!el) return;
      const list = Array.isArray(ids) ? ids.filter(Boolean) : [];
      if (!list.length) {
        el.innerHTML = `<p class="pref-list-empty">${emptyText}</p>`;
        return;
      }
      el.innerHTML = list.map(id => {
        const meta = insightPrefLabel(id);
        return `
        <div class="pref-row" data-pref-id="${esc(id)}">
          <div>
            <span class="pref-row-id" title="${esc(id)}">${esc(meta.title)}</span>
            <span class="pref-row-meta">${esc(meta.meta)}</span>
          </div>
          <button type="button" class="btn" data-pref-action="${actionKey}" data-pref-id="${esc(id)}">Restore</button>
        </div>`;
      }).join('');
      el.querySelectorAll('[data-pref-action]').forEach(btn => {
        btn.addEventListener('click', () => restoreGuidancePref(btn.dataset.prefAction, btn.dataset.prefId, btn));
      });
    }

    function renderGuidancePrefs(s) {
      const ignored = s?.suppressed_insights || lastStatic?.suppressed_insights || [];
      const fixed = s?.resolved_insights || lastStatic?.resolved_insights || [];
      const stats = document.getElementById('optGuidanceStats');
      if (stats) {
        stats.innerHTML = [
          `<span><strong>${ignored.length}</strong> ignored</span>`,
          `<span><strong>${fixed.length}</strong> marked fixed</span>`,
        ].join('');
      }
      renderPrefList(
        document.getElementById('prefIgnoredList'),
        ignored,
        'unsuppress_insight',
        'Nothing ignored — Hide on a Guidance card adds it here.',
      );
      renderPrefList(
        document.getElementById('prefFixedList'),
        fixed,
        'unresolve_insight',
        'Nothing marked fixed yet.',
      );
    }

    async function restoreGuidancePref(actionKey, insightId, btn) {
      if (!actionKey || !insightId) return;
      if (btn) btn.disabled = true;
      try {
        const body = { [actionKey]: insightId };
        const res = await fetch('/api/store', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || 'failed');
        if (data.suppressed_insights) {
          if (lastStatic) lastStatic.suppressed_insights = data.suppressed_insights;
        }
        if (data.resolved_insights) {
          if (lastStatic) lastStatic.resolved_insights = data.resolved_insights;
        }
        renderStorage(data);
        showOptionsMsg(`Restored ${insightId}`, true);
        // Re-paint Guidance so restored cards can show again
        if (typeof renderWarnings === 'function') {
          try {
            const hints = lastLatest?.tuning || lastWarningsHints || [];
            renderWarnings(hints);
          } catch {}
        }
      } catch (e) {
        showOptionsMsg(e.message || 'Could not restore', false);
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    function renderStorage(s) {
      if (!s) return;
      storeCache = s;
      if (!optionsThemeLocked()) {
        if (!themeHydrated) {
          if (s.theme_mode) themeMode = s.theme_mode;
          themeHydrated = true;
          syncThemeModeUi();
          applyThemeFromSettings({ force: true });
        } else if (s.theme_mode === themeMode) {
          updateThemeStatus(lastStatic?.cosmic_theme);
          if (!themePreviewMode) {
            paintThemePreview(
              resolveChromeTokens(themeMode, lastStatic?.cosmic_theme),
              themeMode,
            );
          }
        }
      }
      const days = s.retention_days ?? 10;
      const est = s.est_max_mb ?? '—';
      const catalog = storeCache?.games_catalog || lastStatic?.games_catalog || {};
      const games = Object.entries(s.games || {}).map(([id, n]) => {
        const label = catalog[id]?.short || catalog[id]?.name || gameLabel(id);
        return `${label}: ${n}`;
      }).join(' · ');
      const statsEl = document.getElementById('storeStats');
      if (statsEl) {
        statsEl.innerHTML = [
          `<span><strong>${(s.samples || 0).toLocaleString()}</strong> samples</span>`,
          `<span><strong>${s.size_mb ?? 0}</strong> MB on disk</span>`,
          `<span>span ${fmtStoreSpan(s.oldest_ts)} → ${fmtStoreSpan(s.newest_ts)}</span>`,
          games ? `<span>${games}</span>` : '',
        ].filter(Boolean).join('');
      }
      const dataStats = document.getElementById('optDataStats');
      if (dataStats) {
        dataStats.innerHTML = [
          `<span><strong>${(s.samples || 0).toLocaleString()}</strong> samples</span>`,
          `<span><strong>${s.size_mb ?? 0}</strong> MB DB</span>`,
          `<span><strong>${s.game_sessions ?? 0}</strong> sessions</span>`,
          `<span>span ${fmtStoreSpan(s.oldest_ts)} → ${fmtStoreSpan(s.newest_ts)}</span>`,
        ].join('');
      }
      const estText =
        `At 1 sample/sec, ~${est} MB max with ${days}-day retention (older samples are removed automatically).`;
      const storeEst = document.getElementById('storeEstimate');
      if (storeEst) storeEst.textContent = estText;
      const optEst = document.getElementById('optStoreEstimate');
      if (optEst) optEst.textContent = estText;
      const hint = document.getElementById('storageRetentionHint');
      if (hint) hint.textContent = `Keep ${days} days of samples`;
      const drillSum = document.getElementById('drillStorageSum');
      if (drillSum) {
        drillSum.textContent =
          `${(s.samples || 0).toLocaleString()} samples · ${s.size_mb ?? 0} MB\nkeep ${days}d`;
      }
      const presets = s.retention_presets || [3, 7, 10, 14, 30];
      const min = s.retention_min ?? 1;
      const max = s.retention_max ?? 90;
      const custom = document.getElementById('retentionCustom');
      if (custom) {
        custom.min = min;
        custom.max = max;
        if (document.activeElement !== custom) custom.value = days;
      }
      const presetHost = document.getElementById('retentionPresets');
      if (presetHost) {
        presetHost.innerHTML = presets.map(d =>
          `<button class="btn${d === days ? ' active' : ''}" type="button" data-days="${d}">${d}d</button>`
        ).join('');
        presetHost.querySelectorAll('[data-days]').forEach(btn => {
          btn.onclick = () => applyRetention(+btn.dataset.days, btn);
        });
      }
      if (!optionsUiScaleLocked()) renderUiScaleControls(s);
      if (!optionsHwScaleLocked()) applyHwScalesFromStore(s);
      else fillHwScaleHints();
      renderTuningLogControls(s);
      renderResetStats(s);
      renderGuidancePrefs(s);
    }

    async function applyRetention(days, btn) {
      const min = storeCache?.retention_min ?? 1;
      const max = storeCache?.retention_max ?? 90;
      days = Math.round(Number(days));
      if (!Number.isFinite(days) || days < min || days > max) {
        showOptionsMsg(`Enter ${min}–${max} days`, false);
        return;
      }
      if (btn) btn.disabled = true;
      try {
        const res = await fetch('/api/store', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ retention_days: days }),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || 'failed');
        renderStorage(data);
        const pruned = data.pruned ? ` · removed ${data.pruned.toLocaleString()} old samples` : '';
        showOptionsMsg(`Retention set to ${days} days${pruned}`, true);
      } catch (e) {
        showOptionsMsg('Could not save retention setting', false);
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    async function applyUiScaleSetting(scale, { silent = false } = {}) {
      const min = storeCache?.ui_scale_min ?? 1;
      const max = storeCache?.ui_scale_max ?? 2;
      let s = Number(scale);
      if (!Number.isFinite(s)) {
        if (!silent) showOptionsMsg('Invalid UI scale', false);
        return;
      }
      s = Math.max(min, Math.min(max, Math.round(s / 0.05) * 0.05));
      s = Math.round(s * 100) / 100;
      applyUiScale(s);
      uiScalePending = { scale: s, silent };
      flushUiScaleSave();
    }

    async function flushUiScaleSave() {
      if (uiScaleBusy) return;
      uiScaleBusy = true;
      try {
        while (uiScalePending) {
          const job = uiScalePending;
          uiScalePending = null;
          storeWriteGen += 1;
          try {
            const res = await fetch('/api/store', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ ui_scale: job.scale }),
            });
            const data = await res.json();
            if (!data.ok) throw new Error(data.error || 'failed');
            storeCache = data;
            storeWriteGen += 1;
            if (!uiScalePending && !optionsUiScaleLocked()) renderUiScaleControls(data);
            if (!uiScalePending && !job.silent) {
              showOptionsMsg(`UI scale set to ${Math.round(job.scale * 100)}%`, true);
            }
          } catch (e) {
            if (!uiScalePending && !job.silent) {
              showOptionsMsg('Could not save UI scale', false);
            }
          }
        }
      } finally {
        uiScaleBusy = false;
        if (uiScalePending) flushUiScaleSave();
      }
    }

    async function fetchStore() {
      const gen = storeWriteGen;
      try {
        const data = await (await fetch('/api/store')).json();
        if (gen !== storeWriteGen) return;
        renderStorage(data);
      } catch (_) {
        const statsEl = document.getElementById('storeStats');
        if (statsEl) statsEl.textContent = 'Storage stats unavailable';
      }
    }

    let rulePacksCache = null;
    let ruleCatalogCache = null;

    function renderRulePackList(packs) {
      const host = document.getElementById('rulePackList');
      const stats = document.getElementById('rulePackStats');
      if (!host) return;
      rulePacksCache = packs || [];
      const enabled = rulePacksCache.filter(p => p.enabled);
      const rules = enabled.reduce((n, p) => n + (p.rule_count || 0), 0);
      if (stats) {
        stats.innerHTML = [
          `<span><strong>${enabled.length}</strong> / ${rulePacksCache.length} packs on</span>`,
          `<span><strong>${rules}</strong> active rules</span>`,
        ].join('');
      }
      if (!rulePacksCache.length) {
        host.innerHTML = '<p class="storage-note">No rule packs found under rules/builtin or ~/.config/pulse/rules.</p>';
        return;
      }
      host.innerHTML = rulePacksCache.map(p => {
        const badge = p.builtin
          ? '<span class="pack-badge builtin">built-in</span>'
          : '<span class="pack-badge">local</span>';
        const overrides = p.override_count
          ? ` · ${p.override_count} game override${p.override_count === 1 ? '' : 's'}`
          : '';
        return `<div class="pack-card${p.enabled ? '' : ' is-disabled'}" data-pack="${esc(p.id)}">
          <div class="pack-card-head">
            <h3 class="pack-card-title">${esc(p.name || p.id)} ${badge}</h3>
            <label class="pack-toggle">
              <input type="checkbox" data-pack-enable="${esc(p.id)}" ${p.enabled ? 'checked' : ''} />
              ${p.enabled ? 'Enabled' : 'Disabled'}
            </label>
          </div>
          <p class="pack-card-meta">
            <code>${esc(p.id)}</code> · v${esc(String(p.version || '0'))} ·
            ${p.rule_count || 0} rules${overrides}<br>
            <span title="${esc(p.path || '')}">${esc((p.path || '').replace(/\\/g, '/').split('/').slice(-3).join('/'))}</span>
          </p>
        </div>`;
      }).join('');
      host.querySelectorAll('[data-pack-enable]').forEach(input => {
        input.addEventListener('change', async () => {
          const packId = input.dataset.packEnable;
          const enabled = !!input.checked;
          input.disabled = true;
          try {
            const res = await fetch('/api/rule-packs', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ action: 'set_enabled', pack_id: packId, enabled }),
            });
            const data = await res.json();
            if (!data.ok) throw new Error(data.error || 'failed');
            renderRulePackList(data.packs || []);
            await fetchRuleCatalog();
            showOptionsMsg(
              enabled ? `Enabled pack ${packId}` : `Disabled pack ${packId}`,
              true,
            );
          } catch (e) {
            input.checked = !enabled;
            showOptionsMsg(e.message || 'Could not update pack', false);
          } finally {
            input.disabled = false;
          }
        });
      });
    }

    function renderRuleCatalog(rules) {
      const host = document.getElementById('ruleCatalog');
      if (!host) return;
      ruleCatalogCache = rules || [];
      if (!ruleCatalogCache.length) {
        host.innerHTML = '<p class="storage-note">No rules match.</p>';
        return;
      }
      host.innerHTML = ruleCatalogCache.slice(0, 80).map(r => {
        const lvl = (r.level || 'info').toLowerCase();
        const tip = [r.title, r.insight_id || r.rule_id, r.detect_summary].filter(Boolean).join(' · ');
        return `<div class="rule-row${r.pack_enabled ? '' : ' is-pack-off'}" title="${esc(tip)}">
          <span class="rule-level ${esc(lvl)}">${esc(lvl)}</span>
          <div>
            <div class="rule-row-title">${esc(r.title || r.insight_id || r.rule_id)}</div>
            <div class="rule-row-meta">
              ${esc(r.pack_id || '')}${r.bucket ? ` · ${esc(r.bucket)}` : ''}
            </div>
          </div>
        </div>`;
      }).join('');
      if (ruleCatalogCache.length > 80) {
        host.innerHTML += `<p class="storage-note">Showing 80 of ${ruleCatalogCache.length} — refine the filter.</p>`;
      }
      if (storeCache) renderGuidancePrefs(storeCache);
    }

    async function fetchRulePacks() {
      try {
        const data = await (await fetch('/api/rule-packs')).json();
        if (data.ok) renderRulePackList(data.packs || []);
      } catch (_) {
        const host = document.getElementById('rulePackList');
        if (host) host.innerHTML = '<p class="storage-note">Rule packs unavailable.</p>';
      }
    }

    async function fetchRuleCatalog(q) {
      try {
        const params = new URLSearchParams({ view: 'rules' });
        if (q) params.set('q', q);
        const data = await (await fetch(`/api/rule-packs?${params}`)).json();
        if (data.ok) {
          if (data.packs) renderRulePackList(data.packs);
          renderRuleCatalog(data.rules || []);
        }
      } catch (_) {
        const host = document.getElementById('ruleCatalog');
        if (host) host.innerHTML = '<p class="storage-note">Rule catalog unavailable.</p>';
      }
    }

    let ruleSearchTimer = null;
    document.getElementById('ruleCatalogSearch')?.addEventListener('input', e => {
      clearTimeout(ruleSearchTimer);
      ruleSearchTimer = setTimeout(() => fetchRuleCatalog(e.target.value.trim()), 200);
    });
    document.getElementById('rulePacksReload')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        const res = await fetch('/api/rule-packs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'reload' }),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || 'failed');
        renderRulePackList(data.packs || []);
        await fetchRuleCatalog(document.getElementById('ruleCatalogSearch')?.value?.trim());
        showOptionsMsg('Rule packs reloaded', true);
      } catch (err) {
        showOptionsMsg(err.message || 'Reload failed', false);
      } finally {
        btn.disabled = false;
      }
    });
    fetchRulePacks();
    fetchRuleCatalog();

    function resetConfirmOk() {
      return (document.getElementById('resetConfirmInput')?.value || '').trim() === 'RESET';
    }

    function syncResetButtons() {
      const ok = resetConfirmOk();
      ['btnClearSamples', 'btnClearTuningLog', 'btnResetGuidancePrefs', 'btnResetAll'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = !ok;
      });
      document.getElementById('resetConfirmRow')?.classList.toggle('is-ready', ok);
      const hint = document.getElementById('resetConfirmHint');
      if (hint) hint.textContent = ok ? 'Unlocked' : 'Required to unlock clear / reset';
    }

    function clearClientHistoryBuffers() {
      try {
        rawHistory = [];
        if (typeof metricsBootstrapped !== 'undefined') metricsBootstrapped = false;
      } catch (_) { /* ignore */ }
    }

    async function postStoreAction(body, btn) {
      if (btn) btn.disabled = true;
      try {
        const res = await fetch('/api/store', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || 'failed');
        renderStorage(data);
        if (data.details?.client_clear_history) clearClientHistoryBuffers();
        const conf = document.getElementById('resetConfirmInput');
        if (conf && body.confirm) conf.value = '';
        syncResetButtons();
        return data;
      } catch (e) {
        showOptionsMsg(e.message || 'Action failed', false);
        return null;
      } finally {
        if (btn) {
          // Re-enable non-confirm buttons; confirm-gated ones follow syncResetButtons.
          if (!body.confirm) btn.disabled = false;
          else syncResetButtons();
        }
      }
    }

    async function applyTuningLogMax(n, btn) {
      const min = storeCache?.tuning_log_min ?? 8;
      const max = storeCache?.tuning_log_max_cap ?? 500;
      n = Math.round(Number(n));
      if (!Number.isFinite(n) || n < min || n > max) {
        showOptionsMsg(`Enter ${min}–${max} cards`, false);
        return;
      }
      const data = await postStoreAction({ tuning_log_max: n }, btn);
      if (data) {
        const trim = data.details?.trim_tuning_log;
        const trimmed = trim && trim.before > trim.after
          ? ` · trimmed ${trim.before - trim.after} cards`
          : '';
        showOptionsMsg(`Guidance log cap set to ${data.tuning_log_max}${trimmed}`, true);
      }
    }

    async function runDestructive(action, btn, successMsg) {
      if (!resetConfirmOk()) {
        showOptionsMsg('Type RESET in the confirm box first', false);
        return;
      }
      const data = await postStoreAction({ action, confirm: 'RESET' }, btn);
      if (data) showOptionsMsg(successMsg(data), true);
    }

    document.getElementById('retentionApply')?.addEventListener('click', () =>
      applyRetention(document.getElementById('retentionCustom').value));
    document.getElementById('retentionCustom')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') applyRetention(e.target.value);
    });
    document.getElementById('openOptionsRetention')?.addEventListener('click', () => {
      setTab('options', 'optionsData', true);
    });
    document.getElementById('driveList')?.addEventListener('click', (e) => {
      if (e.target.closest('[data-open-guidance-tools]')) openGuidanceDataTools();
    });

    document.getElementById('tuningLogApply')?.addEventListener('click', () =>
      applyTuningLogMax(document.getElementById('tuningLogCustom').value));
    document.getElementById('tuningLogCustom')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') applyTuningLogMax(e.target.value);
    });
    document.getElementById('tuningLogTrim')?.addEventListener('click', async (e) => {
      const data = await postStoreAction({ action: 'trim_tuning_log' }, e.currentTarget);
      if (data) {
        const t = data.details?.trim_tuning_log || {};
        const dropped = (t.before || 0) - (t.after || 0);
        showOptionsMsg(
          dropped > 0
            ? `Trimmed Guidance log to ${t.after} cards (removed ${dropped})`
            : `Already within cap (${t.after ?? data.tuning_log_entries} cards)`,
          true,
        );
      }
    });

    document.getElementById('resetConfirmInput')?.addEventListener('input', syncResetButtons);
    document.getElementById('btnClearSamples')?.addEventListener('click', (e) => {
      runDestructive('clear_samples', e.currentTarget, (d) => {
        const h = d.details?.clear_history || {};
        return `Cleared ${(h.cleared_samples || 0).toLocaleString()} samples · ${h.cleared_sessions || 0} sessions`;
      });
    });
    document.getElementById('btnClearTuningLog')?.addEventListener('click', (e) => {
      runDestructive('clear_tuning_log', e.currentTarget, (d) =>
        `Cleared ${d.details?.cleared_tuning_entries ?? 0} Guidance log cards`);
    });
    document.getElementById('btnResetGuidancePrefs')?.addEventListener('click', (e) => {
      runDestructive('reset_guidance_prefs', e.currentTarget, () =>
        'Ignored and marked-fixed lists cleared — cards can reopen');
    });
    document.getElementById('btnClearDiagCache')?.addEventListener('click', async (e) => {
      const data = await postStoreAction({ action: 'clear_diag_cache' }, e.currentTarget);
      if (data) showOptionsMsg('Diagnostics scan cache cleared', true);
    });
    document.getElementById('btnResetAll')?.addEventListener('click', (e) => {
      runDestructive('reset_all_pulse_data', e.currentTarget, (d) => {
        const h = d.details?.clear_history || {};
        return `Reset complete — ${(h.cleared_samples || 0).toLocaleString()} samples, log + prefs cleared`;
      });
    });
    syncResetButtons();

    document.querySelectorAll('[data-hw-scale]').forEach(el => {
      el.addEventListener('input', () => {
        const key = el.dataset.hwScale;
        const lab = document.getElementById(el.id + 'Val');
        const n = Number(el.value);
        if (lab && Number.isFinite(n)) lab.textContent = (HW_SCALE_LABEL[key] || (x => String(x)))(n);
      });
      el.addEventListener('change', () => {
        applyHwScaleSetting(el.dataset.hwScale, el.value);
      });
    });

    const uiScaleRange = document.getElementById('uiScaleRange');
    if (uiScaleRange) {
      // Dragging: only update the % label (full rem reflow every tick feels terrible).
      // Release (change): apply scale + save.
      uiScaleRange.addEventListener('input', () => {
        updateUiScaleLabel(+uiScaleRange.value);
      });
      uiScaleRange.addEventListener('change', () => {
        applyUiScaleSetting(+uiScaleRange.value);
      });
    }

    fetchStore();

    function appendHistoryPoint(point) {
      if (!point || point.ts == null) return;
      const prev = rawHistory.at(-1);
      if (prev && prev.ts === point.ts) return;
      rawHistory.push(point);
      const maxLen = lastStatic?.history_max_sec || 600;
      if (rawHistory.length > maxLen) rawHistory.splice(0, rawHistory.length - maxLen);
    }

    let tickInFlight = false;
    let tickAbort = null;
    let tickGen = 0;
    let wakeRecoverAt = 0;
    const FETCH_TIMEOUT_MS = 5000;

    function clientWallJumped() {
      const wall = Date.now() / 1000;
      const perf = (typeof performance !== 'undefined' ? performance.now() : 0) / 1000;
      const wallDt = wall - lastWallSec;
      const perfDt = Math.max(0, perf - lastPerfSec);
      return (wallDt - perfDt) > CLIENT_WALL_JUMP_SEC || wallDt > 30;
    }

    async function fetchJson(url, timeoutMs = FETCH_TIMEOUT_MS, signal = null) {
      const ctrl = new AbortController();
      const onParent = () => { try { ctrl.abort(); } catch (_) { /* ignore */ } };
      if (signal) {
        if (signal.aborted) {
          const err = new Error('Aborted');
          err.name = 'AbortError';
          throw err;
        }
        signal.addEventListener('abort', onParent, { once: true });
      }
      const timer = setTimeout(() => { try { ctrl.abort(); } catch (_) { /* ignore */ } }, timeoutMs);
      try {
        const res = await fetch(url, { cache: 'no-store', signal: ctrl.signal });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
      } finally {
        clearTimeout(timer);
        if (signal) signal.removeEventListener('abort', onParent);
      }
    }

    /** After suspend/resume or sampler respawn — clear chart pause/zoom and force fresh history. */
    function forceWakeRecover(reason, { kickTick = true } = {}) {
      const now = Date.now();
      // Debounce — visibility+focus+wall-jump often fire together on lid open.
      if (now - wakeRecoverAt < 800) return;
      wakeRecoverAt = now;
      try {
        if (typeof resumeChartsLive === 'function') resumeChartsLive();
      } catch (_) { /* charts may not be wired yet */ }
      metricsBootstrapped = false;
      sameTsStreak = 0;
      lastSampleTs = null;
      try { resetSparkRing(); } catch (_) { /* ignore */ }
      console.info('Cosmic Pulse: wake recover —', reason || 'resume');
      // Abort hung pre-suspend fetch and pull immediately — but not when the
      // current tick asked us only to reset chart state (kickTick: false).
      if (kickTick) {
        tickGen += 1;
        if (tickAbort) {
          try { tickAbort.abort(); } catch (_) { /* ignore */ }
        }
        tickInFlight = false;
        try { tick(); } catch (_) { /* ignore */ }
      }
    }

    // Tab visible after sleep — recover only if the wall clock jumped.
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && clientWallJumped()) {
        forceWakeRecover('visibility');
      }
    });
    window.addEventListener('pageshow', (ev) => {
      if (ev.persisted) forceWakeRecover('pageshow');
    });
    window.addEventListener('focus', () => {
      if (clientWallJumped()) forceWakeRecover('focus-wall-jump');
      lastWallSec = Date.now() / 1000;
      lastPerfSec = (typeof performance !== 'undefined' ? performance.now() : 0) / 1000;
    });

    /** 1 Hz poll: bootstrap once, then slim history points. Render helpers diff via layout keys. */
    async function tick() {
      if (tickInFlight) return;
      const myGen = ++tickGen;
      tickInFlight = true;
      const controller = new AbortController();
      tickAbort = controller;
      try {
        // Client-side suspend/resume: wall jumps while performance.now barely moves.
        const wallNow = Date.now() / 1000;
        const perfNow = (typeof performance !== 'undefined' ? performance.now() : 0) / 1000;
        const wallDt = wallNow - lastWallSec;
        const perfDt = Math.max(0, perfNow - lastPerfSec);
        if ((wallDt - perfDt) > CLIENT_WALL_JUMP_SEC || (wallDt > 5 && perfDt < 2)) {
          // Don't recurse via forceWakeRecover→tick; just reset state here.
          wakeRecoverAt = Date.now();
          try { if (typeof resumeChartsLive === 'function') resumeChartsLive(); } catch (_) { /* ignore */ }
          metricsBootstrapped = false;
          sameTsStreak = 0;
          lastSampleTs = null;
          try { resetSparkRing(); } catch (_) { /* ignore */ }
          console.info('Cosmic Pulse: wake recover — tick-wall-jump');
        }
        lastWallSec = wallNow;
        lastPerfSec = perfNow;

        const url = metricsBootstrapped ? '/api/metrics' : '/api/metrics?bootstrap=1';
        const data = await fetchJson(url, FETCH_TIMEOUT_MS, controller.signal);
        if (myGen !== tickGen) return;
        const wasBootstrap = !metricsBootstrapped;
        if (wasBootstrap) {
          rawHistory = data.history || [];
          lastStatic = data.static || lastStatic;
          metricsBootstrapped = true;
          // Fresh page load: always rebuild spark ring from bootstrap history
          resetSparkRing();
        } else {
          appendHistoryPoint(data.point);
          if (lastStatic) {
            if (data.resolved_insights) lastStatic.resolved_insights = data.resolved_insights;
            if (data.suppressed_insights) lastStatic.suppressed_insights = data.suppressed_insights;
          }
        }
        // Live COSMIC theme tokens (mtime-synced on server) — prefer data.theme, then cosmic_theme
        const liveTheme = data.theme || data.cosmic_theme || data.static?.cosmic_theme || null;
        if (liveTheme && lastStatic) {
          lastStatic.cosmic_theme = liveTheme;
        } else if (wasBootstrap && data.static?.cosmic_theme && lastStatic) {
          lastStatic.cosmic_theme = data.static.cosmic_theme;
        }
        const l = data.latest, s = lastStatic || {};
        if (!l || l.ts == null) throw new Error('metrics missing latest');

        // Stale detection: frozen ts after suspend/resume (HTTP still 200 with old sample).
        const sampleTs = l.ts;
        const nowSec = Date.now() / 1000;
        const ageSec = Math.max(0, nowSec - sampleTs);
        if (sampleTs === lastSampleTs) sameTsStreak += 1;
        else { sameTsStreak = 0; lastSampleTs = sampleTs; }
        const samp = data.sampler || null;
        // Sampler child respawn / resume kill — force UI out of pause/zoom and rebootstrap.
        if (samp) {
          const gen = samp.generation;
          const epoch = samp.resume_epoch;
          if (lastSamplerGeneration != null && gen != null && gen !== lastSamplerGeneration) {
            forceWakeRecover(`generation ${lastSamplerGeneration}→${gen}`, { kickTick: false });
          }
          if (lastResumeEpoch != null && epoch != null && epoch !== lastResumeEpoch) {
            forceWakeRecover(`resume_epoch ${lastResumeEpoch}→${epoch}`, { kickTick: false });
          }
          if (gen != null) lastSamplerGeneration = gen;
          if (epoch != null) lastResumeEpoch = epoch;
        }
        const serverStale = samp && samp.ok === false;
        const serverDegraded = !!(samp && samp.degraded);
        const clientStale = ageSec > STALE_AGE_SEC || sameTsStreak >= SAME_TS_STALE || serverStale;
        const needRebootstrap =
          ageSec > REBOOTSTRAP_STALE_SEC ||
          sameTsStreak >= SAME_TS_REBOOTSTRAP ||
          (samp && samp.age_sec != null && samp.age_sec > REBOOTSTRAP_STALE_SEC);
        if (needRebootstrap) {
          metricsBootstrapped = false;
          try { if (typeof resumeChartsLive === 'function') resumeChartsLive(); } catch (_) { /* ignore */ }
        }

        if (wasBootstrap || l.issues_by_game) {
          cachedIssuesByGame = l.issues_by_game || cachedIssuesByGame;
          lastIssuesFetchKey = hintsStructKey(l.tuning);
        } else if (hintsStructKey(l.tuning) !== lastIssuesFetchKey) {
          await refreshIssuesByGame(l.tuning);
        }
        const issuesByGame = patchIssuesRunning(cachedIssuesByGame, l.games);
        lastLatest = l;
        lastComparison = l.comparison;
        try {
          sparkRingIngest(l);
        } catch (_) { /* ignore */ }
        if (document.visibilityState === 'hidden') {
          return;
        }
        try {
        // Chrome theme: Cosmic mode tracks desktop light/dark live via mtime; other modes ignore.
        let themeChanged = false;
        const themeTokens = liveTheme || s?.cosmic_theme;
        if (themeMode === 'cosmic' && themeTokens) {
          if (themeTokens.available) {
            themeChanged = applyChromeTheme(themeTokens);
            if (!themePreviewMode) {
              paintThemePreview(themeTokens, 'cosmic');
              updateThemeStatus(themeTokens);
            }
          } else {
            // Still push --cosmic-* fallbacks if present
            applyThemeCssVars(themeTokens);
          }
        } else if (wasBootstrap) {
          themeChanged = !!applyThemeFromSettings({ force: true });
        } else {
          updateThemeStatus(s?.cosmic_theme);
        }
        const mem = s.memory || {};
        const rig = s.rig || {};
        document.getElementById('clock').textContent = fmtTime(l.ts);
        renderPlatformBadges(s);
        renderRigStrip(s, l);
        updateGpuBwTitle(s);
        renderStorageDrives(s, l);
        updateMetaLine(s, l);
        updateGameContext(s, l);
        renderSummaryBar(l, l.tuning, l.comparison);
        renderVisualDashboard(l, l.comparison);
        renderBandwidth(l);
        renderComparison(l.comparison, mem, s.pulse_root);
        renderWarnings(l.tuning);
        syncHwFocusDOM();
        if (activeTab === 'fixes') {
          renderFixes(l.tuning);
          renderGameIssues(issuesByGame);
        }
        renderBacklog(s.backlog);
        renderTools(s.tools);
        const sh = l.sensor_health;
        if (sh) {
          const el = document.getElementById('sensorStatus');
          if (el) {
            el.textContent = `${sh.ok}/${sh.total} sensors reporting`;
            el.className = 'sensor-status' + (sh.missing?.length ? '' : ' ok');
            if (sh.missing?.length) el.textContent += ` · missing: ${sh.missing.join(', ')}`;
          }
        }
        if (isDrillOpen('drill-compute')) {
          renderCores(l.cpu?.per_core);
          const vs = document.getElementById('vramStat');
          const g = l.gpu?.discrete || {};
          if (vs) vs.innerHTML = `${g.vram_used_mb ?? '—'}<small> / ${g.vram_total_mb ?? '—'} MB</small>`;
          setMeterWidth(document.getElementById('vramMeter'), g.vram_pct ?? 0);
          const gd = document.getElementById('gpuDetail');
          if (gd) gd.textContent =
            `${g.gfx_mhz ?? '—'} MHz · Fan ${g.fan_rpm ?? '—'} rpm · VRAM ${g.mem_temp_c ?? '—'}°C · PCIe ${g.pcie_active || g.pcie_link || '—'}`;
        }
        renderSensorGroups(l.sensors || []);
        renderCharts();
        if (themeChanged) renderSparkChart();
        renderGamePerformance(l, s);
        if (isDrillOpen('drill-game')) renderProcs(l.game_procs, l.game_totals);
        if (++storeTick % 30 === 0) fetchStore();
        if (storeTick % 90 === 0) fetchDiagnostics();
        if (clientStale) {
          document.getElementById('liveDot').style.background = 'var(--amber, #e6a817)';
          document.getElementById('liveLabel').textContent = 'Stale — recovering…';
        } else if (serverDegraded) {
          document.getElementById('liveDot').style.background = 'var(--amber, #e6a817)';
          document.getElementById('liveLabel').textContent = 'Degraded — core metrics only';
        } else {
          document.getElementById('liveDot').style.background = 'var(--lime)';
          document.getElementById('liveLabel').textContent = 'Online';
        }
        } catch (renderErr) {
          console.warn('Cosmic Pulse: tick render failed', renderErr);
        }
      } catch (err) {
        if (myGen !== tickGen) return;
        const aborted = err && (err.name === 'AbortError' || /abort/i.test(String(err.message || err)));
        if (aborted) {
          const dot = document.getElementById('liveDot');
          const lab = document.getElementById('liveLabel');
          if (dot) dot.style.background = 'var(--amber, #e6a817)';
          if (lab) lab.textContent = 'Reconnecting…';
          return;
        }
        metricsBootstrapped = false;
        try { if (typeof resumeChartsLive === 'function') resumeChartsLive(); } catch (_) { /* ignore */ }
        const dot = document.getElementById('liveDot');
        const lab = document.getElementById('liveLabel');
        if (dot) dot.style.background = 'var(--hot)';
        if (lab) lab.textContent = 'Offline';
      } finally {
        if (myGen === tickGen) tickInFlight = false;
      }
    }

    let vizFocus = sessionStorage.getItem('pulse-viz-focus') || 'rig';
    let sensorStripExpanded = sessionStorage.getItem('pulse-sensors-expanded') === '1';

    function setVizFocus(tab) {
      // Game performance is a permanent hero — not a Live lab tab.
      const allowed = new Set(['rig', 'index', 'stutter']);
      if (tab === 'game') {
        scrollToElement(document.getElementById('gamePerformanceHero'));
        tab = 'rig';
      }
      if (!allowed.has(tab)) tab = 'rig';
      vizFocus = tab;
      sessionStorage.setItem('pulse-viz-focus', tab);
      const grid = document.getElementById('vizGrid');
      grid?.classList.remove('viz-focus-rig', 'viz-focus-index', 'viz-focus-stutter', 'viz-focus-game');
      grid?.classList.add(`viz-focus-${tab}`);
      document.querySelectorAll('.viz-tab').forEach(btn => {
        const on = btn.dataset.vizTab === tab;
        btn.classList.toggle('active', on);
        btn.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      // Chart.js needs a resize after display:none → visible
      requestAnimationFrame(() => {
        try {
          if (tab === 'rig') {
            sparkChart?.resize();
            renderSparkChart();
          }
          if (tab === 'index') {
            indexChart?.resize();
            renderIndexChart();
          }
          if (tab === 'stutter') {
            stutterChart?.resize();
            renderStutterChart();
          }
        } catch (_) { /* charts may not exist yet */ }
      });
    }

    function syncSensorStripExpanded() {
      const el = document.getElementById('sensorStrip');
      const btn = document.getElementById('sensorStripToggle');
      if (!el || !btn) return;
      el.classList.toggle('collapsed', !sensorStripExpanded);
      // Collapsed = CPU/GPU/VRAM/disk temps; expanded = temps + I/O + network rates
      btn.textContent = sensorStripExpanded ? 'Temps only' : 'Show more';
      btn.setAttribute('aria-expanded', sensorStripExpanded ? 'true' : 'false');
      btn.title = sensorStripExpanded
        ? 'Hide I/O and network rates — keep temperatures'
        : 'CPU, GPU, VRAM, and disk temps always show. Expand for I/O and network rates.';
    }

    function syncVizTabBadges(l, comparison) {
      const idxEl = document.getElementById('vizTabIndexVal');
      const stEl = document.getElementById('vizTabStutterVal');
      const idx = Number(comparison?.session_index);
      const hitch = Number(l?.stutter?.score);
      if (idxEl) idxEl.textContent = Number.isFinite(idx) ? String(Math.round(idx)) : '';
      if (stEl) stEl.textContent = Number.isFinite(hitch) ? String(Math.round(hitch)) : '';
      const stTab = document.querySelector('.viz-tab[data-viz-tab="stutter"]');
      if (stTab) {
        const hot = Number.isFinite(hitch) && hitch >= 50;
        const warn = Number.isFinite(hitch) && hitch >= 30 && hitch < 50;
        stTab.classList.toggle('is-hot', hot);
        stTab.classList.toggle('is-warn', warn);
      }
      const idxTab = document.querySelector('.viz-tab[data-viz-tab="index"]');
      if (idxTab) {
        const pushed = Number.isFinite(idx) && idx >= 71;
        idxTab.classList.toggle('is-warn', pushed);
        idxTab.classList.toggle('is-hot', false);
      }
    }

    document.querySelectorAll('.viz-tab').forEach(btn => {
      btn.addEventListener('click', () => setVizFocus(btn.dataset.vizTab));
    });
    const hitchDial = document.querySelector('#glanceGrid [data-dial="hitch"]');
    if (hitchDial) {
      hitchDial.addEventListener('click', () => jumpTo('viz-stutter'));
      hitchDial.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          jumpTo('viz-stutter');
        }
      });
    }
    document.getElementById('sensorStripToggle')?.addEventListener('click', () => {
      sensorStripExpanded = !sensorStripExpanded;
      sessionStorage.setItem('pulse-sensors-expanded', sensorStripExpanded ? '1' : '0');
      syncSensorStripExpanded();
    });
    document.getElementById('sensorStripDrillLink')?.addEventListener('click', () => jumpTo('drill-sensors'));

    // Game performance is the top hero; Live lab is Snapshot / Index / Stutter only
    restoreOpenPanels();
    if (vizFocus === 'game') vizFocus = 'rig';
    setVizFocus(vizFocus);
    syncSensorStripExpanded();

    document.getElementById('rigFocusClear')?.addEventListener('click', () => setHwFocus(null));
    window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', () => {
      document.querySelectorAll('#summaryBar [data-hw], #vizPanel [data-hw], #warningList .warn-row[data-hw]').forEach(el => {
        clearHwFilterHide(el);
        if (hwItemVisible(el)) {
          el.classList.remove('hw-filtered-hidden', 'hw-filtered-out');
          if (el.matches('.warn-row[data-hw]')) el.style.maxHeight = '';
        } else {
          el.classList.add('hw-filtered-out', 'hw-filtered-hidden');
        }
      });
      scheduleNocEmptyStates();
    });
    bindScrollContainment();
    initStaticGlyphs();
    syncHwFocusDOM();
    tick();
    setInterval(tick, 1000);
