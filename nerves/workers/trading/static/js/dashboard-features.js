// ═══ INDICATORS TAB — USE /api/scan/trigger ═══
let indVersion = 'v1';

// ── Capture Studio live chart state ──────────────────────────────────────────
let _csLiveTimer    = null;   // interval handle for 30s auto-refresh
let _captureRunning = false;  // prevent concurrent captures
let _csChart        = null;   // LightweightCharts instance
let _csCandleSeries = null;   // candleSeries reference
let _csEma9Series   = null;
let _csEma21Series  = null;
let _csEma50Series  = null;
let _csBollUpper    = null;
let _csBollLower    = null;
let _csVolSeries    = null;
let _csLastSymbol   = null;
let _csLastInterval = null;
let _csDebounceTimer = null;

function setIndVersion(v) {
  indVersion = v;
  const p1 = document.getElementById('pill-v1');
  const p2 = document.getElementById('pill-v2');
  if (p1) p1.className = `vpill ${v === 'v1' ? 'active' : ''}`;
  if (p2) p2.className = `vpill ${v === 'v2' ? 'active' : ''}`;
  const g1 = document.getElementById('pine-v1-group');
  const g2 = document.getElementById('pine-v2-group');
  if (g1) g1.style.display = v === 'v1' ? 'block' : 'none';
  if (g2) g2.style.display = v === 'v2' ? 'block' : 'none';
}

let lastScanResults = [];

async function loadIndicators() {
  const sym = document.getElementById('indSymbolSelect')?.value || '';
  if (!sym || lastScanResults.length === 0) { renderEmptyIndicators(); return; }
  const r = lastScanResults.find(x => x.symbol === sym);
  if (!r) { renderEmptyIndicators(); return; }
  renderScore(r.trend_template_score || 0);
  renderMAs(r);
  renderVCP(r);
  renderRS(r);
  renderConditions(r);
}

function renderEmptyIndicators() {
  const el = id => document.getElementById(id);
  if (el('scoreNum')) el('scoreNum').textContent = '—';
  if (el('scoreLabel')) { el('scoreLabel').textContent = 'Run scan first'; el('scoreLabel').className = 'score-label'; }
  if (el('ringFill')) el('ringFill').setAttribute('stroke-dasharray', '0 314');
  if (el('maList')) el('maList').innerHTML = '<p class="muted-label">Run Scan → then view indicators</p>';
  if (el('vcpContent')) el('vcpContent').innerHTML = '<p class="muted-label">No VCP data</p>';
  if (el('rsContent')) el('rsContent').innerHTML = '<p class="muted-label">No RS data</p>';
  if (el('condGrid')) el('condGrid').innerHTML = '<p class="muted-label">No data available</p>';
}

function renderScore(score) {
  const el = document.getElementById('scoreNum');
  const label = document.getElementById('scoreLabel');
  const ring = document.getElementById('ringFill');
  if (!el) return;
  el.textContent = score;
  const pct = (score / 8) * 314;
  if (ring) ring.setAttribute('stroke-dasharray', `${pct} 314`);
  if (label) {
    if (score >= 7) { label.textContent = 'STRONG TREND'; label.className = 'score-label pass'; if (ring) ring.style.stroke = 'var(--buy)'; }
    else if (score >= 5) { label.textContent = 'MODERATE'; label.className = 'score-label warn'; if (ring) ring.style.stroke = 'var(--warn)'; }
    else { label.textContent = 'WEAK'; label.className = 'score-label fail'; if (ring) ring.style.stroke = 'var(--sell)'; }
  }
}

function renderMAs(r) {
  const el = document.getElementById('maList');
  if (!el) return;
  const chgColor = (r.change_pct || 0) >= 0 ? 'var(--buy)' : 'var(--sell)';
  el.innerHTML = `
    <div class="ma-row"><span class="ma-name">Price</span><span class="ma-val" style="font-family:var(--mono)">${r.price || '—'}</span></div>
    <div class="ma-row"><span class="ma-name">Change</span><span class="ma-val" style="color:${chgColor}">${(r.change_pct || 0).toFixed(2)}%</span></div>
    <div class="ma-row"><span class="ma-name">Stage</span><span class="ma-val">${r.trend_template_stage || '—'}</span></div>
    <div class="ma-row"><span class="ma-name">Score</span><span class="ma-val">${r.trend_template_score}/8</span></div>
    <div class="ma-row"><span class="ma-name">Vol Ratio</span><span class="ma-val">${r.volume_ratio || '—'}x</span></div>
  `;
}

function renderVCP(r) {
  const el = document.getElementById('vcpContent');
  if (!el) return;
  el.innerHTML = `
    <div style="text-align:center;margin:10px 0">
      <div style="font-size:2.5rem;margin-bottom:8px">${r.vcp_detected ? '🔺' : '⬜'}</div>
      <div style="font-weight:700;color:${r.vcp_detected ? 'var(--buy)' : 'var(--text-muted)'}">${r.vcp_detected ? 'VCP DETECTED!' : 'No VCP'}</div>
      <div style="font-size:0.78rem;color:var(--text-muted);margin-top:6px">${r.vcp_note || ''}</div>
      <div style="margin-top:8px;font-size:0.8rem">
        <span>Range: ${r.range_ratio || '—'}</span> · <span>Pivot: ${r.pivot_level || '—'}</span>
      </div>
    </div>`;
}

function renderRS(r) {
  const el = document.getElementById('rsContent');
  if (!el) return;
  el.innerHTML = `
    <div style="text-align:center;margin:10px 0">
      <div style="font-size:2rem;margin-bottom:8px">💪</div>
      <div style="font-size:0.85rem;color:var(--text-sub)">Volume Ratio</div>
      <div style="font-size:1.5rem;font-weight:700;font-family:var(--mono);margin-top:4px">${r.volume_ratio || '—'}x</div>
      <div style="font-size:0.78rem;color:var(--text-muted);margin-top:6px">${r.vol_breakout ? '🚀 Volume Breakout!' : 'Normal volume'}</div>
    </div>`;
}

function renderConditions(r) {
  const el = document.getElementById('condGrid');
  if (!el) return;
  const criteria = r.trend_template_criteria || {};
  const labels = ['Giá > SMA 150 & 200', 'SMA 150 > SMA 200', 'SMA 200 dốc lên',
    'SMA 50 > SMA 150 & 200', 'Giá > SMA 50', 'Giá cách đáy 52W > 30%',
    'Giá cách đỉnh 52W < 25%', 'RS > Benchmark'];
  const keys = Object.keys(criteria);
  if (keys.length === 0) {
    el.innerHTML = labels.map((l, i) => `<div class="cond-item"><span class="cond-icon">⬜</span><span>${i + 1}. ${l}</span></div>`).join('');
    return;
  }
  el.innerHTML = keys.map((k, i) => {
    const pass = criteria[k];
    return `<div class="cond-item ${pass ? 'pass' : 'fail'}"><span class="cond-icon">${pass ? '✅' : '❌'}</span><span>${i + 1}. ${labels[i] || k}</span></div>`;
  }).join('');
}

// ═══ NOTIFICATIONS — BUILD FROM SIGNALS + TRADES ═══
let notifications = [];
async function loadNotifications() {
  const data = await apiFetch('/trades?limit=50');
  if (!data || !data.trades) return;
  notifications = data.trades.map(t => ({
    type: t.signal_action === 'alert' ? 'WEBHOOK' : 'TRADE',
    title: `${(t.side || '').toUpperCase()} ${t.symbol || ''}`,
    msg: `Price: ${t.executed_price || '—'} | Qty: ${t.executed_qty || t.requested_qty || '—'} | Status: ${(t.status || '—').toUpperCase()}`,
    time: t.created_at,
    score: t.combined_score
  }));
  renderNotifications(notifications);
  const badge = document.getElementById('notifBadge');
  if (badge) badge.textContent = notifications.length;
}

function filterNotifs() {
  const f = document.getElementById('notifFilter')?.value || 'all';
  if (f === 'all') renderNotifications(notifications);
  else renderNotifications(notifications.filter(n => n.type === f));
}

function renderNotifications(list) {
  const el = document.getElementById('notifList');
  if (!el) return;
  if (!list.length) { el.innerHTML = '<div class="empty-state"><div class="icon">🔔</div><h3>Không có thông báo</h3></div>'; return; }
  el.innerHTML = list.map(n => {
    const icons = { WEBHOOK: '📡', TRADE: '💰', VISION: '👁', BRIEF: '🌅' };
    const tags = { WEBHOOK: 'tag-webhook', TRADE: 'tag-trade', VISION: 'tag-vision', BRIEF: 'tag-brief' };
    return `<div class="notif-item">
      <div class="notif-icon">${icons[n.type] || '📋'}</div>
      <div class="notif-body">
        <div class="notif-title">${n.title} <span class="notif-tag ${tags[n.type] || ''}">${n.type}</span></div>
        <div class="notif-msg">${n.msg}</div>
      </div>
      <div class="notif-time">${n.time || '—'}</div>
    </div>`;
  }).join('');
}

function clearNotifs() {
  notifications = [];
  renderNotifications([]);
  const badge = document.getElementById('notifBadge');
  if (badge) badge.textContent = '0';
}


// ─────────────────────────────────────────────────────────────────────────────
//  STEALTH CAPTURE STUDIO — Live Chart Engine (LightweightCharts v4)
//  6-Phase Pine Script Virtual Layout: Candles + Vol + EMA + RSI + MACD + BB
//  + MIS/MTT Signal Markers + Inset Parent TF Chart
// ─────────────────────────────────────────────────────────────────────────────

/** Global chart state */
const _CS = {
  chart:        null,   // LightweightCharts instance
  candleSeries: null,   // Main candlestick
  volSeries:    null,   // Volume histogram
  ema9Series:   null,
  ema21Series:  null,
  ema50Series:  null,
  bbUpper:      null,
  bbMid:        null,
  bbLower:      null,
  rsiSeries:    null,
  macdSeries:   null,
  macdSignal:   null,
  macdHist:     null,
  _candles:     null,   // raw Binance candles cache
  _sym:         '',
  _interval:    '',
};

// ── TF map ──
const _csTfMap        = {'15': '15m', '60': '1h', '240': '4h', 'D': '1d', 'W': '1w'};
const _csParentTfMap  = {'15m': '1h', '1h': '4h', '4h': '1d', '1d': '1w', '1w': '1M'};

// ── TV Color Palette ──
const TV = {
  GREEN:       '#26a69a',
  RED:         '#ef5350',
  BG:          '#131722',
  GRID:        'rgba(42, 46, 57, 0.5)',
  TEXT:        '#787b86',
  BORDER:      'rgba(42, 46, 57, 0.8)',
  EMA9:        '#26c6da',
  EMA21:       '#ff9800',
  EMA50:       '#ab47bc',
  BB:          'rgba(33, 150, 243, 0.6)',
  RSI:         '#e040fb',
  MACD_LINE:   '#42a5f5',
  MACD_SIG:    '#ef5350',
  MACD_HIST_G: 'rgba(38,166,154,0.7)',
  MACD_HIST_R: 'rgba(239,83,80,0.7)',
  MTT_BUY:     '#26a69a',
  MTT_SELL:    '#ef5350',
  MIS_BUY:     '#ff9800',
  MIS_SELL:    '#ab47bc',
};

// ─────────────────────────────────────────────────────────────────────────────
//  MAIN ENTRY: loadCSLiveChart()
// ─────────────────────────────────────────────────────────────────────────────
async function loadCSLiveChart() {
  const container = document.getElementById('csLiveChart');
  if (!container) return;

  const sym       = (document.getElementById('captureSymbol')?.value || 'BTCUSDT').trim().toUpperCase();
  const tfRaw     = document.getElementById('captureTimeframe')?.value || '60';
  const interval  = _csTfMap[tfRaw] || '1h';
  const showInset = document.getElementById('showParentChart')?.value === 'yes';
  const insetPos  = document.getElementById('insetPosition')?.value || 'bottom-right';
  const cleanSym  = sym.includes(':') ? sym.split(':')[1] : sym;

  // Update live label
  const lbl = document.getElementById('csLiveLabel');
  if (lbl) lbl.textContent = `${sym} · ${interval.toUpperCase()} · Binance`;

  // ── Phase 1: Init or reuse LightweightCharts instance ──
  _csInitChart(container);

  // ── Fetch candles ──
  try {
    const res = await fetch(`https://api.binance.com/api/v3/klines?symbol=${cleanSym}&interval=${interval}&limit=120`);
    if (!res.ok) throw new Error('Binance API error');
    const raw = await res.json();
    if (!raw || !raw.length) throw new Error('No candle data');

    _CS._candles  = raw;
    _CS._sym      = cleanSym;
    _CS._interval = interval;

    // ── Set candle data ──
    const ohlcv = raw.map(c => ({
      time:  Math.floor(c[0] / 1000),
      open:  parseFloat(c[1]),
      high:  parseFloat(c[2]),
      low:   parseFloat(c[3]),
      close: parseFloat(c[4]),
    }));
    _CS.candleSeries.setData(ohlcv);

    // ── Volume ──
    const maxVol = Math.max(...raw.map(c => parseFloat(c[5])));
    _CS.volSeries.setData(raw.map(c => ({
      time:  Math.floor(c[0] / 1000),
      value: parseFloat(c[5]),
      color: parseFloat(c[4]) >= parseFloat(c[1]) ? 'rgba(38,166,154,0.35)' : 'rgba(239,83,80,0.35)',
    })));

    // Update current price in bar
    const lastC = raw[raw.length - 1];
    const lastClose = parseFloat(lastC[4]);
    const priceEl = document.getElementById('csLivePrice');
    if (priceEl) {
      const bull = lastClose >= parseFloat(lastC[1]);
      priceEl.textContent = _tvFmtPrice(lastClose);
      priceEl.style.color = bull ? TV.GREEN : TV.RED;
    }

    // ── Phase 2: EMA Overlays ──
    const closes = raw.map(c => parseFloat(c[4]));
    const times  = raw.map(c => Math.floor(c[0] / 1000));
    _csSetEMA(times, closes);

    // ── Regime badge (MTT SMA logic) ──
    _csSetRegimeBadge(closes);

    // ── Phase 3: RSI ──
    _csSetRSI(times, closes);

    // ── Phase 4: Signal Markers (MIS/MTT from server + MIS client-side) ──
    // Pre-compute MIS signals client-side as fallback
    _CS._misSignals = _calcMISSignals(times, closes);
    await _csSetMarkers(cleanSym, interval, raw);

    // ── Phase 5: Bollinger Bands + MACD ──
    _csSetBB(times, closes);
    _csSetMACD(times, closes);

    // ── Apply visibility from toggles ──
    updateCSIndicators();

    // ── Phase 6: Inset canvas overlay ──
    if (showInset) {
      await _csDrawInset(cleanSym, interval, insetPos);
    } else {
      _csClearInset();
    }

    // Fit chart to data
    _CS.chart.timeScale().fitContent();

  } catch (e) {
    console.warn('[CS Chart]', e);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
//  PHASE 1: Chart Initialization
// ─────────────────────────────────────────────────────────────────────────────
function _csInitChart(container) {
  if (_CS.chart) {
    // Reuse existing chart — just update data
    return;
  }
  const h = Math.max(container.clientHeight || 380, 380);

  _CS.chart = LightweightCharts.createChart(container, {
    width:  container.clientWidth  || 600,
    height: h,
    layout: {
      background: { type: 'solid', color: TV.BG },
      textColor: TV.TEXT,
      fontFamily: '"JetBrains Mono", monospace',
      fontSize: 10,
    },
    grid: {
      vertLines:  { color: TV.GRID, style: LightweightCharts.LineStyle.Dashed },
      horzLines:  { color: TV.GRID, style: LightweightCharts.LineStyle.Dashed },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: { color: 'rgba(255,255,255,0.2)', width: 1, style: LightweightCharts.LineStyle.Dashed, labelBackgroundColor: '#363a45' },
      horzLine: { color: 'rgba(255,255,255,0.2)', width: 1, style: LightweightCharts.LineStyle.Dashed, labelBackgroundColor: '#363a45' },
    },
    rightPriceScale: {
      borderColor: TV.BORDER,
      scaleMargins: { top: 0.05, bottom: 0.25 },
    },
    timeScale: {
      borderColor: TV.BORDER,
      timeVisible: true,
      secondsVisible: false,
      fixLeftEdge: false,
      fixRightEdge: false,
    },
  });

  // ── Candlestick series ──
  _CS.candleSeries = _CS.chart.addCandlestickSeries({
    upColor:        TV.GREEN,
    downColor:      TV.RED,
    borderUpColor:  TV.GREEN,
    borderDownColor:TV.RED,
    wickUpColor:    TV.GREEN,
    wickDownColor:  TV.RED,
    priceLineVisible: true,
    priceLineColor:   TV.GREEN,
    priceLineWidth:   1,
    priceLineStyle:   LightweightCharts.LineStyle.Dashed,
  });

  // ── Volume histogram (sub-pane via scaleId overlay) ──
  _CS.volSeries = _CS.chart.addHistogramSeries({
    priceFormat:   { type: 'volume' },
    priceScaleId:  'volume',
  });
  _CS.chart.priceScale('volume').applyOptions({
    scaleMargins: { top: 0.82, bottom: 0.00 },
  });

  // ── EMA lines (Phase 2) ──
  _CS.ema9Series  = _CS.chart.addLineSeries({ color: TV.EMA9,  lineWidth: 1, priceLineVisible: false, lastValueVisible: true });
  _CS.ema21Series = _CS.chart.addLineSeries({ color: TV.EMA21, lineWidth: 1, priceLineVisible: false, lastValueVisible: true });
  _CS.ema50Series = _CS.chart.addLineSeries({ color: TV.EMA50, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, visible: false });

  // ── Bollinger Bands (Phase 5) ──
  _CS.bbUpper = _CS.chart.addLineSeries({ color: TV.BB, lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, visible: false });
  _CS.bbMid   = _CS.chart.addLineSeries({ color: TV.BB, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, visible: false });
  _CS.bbLower = _CS.chart.addLineSeries({ color: TV.BB, lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, visible: false });

  // ── RSI pane (Phase 3) ──
  _CS.rsiSeries = _CS.chart.addLineSeries({
    color:            TV.RSI,
    lineWidth:        1,
    priceScaleId:     'rsi',
    priceLineVisible: false,
    lastValueVisible: true,
  });
  _CS.chart.priceScale('rsi').applyOptions({
    scaleMargins: { top: 0.78, bottom: 0.05 },
    borderColor: TV.BORDER,
  });

  // ── MACD pane (Phase 5) ──
  _CS.macdHist = _CS.chart.addHistogramSeries({
    priceScaleId: 'macd',
    priceLineVisible: false,
    lastValueVisible: false,
    visible: false,
  });
  _CS.macdSeries = _CS.chart.addLineSeries({
    color: TV.MACD_LINE, lineWidth: 1,
    priceScaleId: 'macd',
    priceLineVisible: false, lastValueVisible: false, visible: false,
  });
  _CS.macdSignal = _CS.chart.addLineSeries({
    color: TV.MACD_SIG, lineWidth: 1,
    priceScaleId: 'macd',
    priceLineVisible: false, lastValueVisible: false, visible: false,
  });
  _CS.chart.priceScale('macd').applyOptions({
    scaleMargins: { top: 0.88, bottom: 0.00 },
    borderColor: TV.BORDER,
  });

  // Auto-resize
  const ro = new ResizeObserver(() => {
    if (_CS.chart && container.clientWidth > 0) {
      _CS.chart.resize(container.clientWidth, container.clientHeight || 380);
    }
  });
  ro.observe(container);
}

// ─────────────────────────────────────────────────────────────────────────────
//  PHASE 2: EMA Calculations
// ─────────────────────────────────────────────────────────────────────────────
function _calcEMA(closes, period) {
  const k = 2 / (period + 1);
  const result = [];
  let ema = closes.slice(0, period).reduce((a, b) => a + b, 0) / period;
  for (let i = period - 1; i < closes.length; i++) {
    if (i > period - 1) ema = closes[i] * k + ema * (1 - k);
    result.push(ema);
  }
  return result;
}

function _csSetEMA(times, closes) {
  const makeData = (vals, offset) =>
    vals.map((v, i) => ({ time: times[i + offset], value: v }));

  const ema9  = _calcEMA(closes, 9);
  const ema21 = _calcEMA(closes, 21);
  const ema50 = _calcEMA(closes, 50);

  _CS.ema9Series.setData(makeData(ema9, 8));
  _CS.ema21Series.setData(makeData(ema21, 20));
  _CS.ema50Series.setData(makeData(ema50, 49));
}

// ─────────────────────────────────────────────────────────────────────────────
//  MIS Client-Side Signals — EMA20/EMA50 crossover (replicates a007_mis_webhook.pine)
//  Pine logic: longCondition = ta.crossover(fastEMA, slowEMA)  fast=EMA20, slow=EMA50
// ─────────────────────────────────────────────────────────────────────────────
function _calcMISSignals(times, closes) {
  const ema20 = _calcEMA(closes, 20);
  const ema50 = _calcEMA(closes, 50);
  // ema50 starts at index 49, ema20 starts at index 19
  // Align: ema50[i] corresponds to closes[i+49], ema20[i+30] corresponds to same bar
  const offset = 49; // start where ema50 is available
  const signals = [];

  for (let i = 1; i < ema50.length; i++) {
    const ema20Now  = ema20[i + 30];     // ema20 offset = 19, so +30 aligns with ema50 offset 49
    const ema20Prev = ema20[i + 30 - 1];
    const ema50Now  = ema50[i];
    const ema50Prev = ema50[i - 1];
    if (!ema20Now || !ema20Prev) continue;

    const t = times[i + offset];
    if (!t) continue;

    // Crossover: ema20 crosses above ema50 → BUY
    if (ema20Prev <= ema50Prev && ema20Now > ema50Now) {
      signals.push({ time: t, action: 'buy', mode: 'MIS' });
    }
    // Crossunder: ema20 crosses below ema50 → SELL
    else if (ema20Prev >= ema50Prev && ema20Now < ema50Now) {
      signals.push({ time: t, action: 'sell', mode: 'MIS' });
    }
  }
  return signals;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Regime Badge — TREND vs CHOP detection
//  Based on MTT logic: price > SMA50 > SMA150 > SMA200 = TREND, else CHOP
// ─────────────────────────────────────────────────────────────────────────────
function _csSetRegimeBadge(closes) {
  const badge = document.getElementById('csRegimeBadge');
  if (!badge) return;

  if (closes.length < 200) { badge.textContent = ''; return; }

  const sma = (n) => closes.slice(-n).reduce((a, b) => a + b, 0) / n;
  const sma50  = sma(50);
  const sma150 = sma(150);
  const sma200 = sma(200);
  const price  = closes[closes.length - 1];

  // MTT Trend Template simplified: price > SMA50 > SMA150 > SMA200
  const isTrend = price > sma50 && sma50 > sma150 && sma150 > sma200;

  badge.textContent = isTrend ? '📈 TREND' : '⚡ CHOP';
  badge.className   = `cs-regime-badge ${isTrend ? 'trend' : 'chop'}`;
}

// ─────────────────────────────────────────────────────────────────────────────
//  PHASE 3: RSI(14)
// ─────────────────────────────────────────────────────────────────────────────
function _calcRSI(closes, period = 14) {
  const result = [];
  let avgGain = 0, avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff > 0) avgGain += diff;
    else avgLoss -= diff;
  }
  avgGain /= period; avgLoss /= period;
  for (let i = period; i < closes.length; i++) {
    if (i > period) {
      const diff = closes[i] - closes[i - 1];
      avgGain = (avgGain * (period - 1) + (diff > 0 ? diff : 0)) / period;
      avgLoss = (avgLoss * (period - 1) + (diff < 0 ? -diff : 0)) / period;
    }
    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
    result.push(100 - (100 / (1 + rs)));
  }
  return result;
}

function _csSetRSI(times, closes) {
  const rsi = _calcRSI(closes, 14);
  _CS.rsiSeries.setData(rsi.map((v, i) => ({ time: times[i + 14], value: v })));

  // Add overbought/oversold reference lines as price lines
  _CS.rsiSeries.createPriceLine({ price: 70, color: 'rgba(239,83,80,0.4)',   lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: true, title: 'OB' });
  _CS.rsiSeries.createPriceLine({ price: 30, color: 'rgba(38,166,154,0.4)', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: true, title: 'OS' });
  _CS.rsiSeries.createPriceLine({ price: 50, color: 'rgba(120,123,134,0.3)', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: false });
}

// ─────────────────────────────────────────────────────────────────────────────
//  PHASE 4: MIS/MTT Signal Markers
// ─────────────────────────────────────────────────────────────────────────────
async function _csSetMarkers(sym, interval, raw) {
  if (!_CS.candleSeries) return;
  const showMTT = document.getElementById('indMTT')?.checked ?? true;
  const showMIS = document.getElementById('indMIS')?.checked ?? true;
  if (!showMTT && !showMIS) { _CS.candleSeries.setMarkers([]); return; }

  const fromTs = raw[0][0];
  const toTs   = raw[raw.length - 1][0];
  let markers = [];

  // ── Try server-side markers (webhook signals DB) ──
  try {
    const res = await apiFetch(
      `/api/chart-markers?symbol=${sym}&interval=${interval}&from=${fromTs}&to=${toTs}`
    );
    if (res && res.markers && res.markers.length > 0) {
      res.markers.forEach(m => {
        if (m.mode === 'MTT' && !showMTT) return;
        if (m.mode === 'MIS' && !showMIS) return;
        markers.push({
          time:     m.time,
          position: m.action === 'buy' ? 'belowBar' : 'aboveBar',
          shape:    m.action === 'buy' ? 'arrowUp'  : 'arrowDown',
          color:    m.mode === 'MTT'
            ? (m.action === 'buy' ? TV.MTT_BUY : TV.MTT_SELL)
            : (m.action === 'buy' ? TV.MIS_BUY : TV.MIS_SELL),
          size:  1.2,
          text:  `[${m.mode}]${m.confidence ? ' ' + m.confidence + '%' : ''}`,
        });
      });
    }
  } catch (e) {
    // endpoint not yet available — fall through to client-side
  }

  // ── Fallback: use client-side MIS signals if server returned nothing ──
  if (markers.length === 0 && showMIS && _CS._misSignals?.length) {
    const minT = Math.floor(fromTs / 1000);
    const maxT = Math.floor(toTs   / 1000);
    _CS._misSignals
      .filter(s => s.time >= minT && s.time <= maxT)
      .forEach(s => {
        markers.push({
          time:     s.time,
          position: s.action === 'buy' ? 'belowBar' : 'aboveBar',
          shape:    s.action === 'buy' ? 'arrowUp'  : 'arrowDown',
          color:    s.action === 'buy' ? TV.MIS_BUY : TV.MIS_SELL,
          size:     1.0,
          text:     '[MIS]',
        });
      });
  }

  _CS.candleSeries.setMarkers(markers.sort((a, b) => a.time - b.time));
}

// ─────────────────────────────────────────────────────────────────────────────
//  PHASE 5: Bollinger Bands (20, 2σ)
// ─────────────────────────────────────────────────────────────────────────────
function _calcBB(closes, period = 20, stdMul = 2) {
  const upper = [], mid = [], lower = [];
  for (let i = period - 1; i < closes.length; i++) {
    const slice = closes.slice(i - period + 1, i + 1);
    const mean  = slice.reduce((a, b) => a + b, 0) / period;
    const std   = Math.sqrt(slice.map(x => (x - mean) ** 2).reduce((a, b) => a + b, 0) / period);
    upper.push(mean + stdMul * std);
    mid.push(mean);
    lower.push(mean - stdMul * std);
  }
  return { upper, mid, lower };
}

function _csSetBB(times, closes) {
  const { upper, mid, lower } = _calcBB(closes, 20, 2);
  const offset = 19;
  const mk = (arr) => arr.map((v, i) => ({ time: times[i + offset], value: v }));
  _CS.bbUpper.setData(mk(upper));
  _CS.bbMid.setData(mk(mid));
  _CS.bbLower.setData(mk(lower));
}

// ─────────────────────────────────────────────────────────────────────────────
//  PHASE 5: MACD (12, 26, 9)
// ─────────────────────────────────────────────────────────────────────────────
function _csSetMACD(times, closes) {
  const ema12 = _calcEMA(closes, 12);
  const ema26 = _calcEMA(closes, 26);
  const offset26 = 25;

  // MACD line = EMA12 - EMA26 (aligned to longer EMA)
  const macdLine = ema26.map((v, i) => ema12[i + 13] - v);
  // Signal line = EMA9 of MACD line
  const signalLine = _calcEMA(macdLine, 9);
  const histOffset = offset26 + 8;

  const macdTimes   = times.slice(offset26);
  const signalTimes = times.slice(histOffset);

  _CS.macdSeries.setData(macdLine.map((v, i) => ({ time: macdTimes[i], value: v })));
  _CS.macdSignal.setData(signalLine.map((v, i) => ({ time: signalTimes[i], value: v })));
  _CS.macdHist.setData(signalLine.map((v, i) => {
    const macdVal = macdLine[i + 8];
    const histVal = macdVal - v;
    return {
      time:  signalTimes[i],
      value: histVal,
      color: histVal >= 0 ? TV.MACD_HIST_G : TV.MACD_HIST_R,
    };
  }));
}

// ─────────────────────────────────────────────────────────────────────────────
//  Toggle handler — called by all indicator checkboxes
// ─────────────────────────────────────────────────────────────────────────────
function updateCSIndicators() {
  const get = id => document.getElementById(id)?.checked ?? false;

  _CS.ema9Series?.applyOptions({ visible: get('indEma9') });
  _CS.ema21Series?.applyOptions({ visible: get('indEma21') });
  _CS.ema50Series?.applyOptions({ visible: get('indEma50') });

  const bbOn = get('indBB');
  _CS.bbUpper?.applyOptions({ visible: bbOn });
  _CS.bbMid?.applyOptions({ visible: bbOn });
  _CS.bbLower?.applyOptions({ visible: bbOn });

  const rsiOn = get('indRSI');
  _CS.rsiSeries?.applyOptions({ visible: rsiOn });

  const macdOn = get('indMACD');
  _CS.macdSeries?.applyOptions({ visible: macdOn });
  _CS.macdSignal?.applyOptions({ visible: macdOn });
  _CS.macdHist?.applyOptions({ visible: macdOn });

  // MIS/MTT markers — re-fetch if exists
  if (_CS._candles && _CS._sym) {
    _csSetMarkers(_CS._sym, _CS._interval, _CS._candles);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
//  PHASE 6: Inset Parent Chart (Canvas overlay over LightweightCharts)
// ─────────────────────────────────────────────────────────────────────────────
async function _csDrawInset(sym, interval, position) {
  const container  = document.getElementById('csLiveChart');
  const insetCanvas = document.getElementById('csInsetCanvas');
  if (!insetCanvas || !container) return;

  // Sync canvas size to container
  const w = container.clientWidth;
  const h = container.clientHeight || 380;
  insetCanvas.width  = w;
  insetCanvas.height = h;
  insetCanvas.style.width  = w + 'px';
  insetCanvas.style.height = h + 'px';

  const parentInterval = _csParentTfMap[interval] || '1d';
  try {
    const res = await fetch(`https://api.binance.com/api/v3/klines?symbol=${sym}&interval=${parentInterval}&limit=30`);
    if (!res.ok) return;
    const pCandles = await res.json();
    if (!pCandles || pCandles.length < 5) return;

    _drawInsetChart(
      insetCanvas.getContext('2d'),
      pCandles, _CS._candles,
      w, h, position, sym, parentInterval
    );
  } catch (e) {
    // silently skip
  }
}

function _csClearInset() {
  const c = document.getElementById('csInsetCanvas');
  if (c) c.getContext('2d').clearRect(0, 0, c.width, c.height);
}

/**
 * Draw a mini inset candlestick chart with yellow highlight box
 * showing where the main timeframe candles fit in the parent view.
 */
function _drawInsetChart(ctx, pCandles, mainCandles, fullW, fullH, position, symbol, parentTf) {
  // LightweightCharts renders its own price scale at the right (~72px wide)
  const priceScaleW = 72;
  const insetW = Math.min(Math.round(fullW * 0.30), 200);
  const insetH = Math.min(Math.round(fullH * 0.36), 130);
  const margin = 12;
  const topPad = 30; // below the TV toolbar
  const botPad = 20;

  let ix, iy;
  switch (position) {
    case 'top-left':    ix = margin;                             iy = topPad; break;
    case 'top-right':   ix = fullW - insetW - priceScaleW - margin; iy = topPad; break;
    case 'bottom-left': ix = margin;                             iy = fullH - insetH - botPad; break;
    case 'bottom-right':
    default:            ix = fullW - insetW - priceScaleW - margin; iy = fullH - insetH - botPad; break;
  }

  // Clear inset zone
  ctx.clearRect(ix - 2, iy - 2, insetW + 4, insetH + 4);

  // Background
  ctx.save();
  ctx.globalAlpha = 0.94;
  ctx.fillStyle   = 'rgba(13, 17, 28, 0.92)';
  ctx.strokeStyle = 'rgba(42, 46, 57, 0.8)';
  ctx.lineWidth   = 1;
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(ix, iy, insetW, insetH, 6);
  else ctx.rect(ix, iy, insetW, insetH);
  ctx.fill();
  ctx.stroke();
  ctx.globalAlpha = 1;

  // Label
  ctx.fillStyle = '#e2e8f0';
  ctx.font = 'bold 10px "JetBrains Mono", monospace';
  ctx.fillText(`${symbol} ${parentTf.toUpperCase()}`, ix + 8, iy + 14);

  // Chart area
  const padL = 6, padR = 6, padT = 22, padB = 6;
  const cW = insetW - padL - padR;
  const cH = insetH - padT - padB;
  const cX = ix + padL, cY = iy + padT;

  // Price range
  let minP = Infinity, maxP = -Infinity;
  pCandles.forEach(c => {
    const lo = parseFloat(c[3]), hi = parseFloat(c[2]);
    if (lo < minP) minP = lo; if (hi > maxP) maxP = hi;
  });
  const range = (maxP - minP) || 1;
  minP -= range * 0.05; maxP += range * 0.05;
  const finalR = maxP - minP || 1;
  const getY = v => cY + cH * (1 - (v - minP) / finalR);
  const spacing = cW / pCandles.length;
  const cw = Math.max(spacing * 0.55, 1.5);

  pCandles.forEach((c, i) => {
    const o = parseFloat(c[1]), h = parseFloat(c[2]);
    const l = parseFloat(c[3]), cl = parseFloat(c[4]);
    const bull = cl >= o;
    const color = bull ? '#26a69a' : '#ef5350';
    const x = cX + i * spacing + spacing / 2;
    ctx.strokeStyle = color; ctx.lineWidth = 0.8;
    ctx.beginPath(); ctx.moveTo(x, getY(h)); ctx.lineTo(x, getY(l)); ctx.stroke();
    ctx.fillStyle = color;
    ctx.fillRect(x - cw / 2, Math.min(getY(o), getY(cl)), cw, Math.abs(getY(cl) - getY(o)) || 1);
  });

  // Yellow highlight (main chart time range)
  if (mainCandles && mainCandles.length > 0) {
    const mS = mainCandles[0][0], mE = mainCandles[mainCandles.length - 1][6];
    let hlS = -1, hlE = -1;
    pCandles.forEach((c, i) => {
      if (c[6] >= mS && c[0] <= mE) { if (hlS === -1) hlS = i; hlE = i; }
    });
    if (hlS >= 0) {
      const hlX = cX + hlS * spacing;
      const hlW = (hlE - hlS + 1) * spacing;
      ctx.strokeStyle = '#f59e0b'; ctx.lineWidth = 1.5; ctx.setLineDash([]);
      ctx.strokeRect(hlX + 1, cY, hlW, cH);
      ctx.fillStyle = 'rgba(245,158,11,0.1)';
      ctx.fillRect(hlX + 1, cY, hlW, cH);
    }
  }
  ctx.restore();
}

// ─────────────────────────────────────────────────────────────────────────────
//  Polling lifecycle
// ─────────────────────────────────────────────────────────────────────────────
function startCSLivePolling() {
  loadCSLiveChart();
  if (_csLiveTimer) clearInterval(_csLiveTimer);
  _csLiveTimer = setInterval(loadCSLiveChart, 30000);
}

function stopCSLivePolling() {
  if (_csLiveTimer) { clearInterval(_csLiveTimer); _csLiveTimer = null; }
}


function _setStep(id, state) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = `cap-step ${state}`;
}

async function runStealthCapture() {
  if (_captureRunning) return;
  _captureRunning = true;

  const sym = document.getElementById('captureSymbol')?.value || 'BTCUSDT';
  const btn = document.getElementById('captureBtn');
  const btnText = document.getElementById('captureBtnText');
  const btnIcon = document.getElementById('captureBtnIcon');
  const progress = document.getElementById('captureProgress');

  // Reset UI
  if (btn) btn.disabled = true;
  if (btnIcon) btnIcon.textContent = '⏳';
  if (btnText) btnText.textContent = 'Đang capture...';
  if (progress) progress.style.display = 'flex';
  ['step-mcp','step-shot','step-crop','step-ai','step-save'].forEach(s => _setStep(s, ''));

  // Step 1: MCP check (simulated — the endpoint does the actual check)
  _setStep('step-mcp', 'active');
  await new Promise(r => setTimeout(r, 300));
  _setStep('step-mcp', 'done');

  // Step 2: Screenshot
  _setStep('step-shot', 'active');

  const tf = document.getElementById('captureTimeframe')?.value || '1H';
  const showParent = document.getElementById('showParentChart')?.value || 'yes';
  const insetPos = document.getElementById('insetPosition')?.value || 'bottom-right';
  let result;
  try {
    result = await apiFetch(`/api/vision/capture?symbol=${encodeURIComponent(sym)}&timeframe=${encodeURIComponent(tf)}&show_parent=${encodeURIComponent(showParent)}&inset_position=${encodeURIComponent(insetPos)}`, {
      method: 'POST'
    });
  } catch (e) {
    result = null;
  }

  if (!result || result.status !== 'ok') {
    const err = result?.detail || 'Capture failed — check CDP connection';
    ['step-shot','step-crop','step-ai','step-save'].forEach(s => _setStep(s, ''));
    showToast(`❌ ${err}`, 'error');
    _resetCaptureBtn();
    _captureRunning = false;
    return;
  }

  // Animate remaining steps (server already completed them)
  for (const [step, delay] of [['step-shot',150],['step-crop',200],['step-ai',300],['step-save',150]]) {
    _setStep(step, 'done');
    await new Promise(r => setTimeout(r, delay));
  }

  showToast(`✅ Capture OK — ${sym} | Verdict: ${result.verdict || '—'} | Conf: ${result.confidence}/10`, 'success');

  // Update preview panel
  _updateCapturePreview(result);

  // Reload history + stats
  await Promise.all([loadVisionHistory(), loadCaptureStats(), loadOverviewVision()]);

  _resetCaptureBtn();
  _captureRunning = false;
}

function _resetCaptureBtn() {
  const btn = document.getElementById('captureBtn');
  const btnText = document.getElementById('captureBtnText');
  const btnIcon = document.getElementById('captureBtnIcon');
  if (btn) btn.disabled = false;
  if (btnIcon) btnIcon.textContent = '📸';
  if (btnText) btnText.textContent = 'Capture + Analyze';
}

function _updateCapturePreview(result) {
  const verdictColor = (result.verdict || '').includes('STRONG') ? 'var(--buy)'
    : (result.verdict || '').includes('AVOID') ? 'var(--sell)' : 'var(--warn)';
  const conf = result.confidence || 0;
  const circumference = 113;
  const dashVal = Math.round((conf / 10) * circumference);

  // ── Website: keep real LightweightCharts chart visible (no screenshot overlay)
  // CDP screenshot is sent to Telegram by the server — show a small status badge instead
  if (result.screenshot_url) {
    const lbl = document.getElementById('csLiveLabel');
    if (lbl) {
      const sym = result.symbol || document.getElementById('captureSymbol')?.value || '—';
      lbl.innerHTML = `${sym} · Captured <span style="color:#26a69a;font-size:0.7rem;margin-left:6px">📷 → Telegram</span>`;
      setTimeout(() => {
        const s2 = document.getElementById('captureSymbol')?.value || sym;
        const tf = _csTfMap[document.getElementById('captureTimeframe')?.value || '60'] || '1h';
        if (lbl) lbl.textContent = `${s2} · ${tf.toUpperCase()} · Binance`;
      }, 4000);
    }
  }

  // ── Verdict card ──
  const card = document.getElementById('csVerdictCard');
  if (card) {
    card.style.display = 'block';
    const s = document.getElementById('csVerdictSym'); if (s) s.textContent = result.symbol || '—';
    const v = document.getElementById('csVerdictVal');
    if (v) { v.textContent = result.verdict || '—'; v.style.color = verdictColor; }
    const num = document.getElementById('csConfNum');
    if (num) { num.textContent = `${conf}/10`; }
    const circle = document.getElementById('csConfCircle');
    if (circle) circle.setAttribute('stroke-dasharray', `${dashVal} ${circumference}`);
    const confColor = conf >= 7 ? 'var(--buy)' : conf >= 5 ? 'var(--accent2)' : 'var(--sell)';
    if (circle) circle.style.stroke = confColor;
    if (num) num.style.color = confColor;

    // Patterns
    const pats = document.getElementById('csPatterns');
    if (pats) pats.innerHTML = (result.patterns || [])
      .map(p => `<span class="pine-chip" style="font-size:0.7rem;padding:2px 8px">${p}</span>`).join('');

    // Analysis text
    const txt = document.getElementById('csAnalysisText');
    if (txt) txt.textContent = result.ai_analysis || '—';
  }
}

// Legacy compat — keep for Overview quick action button
async function triggerVisionCapture() {
  switchTab('analysis');
  setTimeout(runStealthCapture, 200);
}


// ── Load Capture Stats ──
async function loadCaptureStats() {
  const data = await apiFetch('/api/vision/stats');
  if (!data) return;
  const el = id => document.getElementById(id);
  if (el('cstat-total'))   el('cstat-total').textContent   = data.total_captures ?? '—';
  if (el('cstat-stealth')) el('cstat-stealth').textContent = data.stealth_count ?? '—';
  if (el('cstat-conf'))    el('cstat-conf').textContent    = data.avg_confidence ? `${data.avg_confidence}/10` : '—';
  if (el('cstat-last'))    el('cstat-last').textContent    = data.last_capture ? (data.last_capture || '').slice(11, 16) : '—';
}

// ── Img Zoom ──
function openImgZoom(src) {
  const modal = document.getElementById('imgZoomModal');
  const img   = document.getElementById('imgZoomEl');
  if (!modal || !img) return;
  img.src = src;
  modal.style.display = 'flex';
}
function closeImgZoom() {
  const modal = document.getElementById('imgZoomModal');
  if (modal) modal.style.display = 'none';
}


// ═══ ANALYSIS TAB — USE /api/vision/history + /api/briefs ═══
async function loadBriefs() {
  const el = document.getElementById('briefContent');
  if (!el) return;
  el.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  await Promise.all([loadVisionHistory(), loadLatestBriefText()]);
}

async function loadLatestBriefText() {
  const el = document.getElementById('briefContent');
  if (!el) return;
  const data = await apiFetch('/api/briefs?limit=1');
  if (!data || !data.briefs || data.briefs.length === 0) {
    el.innerHTML = '<div class="empty-state"><div class="icon">🌅</div><h3>Chưa có brief</h3><p>Click "Morning Brief" để tạo</p></div>';
    return;
  }
  const b = data.briefs[0];
  el.innerHTML = `
    <div style="margin-bottom:12px"><span class="muted-label">Brief #${b.id} — ${b.created_at} — ${b.symbols_scanned} symbols</span></div>
    <div style="white-space:pre-wrap;line-height:1.7;font-size:0.85rem">${b.brief_text || b.ai_analysis || 'No content'}</div>
  `;
}

// Cache for history items (avoids JSON injection in onclick)
const _histCache = new Map();

async function loadVisionHistory() {
  const container = document.getElementById('visionHistory');
  if (!container) return;
  container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

  const filterVal = document.getElementById('captureFilter')?.value || 'all';
  const data = await apiFetch('/api/vision/history?limit=20');
  if (!data || !data.items || data.items.length === 0) {
    container.innerHTML = '<div class="empty-state" style="padding:24px 16px"><div class="icon">👁</div><h3>Chưa có phân tích</h3><p>Nhấn Capture + Analyze</p></div>';
    return;
  }

  let items = data.items;
  if (filterVal === 'stealth') items = items.filter(v => v.source === 'stealth');
  else if (filterVal === 'brief')  items = items.filter(v => v.source !== 'stealth');

  if (items.length === 0) {
    container.innerHTML = `<div class="empty-state" style="padding:24px 16px"><div class="icon">🔍</div><h3>Không có kết quả</h3><p>${filterVal}</p></div>`;
    return;
  }

  // Store in cache keyed by id
  _histCache.clear();
  items.forEach(v => _histCache.set(String(v.id), v));

  // Auto-load latest verdict into card (NOT the screenshot — chart stays live)
  if (items[0]) _loadVerdictCard(items[0]);

  container.innerHTML = items.map(v => {
    const isS = v.source === 'stealth';
    const srcBadge = isS
      ? '<span class="hist-badge badge-s">STEALTH</span>'
      : '<span class="hist-badge badge-b">BRIEF</span>';
    const conf = v.confidence || 0;
    const confColor = conf >= 7 ? '#00c454' : conf >= 5 ? '#00d4aa' : '#ff5c5c';
    const verdictColor = (v.verdict || '').includes('STRONG') ? '#00c454'
      : (v.verdict || '').includes('AVOID') ? '#ff5c5c' : '#f59e0b';
    const shortVerdict = (v.verdict || 'N/A').replace(/_/g,' ').substring(0, 22);
    const timeStr = (v.created_at || '').slice(5, 16);
    const sym = v.symbol || '—';
    const thumbUrl = v.has_screenshot && v.screenshot_url ? v.screenshot_url : null;

    return `<div class="cs-hist-card" data-id="${v.id}">
      <div class="cs-hist-thumb">${
        thumbUrl
          ? `<img src="${thumbUrl}" alt="${sym}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
             <span class="cs-hist-no-img" style="display:none">📷</span>`
          : '<span class="cs-hist-no-img">📷</span>'
      }</div>
      <div class="cs-hist-body">
        <div class="cs-hist-row1">
          <span class="cs-hist-sym">${sym}</span>
          ${srcBadge}
        </div>
        <div class="cs-hist-verdict" style="color:${verdictColor}">${shortVerdict}</div>
        <div class="cs-hist-row3">
          <span style="color:${confColor};font-size:0.72rem;font-family:monospace">👁 ${conf}/10</span>
          <span class="cs-hist-time">${timeStr}</span>
        </div>
      </div>
    </div>`;
  }).join('');

  // Bind click via event delegation (safe — no inline JSON)
  container.querySelectorAll('.cs-hist-card').forEach(card => {
    card.addEventListener('click', () => {
      const id = card.dataset.id;
      const item = _histCache.get(id);
      if (item) _loadInCanvas(item);
      container.querySelectorAll('.cs-hist-card').forEach(c => c.classList.remove('active'));
      card.classList.add('active');
    });
  });
}

function _loadInCanvas(v) {
  // Load verdict card from history item
  _loadVerdictCard(v);

  // Reload the live LightweightChart with this item's symbol/timeframe
  // so website always shows interactive chart, not a static screenshot
  if (v && v.symbol) {
    const symSel = document.getElementById('captureSymbol');
    if (symSel) {
      // Find option matching symbol, or set directly
      const opts = Array.from(symSel.options);
      const match = opts.find(o => o.value === v.symbol || v.symbol.startsWith(o.value));
      if (match) symSel.value = match.value;
    }
    // Reload chart with the history item's symbol
    loadCSLiveChart();
  }
}

/**
 * Update verdict card only — does NOT touch the live chart
 */
function _loadVerdictCard(v) {
  if (!v) return;
  const conf = v.confidence || 0;
  const circumference = 113;
  const dashVal = Math.round((conf / 10) * circumference);
  const verdictColor = (v.verdict || '').includes('STRONG') ? 'var(--buy)'
    : (v.verdict || '').includes('AVOID') ? 'var(--sell)' : 'var(--warn)';
  const confColor = conf >= 7 ? 'var(--buy)' : conf >= 5 ? 'var(--accent2)' : 'var(--sell)';

  const card = document.getElementById('csVerdictCard');
  if (card) {
    card.style.display = 'block';
    const s = document.getElementById('csVerdictSym'); if (s) s.textContent = v.symbol || '—';
    const vv = document.getElementById('csVerdictVal');
    if (vv) { vv.textContent = v.verdict || '—'; vv.style.color = verdictColor; }
    const num = document.getElementById('csConfNum'); if (num) { num.textContent = `${conf}/10`; num.style.color = confColor; }
    const circle = document.getElementById('csConfCircle');
    if (circle) { circle.setAttribute('stroke-dasharray', `${dashVal} ${circumference}`); circle.style.stroke = confColor; }
    const pats = document.getElementById('csPatterns');
    if (pats) pats.innerHTML = (v.patterns || [])
      .map(p => `<span class="pine-chip" style="font-size:0.7rem;padding:2px 8px">${p}</span>`).join('');
    const txt = document.getElementById('csAnalysisText');
    if (txt) txt.textContent = v.ai_analysis || '—';
  }

  // Screenshot thumbnail: show in History card only (small thumb) — never on main chart
  // To view full screenshot: click the thumbnail in History panel
  if (v.screenshot_url) {
    // Store for potential zoom on history card click (via openImgZoom)
    _lastScreenshotUrl = v.screenshot_url;
  }
}

let _lastScreenshotUrl = null;


async function submitRagQuery() {
  const q = document.getElementById('ragQuery')?.value.trim();
  if (!q) { showToast('Nhập câu hỏi!', 'error'); return; }
  const el = document.getElementById('ragResults');
  if (!el) return;
  el.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  const data = await apiFetch(`/api/rag/query?q=${encodeURIComponent(q)}&n=3`);
  if (!data || !data.chunks || data.chunks.length === 0) {
    el.innerHTML = '<p class="muted-label">Không tìm thấy kết quả hoặc RAG chưa enabled</p>';
    return;
  }
  el.innerHTML = data.chunks.map(c => `
    <div class="rag-chunk">
      <div class="rag-chunk-meta">
        <span class="rag-chunk-topic">${c.topic || c.chapter || '—'}</span>
        <span class="rag-chunk-score">Score: ${((c.relevance || 0) * 100).toFixed(0)}%</span>
      </div>
      <div style="font-size:0.82rem;line-height:1.6">${c.preview || c.content || ''}</div>
    </div>`).join('');
}

// ═══ SCANNER — USE /api/scan/trigger ═══
async function triggerScan() {
  const btn = document.getElementById('scanBtn');
  const status = document.getElementById('scanStatus');
  if (btn) btn.disabled = true;
  if (status) status.textContent = 'Scanning...';
  showToast('🔍 Đang scan watchlist qua MCP/TradingView...', 'info');

  const data = await apiFetch('/api/scan/trigger?timeframe=D', { method: 'POST' });
  if (btn) btn.disabled = false;
  if (!data || !data.results) {
    showToast('❌ Scan thất bại — MCP có thể chưa connected', 'error');
    if (status) status.textContent = 'Scan failed';
    return;
  }

  lastScanResults = data.results;
  if (status) status.textContent = `Scanned ${data.scanned} symbols at ${new Date().toLocaleTimeString('vi-VN')}`;

  // Populate symbol selects
  populateSymbolsFromScan(data.results);

  const tbody = document.getElementById('scanBody');
  if (!tbody) return;
  tbody.innerHTML = data.results.map(r => {
    const chg = r.change_pct || 0;
    const score = r.trend_template_score || 0;
    const err = r.error;
    if (err) return `<tr><td><strong>${r.symbol}</strong></td><td colspan="7" style="color:var(--sell)">${err}</td></tr>`;
    return `<tr>
      <td><strong>${r.symbol}</strong></td>
      <td style="font-family:var(--mono)">${r.price || '—'}</td>
      <td style="color:${chg >= 0 ? 'var(--buy)' : 'var(--sell)'};font-family:var(--mono)">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</td>
      <td><div style="display:flex;align-items:center;gap:8px"><span>${score}/8</span>
        <div class="score-bar-wrap"><div class="score-bar" style="width:${(score/8)*100}%"></div></div></div></td>
      <td><span class="badge badge-ok">${r.trend_template_stage || '—'}</span></td>
      <td>${r.vcp_detected ? '<span class="badge badge-buy">🔺 YES</span>' : '<span class="badge badge-fail">No</span>'}</td>
      <td style="font-family:var(--mono)">${r.volume_ratio}x</td>
      <td><button class="qbtn" style="padding:4px 10px;font-size:0.75rem" onclick="quickTradeFromScan('${r.symbol}','${r.price}')">⚡ Trade</button></td>
    </tr>`;
  }).join('');
  showToast(`✅ Scan xong ${data.scanned} symbols!`, 'success');
}

function quickTradeFromScan(symbol, price) {
  document.getElementById('orderSymbol').value = symbol;
  document.getElementById('orderPrice').value = price || '';
  openOrderModal();
}

// ═══ POPULATE SYMBOLS ═══
function populateSymbolsFromScan(results) {
  const symbols = results.map(r => r.symbol).filter(Boolean);
  ['indSymbolSelect', 'analysisSymbol'].forEach(id => {
    const sel = document.getElementById(id);
    if (!sel || symbols.length === 0) return;
    sel.innerHTML = symbols.map(s => `<option value="${s}">${s}</option>`).join('');
  });
}

async function populateSymbols() {
  const data = await apiFetch('/api/watchlist');
  if (!data || !data.symbols || data.symbols.length === 0) return;
  ['indSymbolSelect', 'analysisSymbol'].forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = data.symbols.map(s => `<option value="${s}">${s}</option>`).join('');
  });
}

async function syncWatchlist() {
  showToast('🔄 Syncing watchlist from TradingView...', 'info');
  const res = await apiFetch('/api/watchlist/sync', { method: 'PUT' });
  if (res) {
    populateSymbols();
    showToast('✅ Watchlist synced!', 'success');
  } else {
    showToast('❌ Sync failed — MCP may be offline', 'error');
  }
}

// Late init
document.addEventListener('DOMContentLoaded', () => {
  setTimeout(populateSymbols, 1500);
  setTimeout(loadNotifications, 2500);
  setTimeout(loadOverviewWidgets, 1000);
  setTimeout(loadCaptureStats, 3000);
});


// ═══ OVERVIEW WIDGETS ═══

async function loadOverviewWidgets() {
  await Promise.all([
    loadOverviewSignals(),
    loadOverviewVision(),
    loadOverviewHealth(),
    startTickerPolling(),
  ]);
}

// ── LIVE TICKER ──
const _tickerSyms = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'];
const _tickerPrev = {};
let _tickerInterval = null;

async function fetchTickerPrices() {
  try {
    const syms = _tickerSyms.map(s => `"${s}"`).join(',');
    const res = await fetch(`https://api.binance.com/api/v3/ticker/24hr?symbols=[${syms}]`);
    if (!res.ok) return;
    const data = await res.json();
    data.forEach(d => {
      const sym = d.symbol;
      const price = parseFloat(d.lastPrice);
      const chgPct = parseFloat(d.priceChangePercent);
      const prev = _tickerPrev[sym];

      const priceEl = document.getElementById(`tp-${sym}`);
      const chgEl   = document.getElementById(`tc-${sym}`);
      const card    = document.getElementById(`ticker-${sym}`);
      if (!priceEl || !card) return;

      // Flash animation on price change
      if (prev !== undefined) {
        card.classList.remove('flash-up', 'flash-down');
        void card.offsetWidth; // reflow
        if (price > prev) card.classList.add('flash-up');
        else if (price < prev) card.classList.add('flash-down');
        setTimeout(() => card.classList.remove('flash-up', 'flash-down'), 600);
      }
      _tickerPrev[sym] = price;

      const fmt = price > 1000 ? price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})
                               : price.toFixed(4);
      priceEl.textContent = '$' + fmt;

      const sign = chgPct >= 0 ? '+' : '';
      chgEl.textContent = `${sign}${chgPct.toFixed(2)}%`;
      chgEl.className = `ticker-chg ${chgPct >= 0 ? 'up' : 'down'}`;
    });

    // Also update header live price with BTC
    const btc = data.find(d => d.symbol === 'BTCUSDT');
    if (btc) {
      const lp = document.getElementById('livePrice');
      const lc = document.getElementById('liveChange');
      if (lp) lp.textContent = '$' + parseFloat(btc.lastPrice).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
      if (lc) {
        const chg = parseFloat(btc.priceChangePercent);
        lc.textContent = `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%`;
        lc.style.color = chg >= 0 ? 'var(--buy)' : 'var(--sell)';
      }
    }
  } catch (e) {
    // Binance unreachable — fallback silently
  }
}

function startTickerPolling() {
  fetchTickerPrices();
  if (_tickerInterval) clearInterval(_tickerInterval);
  _tickerInterval = setInterval(fetchTickerPrices, 15000);
}

// ── RECENT SIGNALS (Overview) ──
async function loadOverviewSignals() {
  const el = document.getElementById('overviewSignals');
  if (!el) return;
  const data = await apiFetch('/trades?limit=8');
  if (!data || !data.trades || data.trades.length === 0) {
    el.innerHTML = '<p class="muted-label" style="padding:12px">Chưa có tín hiệu nào</p>';
    return;
  }
  el.innerHTML = data.trades.map(t => {
    const side = (t.side || 'INFO').toUpperCase();
    const dotClass = side === 'BUY' ? 'buy' : side === 'SELL' ? 'sell' : 'info';
    const sym = t.symbol || '—';
    const msg = t.signal_action === 'alert'
      ? `Webhook alert @ ${t.executed_price || '—'}`
      : `${side} @ ${t.executed_price || '—'} | ${(t.status || '').toUpperCase()}`;
    const ts = (t.created_at || '').slice(11, 16);
    return `<div class="signal-row">
      <span class="signal-dot ${dotClass}"></span>
      <span class="signal-sym">${sym}</span>
      <span class="signal-msg">${msg}</span>
      <span class="signal-ts">${ts}</span>
    </div>`;
  }).join('');
}

// ── LAST VISION (Overview) ──
async function loadOverviewVision() {
  const el = document.getElementById('overviewVision');
  if (!el) return;
  const data = await apiFetch('/api/vision/history?limit=1');
  if (!data || !data.items || data.items.length === 0) {
    el.innerHTML = `<div class="empty-state" style="padding:24px">
      <div class="icon">👁</div><h3>No analysis yet</h3><p>Capture a chart to start</p>
    </div>`;
    return;
  }
  const v = data.items[0];
  const verdictClass = (v.verdict || '').includes('STRONG') ? 'verdict-buy'
    : (v.verdict || '').includes('AVOID') ? 'verdict-sell' : 'verdict-hold';
  const conf = v.confidence || 0;
  const confColor = conf >= 7 ? 'var(--buy)' : conf >= 5 ? 'var(--warn)' : 'var(--sell)';

  el.innerHTML = `<div class="vision-mini">
    ${v.has_screenshot
      ? `<img class="vision-mini-img" src="${v.screenshot_url}?t=${Date.now()}" alt="Chart"
             onerror="this.style.display='none'">`
      : ''}
    <div class="vision-mini-meta">
      <span class="vision-mini-sym">${v.symbol || '—'}</span>
      <span class="vision-mini-conf" style="color:${confColor}">Confidence: ${conf}/10</span>
      <span class="vision-mini-verdict ${verdictClass}">${v.verdict || '—'}</span>
      <span style="font-size:0.72rem;color:var(--text-muted)">${(v.created_at || '').slice(0,16)}</span>
    </div>
  </div>`;
}

// ── SYSTEM HEALTH (Overview) ──
async function loadOverviewHealth() {
  const setDot = (id, state) => {
    const el = document.getElementById(id);
    if (el) el.className = `health-dot ${state}`;
  };
  // Server always OK if we got here
  setDot('hd-server', 'ok');

  try {
    const status = await apiFetch('/api/system/status');
    if (status) {
      // Actual schema: mcp.connected, telegram_bot.enabled, rag.enabled, vbs.connected
      setDot('hd-mcp',      status.mcp?.connected  ? 'ok' : 'err');
      setDot('hd-telegram', status.telegram_bot?.enabled ? 'ok' : 'warn');
      setDot('hd-binance',  status.rag?.enabled ? 'ok' : 'warn');  // use RAG as 4th indicator
      setDot('hd-vbs',      status.vbs?.connected ? 'ok' : (status.vbs?.enabled ? 'err' : 'warn'));
    }
  } catch(e) {
    setDot('hd-mcp', 'err');
    setDot('hd-telegram', 'err');
    setDot('hd-binance', 'err');
    setDot('hd-vbs', 'err');
  }
}


// ── EQUITY RANGE ──
function setEquityRange(range, btn) {
  document.querySelectorAll('.eq-range-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  // TODO: filter equityChart data by range when trade history supports date filter
  // For now just show toast
  showToast(`Equity range: ${range}`, 'info');
}
