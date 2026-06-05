/**
 * dashboard-visualizer.js — ATR Risk Management Visualizer Controller
 * Sprint 7.6 Integration: Interactive SVG chart, Trailing Stop, and Cross-Tab bridges
 */

const VIS = {
  direction: 'short',
  entryPrice: 72704.49,
  atrValue: 95.9298,
  slMultiplier: 2.0,
  rrrRatio: 3.5,
  trailMultiplier: 3.0,
  showTrail: true,
  lastParsedMeta: null,
  recentSignals: null,
};

// Default multipliers from symbol_config.py
const SYMBOL_DEFAULTS = {
  BTCUSDT: { sl: 2.0, tp: 8.0, rrr: 4.0, trail: 3.0, atr: 95.0 },
  ETHUSDT: { sl: 2.5, tp: 10.0, rrr: 4.0, trail: 3.75, atr: 15.0 },
  SOLUSDT: { sl: 3.2, tp: 13.0, rrr: 4.0, trail: 4.8, atr: 0.8 },
  BNBUSDT: { sl: 2.5, tp: 10.0, rrr: 4.0, trail: 3.75, atr: 2.5 },
};

function getSymbolDefaults(symbol) {
  const sym = String(symbol || '').toUpperCase();
  if (sym.includes('BTC')) return SYMBOL_DEFAULTS.BTCUSDT;
  if (sym.includes('ETH')) return SYMBOL_DEFAULTS.ETHUSDT;
  if (sym.includes('SOL')) return SYMBOL_DEFAULTS.SOLUSDT;
  if (sym.includes('BNB')) return SYMBOL_DEFAULTS.BNBUSDT;
  return SYMBOL_DEFAULTS.BTCUSDT; // Default fallback
}

/**
 * Main entry point: called by switchTab('visualizer')
 */
function initVisualizerTab() {
  // Initialize lightweight chart
  initVisChart();

  // Sync state values to UI controls on tab open
  document.getElementById('visDirection').value = VIS.direction;
  document.getElementById('visEntryPriceInput').value = VIS.entryPrice.toFixed(2);

  const slider = document.getElementById('visEntryPrice');
  if (slider) {
    slider.min = (VIS.entryPrice * 0.9).toFixed(2);
    slider.max = (VIS.entryPrice * 1.1).toFixed(2);
    slider.value = VIS.entryPrice;
  }

  const display = document.getElementById('visValEntryPrice');
  if (display) display.textContent = '$' + VIS.entryPrice.toLocaleString(undefined, {minimumFractionDigits: 2});

  document.getElementById('visAtrValue').value = VIS.atrValue;
  document.getElementById('visSlMultiplier').value = VIS.slMultiplier;
  document.getElementById('visRrrRatio').value = VIS.rrrRatio;
  document.getElementById('visTrailMultiplier').value = VIS.trailMultiplier;
  document.getElementById('visShowTrail').checked = VIS.showTrail;

  // Fetch live candles
  loadVisChartData(VIS.currentSymbol || 'BTCUSDT');

  updateVisCalculation();

  // Load server recorded signals
  refreshVisSignals();
}

/**
 * Initialize Lightweight Chart for Visualizer
 */
function initVisChart() {
  const container = document.getElementById('visLiveChart');
  if (!container || VIS.chart) return;

  const h = Math.max(container.clientHeight || 480, 480);

  VIS.chart = LightweightCharts.createChart(container, {
    width: container.clientWidth || 600,
    height: h,
    layout: {
      background: { type: 'solid', color: '#0a0b10' },
      textColor: '#9ca3af',
      fontFamily: '"JetBrains Mono", monospace',
      fontSize: 10,
    },
    grid: {
      vertLines: { color: 'rgba(255, 255, 255, 0.03)', style: LightweightCharts.LineStyle.Dashed },
      horzLines: { color: 'rgba(255, 255, 255, 0.03)', style: LightweightCharts.LineStyle.Dashed },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: { color: 'rgba(255,255,255,0.15)', width: 1, style: LightweightCharts.LineStyle.Dashed },
      horzLine: { color: 'rgba(255,255,255,0.15)', width: 1, style: LightweightCharts.LineStyle.Dashed },
    },
    rightPriceScale: {
      borderColor: 'rgba(255, 255, 255, 0.08)',
      scaleMargins: { top: 0.12, bottom: 0.12 },
      entireTextOnly: true,
    },
    timeScale: {
      borderColor: 'rgba(255, 255, 255, 0.08)',
      timeVisible: true,
      secondsVisible: false,
    },
  });

  VIS.candleSeries = VIS.chart.addCandlestickSeries({
    upColor: '#00c896',
    downColor: '#ff4d6d',
    borderUpColor: '#00c896',
    borderDownColor: '#ff4d6d',
    wickUpColor: '#00c896',
    wickDownColor: '#ff4d6d',
    priceLineVisible: false,
  });

  // Subscribe to time scale / zoom actions to redraw canvas
  VIS.chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    drawOverlayCanvas();
  });
  VIS.chart.timeScale().subscribeVisibleTimeRangeChange(() => {
    drawOverlayCanvas();
  });

  // Handle window resizing
  const resizeObserver = new ResizeObserver(entries => {
    if (entries.length === 0 || !entries[0]) return;
    const { width, height } = entries[0].contentRect;
    if (VIS.chart) {
      VIS.chart.resize(width, height || 480);
      setTimeout(drawOverlayCanvas, 20); // trigger redraw
    }
  });
  resizeObserver.observe(container);
}

/**
 * Fetch and load live candles from Binance
 */
async function loadVisChartData(symbol) {
  let sym = String(symbol || 'BTCUSDT').toUpperCase().replace('USD', 'USDT');
  if (sym.includes('BTC')) sym = 'BTCUSDT';
  else if (sym.includes('ETH')) sym = 'ETHUSDT';
  else if (sym.includes('SOL')) sym = 'SOLUSDT';
  else if (sym.includes('BNB')) sym = 'BNBUSDT';

  if (VIS.currentSymbol === sym && VIS.candleSeries && VIS.candleSeries.data && VIS.candleSeries.data.length > 0) return;

  VIS.currentSymbol = sym;
  const badge = document.getElementById('visSymbolBadge');
  if (badge) badge.textContent = sym;

  try {
    const res = await fetch(`https://api.binance.com/api/v3/klines?symbol=${sym}&interval=1h&limit=100`);
    if (!res.ok) throw new Error('Binance fetch failed');
    const raw = await res.json();
    if (!raw || !raw.length) throw new Error('No data');

    const ohlcv = raw.map(c => ({
      time: Math.floor(c[0] / 1000),
      open: parseFloat(c[1]),
      high: parseFloat(c[2]),
      low: parseFloat(c[3]),
      close: parseFloat(c[4]),
    }));

    if (VIS.candleSeries) {
      VIS.candleSeries.setData(ohlcv);
      VIS.chart.timeScale().fitContent();
      setTimeout(drawOverlayCanvas, 50); // Redraw canvas once candles are loaded
    }
  } catch (e) {
    console.warn('[Visualizer] Live candles fetch failed:', e);
  }
}

/**
 * Sync numeric input to entry price slider
 */
window.syncEntryInputToSlider = function() {
  const input = document.getElementById('visEntryPriceInput');
  const slider = document.getElementById('visEntryPrice');
  if (!input || !slider) return;

  const val = parseFloat(input.value) || 0;
  slider.min = (val * 0.9).toFixed(2);
  slider.max = (val * 1.1).toFixed(2);
  slider.value = val;

  const display = document.getElementById('visValEntryPrice');
  if (display) display.textContent = '$' + val.toLocaleString(undefined, {minimumFractionDigits: 2});

  updateVisCalculation();
};

/**
 * Sync entry price slider to numeric input
 */
window.syncEntrySliderToInput = function() {
  const input = document.getElementById('visEntryPriceInput');
  const slider = document.getElementById('visEntryPrice');
  if (!input || !slider) return;

  const val = parseFloat(slider.value) || 0;
  input.value = val.toFixed(2);

  const display = document.getElementById('visValEntryPrice');
  if (display) display.textContent = '$' + val.toLocaleString(undefined, {minimumFractionDigits: 2});

  updateVisCalculation();
};

/**
 * Main calculation and chart updating engine
 */
function updateVisCalculation() {
  // Read DOM values
  VIS.direction = document.getElementById('visDirection').value;
  VIS.entryPrice = parseFloat(document.getElementById('visEntryPriceInput').value) || 0;
  VIS.atrValue = parseFloat(document.getElementById('visAtrValue').value) || 0;
  VIS.slMultiplier = parseFloat(document.getElementById('visSlMultiplier').value) || 2.0;
  VIS.rrrRatio = parseFloat(document.getElementById('visRrrRatio').value) || 3.5;
  VIS.trailMultiplier = parseFloat(document.getElementById('visTrailMultiplier').value) || 3.0;
  VIS.showTrail = document.getElementById('visShowTrail').checked;

  // Update slider texts
  setText('visValAtr', VIS.atrValue.toFixed(2));
  setText('visValSlMul', VIS.slMultiplier.toFixed(1) + 'x');
  setText('visValRrr', VIS.rrrRatio.toFixed(1) + ':1');
  setText('visValTrailMul', VIS.trailMultiplier.toFixed(1) + 'x');

  // Math equations
  const risk = VIS.atrValue * VIS.slMultiplier;
  const reward = risk * VIS.rrrRatio;
  const trail = VIS.atrValue * VIS.trailMultiplier;

  let slPrice, tpPrice, trailPrice;
  if (VIS.direction === 'short') {
    slPrice = VIS.entryPrice + risk;
    tpPrice = VIS.entryPrice - reward;
    trailPrice = VIS.entryPrice + trail;
  } else {
    slPrice = VIS.entryPrice - risk;
    tpPrice = VIS.entryPrice + reward;
    trailPrice = VIS.entryPrice - trail;
  }

  const slPct = (risk / VIS.entryPrice) * 100;
  const tpPct = (reward / VIS.entryPrice) * 100;
  const trailPct = (trail / VIS.entryPrice) * 100;

  // Update Metrics Panel
  setText('visPAtr', '$' + VIS.atrValue.toFixed(2));
  setText('visPRiskDist', '$' + risk.toFixed(2));
  setText('visPRewardDist', '$' + reward.toFixed(2));
  setText('visPSlPct', slPct.toFixed(2) + '%');
  setText('visPRrr', VIS.rrrRatio.toFixed(1));

  // Trailing stop metrics
  const trailPill = document.getElementById('visPTrailPill');
  const trailPctPill = document.getElementById('visPTrailPctPill');
  if (VIS.showTrail) {
    if (trailPill) trailPill.style.display = 'flex';
    if (trailPctPill) trailPctPill.style.display = 'flex';
    setText('visPTrailDist', '$' + trail.toFixed(2));
    setText('visPTrailPct', trailPct.toFixed(2) + '%');
  } else {
    if (trailPill) trailPill.style.display = 'none';
    if (trailPctPill) trailPctPill.style.display = 'none';
  }

  // Draw safety caps warnings
  const hardCap = VIS.entryPrice > 50000 ? 8.0 : (VIS.entryPrice > 1000 ? 10.0 : 13.0);
  const isClamped = slPct > hardCap;
  const pSlPctEl = document.getElementById('visPSlPct');
  if (pSlPctEl) {
    if (isClamped) {
      pSlPctEl.style.color = '#f59e0b';
      pSlPctEl.title = `SL exceeds ${hardCap}% cap and will be CLAMPED by Trade Engine!`;
    } else {
      pSlPctEl.style.color = 'var(--accent-red)';
      pSlPctEl.title = '';
    }
  }

  // Update formulas text
  setText('visFAtr', VIS.atrValue.toFixed(4));
  setText('visFMul', VIS.slMultiplier.toFixed(1));
  setText('visFRisk', risk.toFixed(4));
  setText('visFRisk2', risk.toFixed(4));
  setText('visFRrr', VIS.rrrRatio.toFixed(1));
  setText('visFReward', reward.toFixed(4));

  // Math Step-by-step
  const slFormulaEl = document.getElementById('visFSlFormula');
  const slDescEl = document.getElementById('visFSlDesc');
  const tpFormulaEl = document.getElementById('visFTpFormula');
  const tpDescEl = document.getElementById('visFTpDesc');

  if (VIS.direction === 'short') {
    if (slFormulaEl) slFormulaEl.innerHTML = `Stop Loss = Price + Risk = ${VIS.entryPrice.toFixed(2)} + ${risk.toFixed(2)} = <span class="val-sl">${slPrice.toFixed(2)}</span>`;
    if (slDescEl) slDescEl.textContent = 'Với vị thế SHORT, Stop Loss được đặt CAO hơn Giá vào lệnh để bảo vệ nguồn vốn.';
    if (tpFormulaEl) tpFormulaEl.innerHTML = `Take Profit = Price - Reward = ${VIS.entryPrice.toFixed(2)} - ${reward.toFixed(2)} = <span class="val-tp">${tpPrice.toFixed(2)}</span>`;
    if (tpDescEl) tpDescEl.textContent = 'Với vị thế SHORT, Take Profit được đặt DƯỚI Giá vào lệnh.';

    setText('visStateBadge', 'Short Setup');
    document.getElementById('visStateBadge').className = 'state-badge short';
  } else {
    if (slFormulaEl) slFormulaEl.innerHTML = `Stop Loss = Price - Risk = ${VIS.entryPrice.toFixed(2)} - ${risk.toFixed(2)} = <span class="val-sl">${slPrice.toFixed(2)}</span>`;
    if (slDescEl) slDescEl.textContent = 'Với vị thế LONG, Stop Loss được đặt THẤP hơn Giá vào lệnh để giới hạn thua lỗ.';
    if (tpFormulaEl) tpFormulaEl.innerHTML = `Take Profit = Price + Reward = ${VIS.entryPrice.toFixed(2)} + ${reward.toFixed(2)} = <span class="val-tp">${tpPrice.toFixed(2)}</span>`;
    if (tpDescEl) tpDescEl.textContent = 'Với vị thế LONG, Take Profit được đặt TRÊN Giá vào lệnh.';

    setText('visStateBadge', 'Long Setup');
    document.getElementById('visStateBadge').className = 'state-badge long';
  }

  // Trailing stop formulas
  const trailFormulaEl = document.getElementById('visFTrailFormula');
  if (trailFormulaEl) {
    if (VIS.showTrail) {
      trailFormulaEl.parentElement.style.display = 'flex';
      if (VIS.direction === 'short') {
        trailFormulaEl.innerHTML = `Chandelier Trail Stop = Price + (ATR &times; trail_mul) = ${VIS.entryPrice.toFixed(2)} + (${VIS.atrValue.toFixed(2)} &times; ${VIS.trailMultiplier.toFixed(1)}) = <span style="color: var(--accent-orange); font-weight: 600;">${trailPrice.toFixed(2)}</span>`;
      } else {
        trailFormulaEl.innerHTML = `Chandelier Trail Stop = Price - (ATR &times; trail_mul) = ${VIS.entryPrice.toFixed(2)} - (${VIS.atrValue.toFixed(2)} &times; ${VIS.trailMultiplier.toFixed(1)}) = <span style="color: var(--accent-orange); font-weight: 600;">${trailPrice.toFixed(2)}</span>`;
      }
    } else {
      trailFormulaEl.parentElement.style.display = 'none';
    }
  }

  // Update transparent helper lines to scale chart
  renderVisChartLines(slPrice, tpPrice, trailPrice);

  // Redraw Canvas Overlay
  setTimeout(drawOverlayCanvas, 10);
}

/**
 * Update horizontal helper price lines on the live chart (set to transparent so they only scale chart)
 */
function renderVisChartLines(sl, tp, trail) {
  if (!VIS.candleSeries) return;

  // Clear existing lines
  if (VIS.entryLine) {
    try { VIS.candleSeries.removePriceLine(VIS.entryLine); } catch (e) {}
    VIS.entryLine = null;
  }
  if (VIS.slLine) {
    try { VIS.candleSeries.removePriceLine(VIS.slLine); } catch (e) {}
    VIS.slLine = null;
  }
  if (VIS.tpLine) {
    try { VIS.candleSeries.removePriceLine(VIS.tpLine); } catch (e) {}
    VIS.tpLine = null;
  }
  if (VIS.trailLine) {
    try { VIS.candleSeries.removePriceLine(VIS.trailLine); } catch (e) {}
    VIS.trailLine = null;
  }

  // Create transparent lines so chart scaling is handled by Lightweight Charts automatically
  VIS.entryLine = VIS.candleSeries.createPriceLine({
    price: VIS.entryPrice,
    color: 'transparent',
    lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Solid,
    axisLabelVisible: false,
    title: '',
  });

  VIS.slLine = VIS.candleSeries.createPriceLine({
    price: sl,
    color: 'transparent',
    lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Solid,
    axisLabelVisible: false,
    title: '',
  });

  VIS.tpLine = VIS.candleSeries.createPriceLine({
    price: tp,
    color: 'transparent',
    lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Solid,
    axisLabelVisible: false,
    title: '',
  });

  if (VIS.showTrail) {
    VIS.trailLine = VIS.candleSeries.createPriceLine({
      price: trail,
      color: 'transparent',
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Solid,
      axisLabelVisible: false,
      title: '',
    });
  }
}

/**
 * HTML5 Canvas Premium overlay painter
 */
function drawOverlayCanvas() {
  const canvas = document.getElementById('visOverlayCanvas');
  if (!canvas || !VIS.chart || !VIS.candleSeries) return;

  const container = document.getElementById('visLiveChart');
  if (!container) return;

  const w = container.clientWidth;
  const h = container.clientHeight || 480;

  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }

  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, w, h);

  const timeScaleWidth = VIS.chart.timeScale().width();
  if (!timeScaleWidth) return;

  const entryY = VIS.candleSeries.priceToCoordinate(VIS.entryPrice);

  const risk = VIS.atrValue * VIS.slMultiplier;
  const reward = risk * VIS.rrrRatio;
  const trail = VIS.atrValue * VIS.trailMultiplier;

  let slPrice, tpPrice, trailPrice;
  if (VIS.direction === 'short') {
    slPrice = VIS.entryPrice + risk;
    tpPrice = VIS.entryPrice - reward;
    trailPrice = VIS.entryPrice + trail;
  } else {
    slPrice = VIS.entryPrice - risk;
    tpPrice = VIS.entryPrice + reward;
    trailPrice = VIS.entryPrice - trail;
  }

  const slY = VIS.candleSeries.priceToCoordinate(slPrice);
  const tpY = VIS.candleSeries.priceToCoordinate(tpPrice);
  const trailY = VIS.candleSeries.priceToCoordinate(trailPrice);

  if (entryY === null || slY === null || tpY === null) return;

  // ── 1. Draw Target Zones ──
  // Green shaded area for TP
  ctx.fillStyle = 'rgba(0, 200, 150, 0.08)';
  const tpTop = Math.min(entryY, tpY);
  const tpBottom = Math.max(entryY, tpY);
  ctx.fillRect(0, tpTop, timeScaleWidth, tpBottom - tpTop);

  // Red shaded area for SL
  ctx.fillStyle = 'rgba(255, 77, 109, 0.08)';
  const slTop = Math.min(entryY, slY);
  const slBottom = Math.max(entryY, slY);
  ctx.fillRect(0, slTop, timeScaleWidth, slBottom - slTop);

  // ── 2. Draw Horizontal Lines with Glow ──
  function drawGlowLine(y, strokeStyle, shadowColor, isDashed = false) {
    ctx.save();
    if (isDashed) {
      ctx.setLineDash([6, 5]);
    }
    ctx.shadowColor = shadowColor;
    ctx.shadowBlur = 6;
    ctx.strokeStyle = strokeStyle;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(timeScaleWidth, y);
    ctx.stroke();
    ctx.restore();
  }

  // Draw Entry Line (Solid White)
  drawGlowLine(entryY, 'rgba(255, 255, 255, 0.8)', 'rgba(255, 255, 255, 0.3)');

  // Draw TP Line (Solid Green)
  drawGlowLine(tpY, '#00c896', 'rgba(0, 200, 150, 0.4)');

  // Draw SL Line (Solid Red)
  drawGlowLine(slY, '#ff4d6d', 'rgba(255, 77, 109, 0.4)');

  // Draw Trail Line (Dashed Orange)
  if (VIS.showTrail && trailY !== null) {
    drawGlowLine(trailY, '#fb923c', 'rgba(251, 146, 60, 0.3)', true);
  }

  // ── 3. Draw Badges ──
  const badgeX = timeScaleWidth - 190;

  function drawRoundedBadge(text, valText, x, y, bgCol, textCol, percentageText = '') {
    ctx.save();
    ctx.font = 'bold 9px "JetBrains Mono", monospace';
    const tWidth = ctx.measureText(text).width;
    ctx.font = 'normal 9px "JetBrains Mono", monospace';
    const vWidth = ctx.measureText(valText).width;
    const pWidth = percentageText ? ctx.measureText(percentageText).width + 8 : 0;

    const badgeW = tWidth + vWidth + pWidth + 20;
    const badgeH = 18;
    const badgeY = y - badgeH / 2;

    ctx.shadowColor = 'rgba(0, 0, 0, 0.5)';
    ctx.shadowBlur = 4;
    ctx.shadowOffsetY = 1;

    ctx.fillStyle = bgCol;
    ctx.beginPath();
    if (typeof ctx.roundRect === 'function') {
      ctx.roundRect(x, badgeY, badgeW, badgeH, 4);
    } else {
      ctx.rect(x, badgeY, badgeW, badgeH); // fallback
    }
    ctx.fill();
    ctx.restore();

    ctx.fillStyle = textCol;
    ctx.font = 'bold 9px "JetBrains Mono", monospace';
    ctx.fillText(text, x + 6, y + 3);

    ctx.font = 'normal 9px "JetBrains Mono", monospace';
    ctx.fillText(valText, x + 12 + tWidth, y + 3);

    if (percentageText) {
      ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
      ctx.fillText(percentageText, x + 16 + tWidth + vWidth, y + 3);
    }
  }

  const slPct = (risk / VIS.entryPrice) * 100;
  const tpPct = (reward / VIS.entryPrice) * 100;
  const trailPct = (trail / VIS.entryPrice) * 100;

  // Draw Entry Badge (White)
  drawRoundedBadge('ENTRY', VIS.entryPrice.toLocaleString(undefined, {minimumFractionDigits: 2}), badgeX + 40, entryY, '#ffffff', '#000000');

  // Draw TP Badge (Green)
  drawRoundedBadge('TAKE PROFIT', `+$${reward.toLocaleString(undefined, {minimumFractionDigits: 2})}`, badgeX - 10, tpY, '#00c896', '#ffffff', `+${tpPct.toFixed(2)}%`);

  // Draw SL Badge (Red)
  drawRoundedBadge('STOP LOSS', `-$${risk.toLocaleString(undefined, {minimumFractionDigits: 2})}`, badgeX + 10, slY, '#ff4d6d', '#ffffff', `-${slPct.toFixed(2)}%`);

  // Draw TS Badge (Orange)
  if (VIS.showTrail && trailY !== null) {
    drawRoundedBadge('TRAILING STOP', `-$${trail.toLocaleString(undefined, {minimumFractionDigits: 2})}`, badgeX - 20, trailY, '#fb923c', '#ffffff', `${trailPct.toFixed(2)}%`);
  }
}

/**
 * Presets engine loader
 */
function loadVisPreset(name) {
  let direction = 'short';
  let price = 72704.49;
  let atr = 95.9298;
  let slMul = 2.0;
  let rrr = 3.5;
  let trailMul = 3.0;
  let symName = 'BTCUSDT';

  if (name === 'vbs_short_btc') {
    direction = 'short';
    price = 72704.49;
    atr = 95.9298;
    slMul = 2.0;
    rrr = 3.5;
    trailMul = 3.0;
    symName = 'BTCUSDT';
  } else if (name === 'vbs_long_btc') {
    direction = 'long';
    price = 72704.49;
    atr = 95.9298;
    slMul = 2.0;
    rrr = 3.5;
    trailMul = 3.0;
    symName = 'BTCUSDT';
  } else if (name === 'vbs_long_eth') {
    direction = 'long';
    price = 3450.00;
    atr = 15.00;
    slMul = 2.5;
    rrr = 4.0;
    trailMul = 3.75;
    symName = 'ETHUSDT';
  } else if (name === 'vbs_short_sol') {
    direction = 'short';
    price = 165.20;
    atr = 0.85;
    slMul = 3.2;
    rrr = 4.0;
    trailMul = 4.8;
    symName = 'SOLUSDT';
  }

  // Update UI values
  document.getElementById('visDirection').value = direction;
  document.getElementById('visEntryPriceInput').value = price.toFixed(2);

  const slider = document.getElementById('visEntryPrice');
  if (slider) {
    slider.min = (price * 0.9).toFixed(2);
    slider.max = (price * 1.1).toFixed(2);
    slider.value = price;
  }

  const display = document.getElementById('visValEntryPrice');
  if (display) display.textContent = '$' + price.toLocaleString(undefined, {minimumFractionDigits: 2});

  document.getElementById('visAtrValue').value = atr;
  document.getElementById('visSlMultiplier').value = slMul;
  document.getElementById('visRrrRatio').value = rrr;
  document.getElementById('visTrailMultiplier').value = trailMul;

  // Highlight active chip
  document.querySelectorAll('.preset-chip').forEach(chip => {
    chip.classList.toggle('active', chip.getAttribute('onclick').includes(name));
  });

  // Synthesize metadata alert payload in textarea
  const mockMeta = {
    symbol: symName,
    direction,
    atr_value: atr.toString(),
    sl: "0",
    tp: "0",
    rrr_ratio: rrr.toString(),
    sl_mode: "ATR",
    tp_mode: "Fixed RRR",
    trail_stop: "0"
  };
  document.getElementById('visRawMetadata').value = JSON.stringify(mockMeta, null, 2);

  // Load new symbol candles
  loadVisChartData(symName);

  updateVisCalculation();
}

/**
 * Paste string parser (supports JSON and Python dict nháy đơn)
 */
function parseVisMetadata() {
  const text = document.getElementById('visRawMetadata').value.trim();
  if (!text) return;

  try {
    const cleanText = text
      .replace(/'/g, '"')
      .replace(/True/g, 'true')
      .replace(/False/g, 'false')
      .replace(/None/g, 'null');

    const parsed = JSON.parse(cleanText);
    let sym = parsed.symbol || 'BTCUSDT';

    if (parsed.direction) {
      document.getElementById('visDirection').value = parsed.direction.toLowerCase();
    }
    if (parsed.atr_value) {
      document.getElementById('visAtrValue').value = parseFloat(parsed.atr_value);
    }
    if (parsed.rrr_ratio) {
      document.getElementById('visRrrRatio').value = parseFloat(parsed.rrr_ratio);
    }

    // Automatically query symbol scale based on current selected symbol
    let price = parseFloat(parsed.entry || parsed.price) || 0;
    if (!price) {
      const activePriceEl = document.getElementById(`tp-${sym.toUpperCase()}`);
      price = activePriceEl ? parseFloat(activePriceEl.textContent.replace('$', '').replace(/,/g, '')) : 72704.49;
    }

    document.getElementById('visEntryPriceInput').value = price.toFixed(2);

    const slider = document.getElementById('visEntryPrice');
    if (slider) {
      slider.min = (price * 0.9).toFixed(2);
      slider.max = (price * 1.1).toFixed(2);
      slider.value = price;
    }

    const display = document.getElementById('visValEntryPrice');
    if (display) display.textContent = '$' + price.toLocaleString(undefined, {minimumFractionDigits: 2});

    const defaults = getSymbolDefaults(sym);
    document.getElementById('visSlMultiplier').value = defaults.sl;
    document.getElementById('visTrailMultiplier').value = defaults.trail;

    loadVisChartData(sym);

    updateVisCalculation();
    showToast("✅ Đã phân tích metadata chỉ báo!", "success");
  } catch (e) {
    showToast("❌ Định dạng metadata không hợp lệ", "error");
  }
}

/**
 * Live Server Recorded Signals Feed Loader
 */
window.refreshVisSignals = async function(event) {
  if (event) event.stopPropagation();
  const container = document.getElementById('visRecentSignals');
  if (!container) return;

  container.innerHTML = '<div style="font-size: 0.72rem; color: var(--text-muted); text-align: center; padding: 12px;"><div class="spinner" style="width:12px;height:12px;display:inline-block;margin-right:6px;"></div>Loading signals...</div>';

  try {
    const res = await apiFetch('/api/indicator-signals?limit=6');
    if (!res || !res.signals || !res.signals.length) {
      container.innerHTML = '<div style="font-size: 0.72rem; color: var(--text-muted); text-align: center; padding: 12px;">No signals found on server</div>';
      return;
    }

    VIS.recentSignals = res.signals; // Cache locally

    let html = '';
    res.signals.forEach(sig => {
      const isEntry = sig.signal_type === 'entry';
      const isExit = sig.signal_type === 'exit';
      const badgeColor = isEntry ? 'rgba(0, 200, 150, 0.15)' : isExit ? 'rgba(255, 77, 109, 0.15)' : 'rgba(59, 130, 246, 0.15)';
      const textColor = isEntry ? '#00c896' : isExit ? '#ff4d6d' : '#3b82f6';

      const timeStr = new Date(sig.created_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });

      // Parse metadata details
      let metaStr = '';
      const meta = typeof sig.metadata === 'object' ? sig.metadata : {};
      metaStr = `ATR: ${parseFloat(meta.atr_value || 0).toFixed(2)}, Dir: ${meta.direction || 'N/A'}, RRR: ${meta.rrr_ratio || 'N/A'}`;

      html += `
        <div class="vis-sig-item" onclick="loadVisSignalById(${sig.id})" title="${sig.indicator_name} | ${metaStr}">
          <div style="display: flex; align-items: center; gap: 6px;">
            <span style="display:inline-block; padding: 1px 4px; border-radius: 3px; background: ${badgeColor}; color: ${textColor}; font-weight: bold; font-size: 0.65rem;">
              ${sig.signal_type.toUpperCase()}
            </span>
            <span style="font-weight: 600; color: #ffffff;">${sig.symbol}</span>
            <span style="color: var(--text-muted); font-size: 0.68rem;">@$${(sig.price || 0).toLocaleString(undefined, {minimumFractionDigits: 1})}</span>
          </div>
          <div style="display: flex; align-items: center; gap: 6px; color: var(--text-muted); font-size: 0.68rem;">
            <span>${sig.indicator_name}</span>
            <span>${timeStr}</span>
          </div>
        </div>
      `;
    });
    container.innerHTML = html;
  } catch (e) {
    console.error('Failed to load visualizer signals:', e);
    container.innerHTML = '<div style="font-size: 0.72rem; color: var(--text-muted); text-align: center; padding: 12px; color: var(--accent-red);">Failed to load signals</div>';
  }
};

/**
 * Load selected recorded signal parameters into the visualizer
 */
window.loadVisSignalById = function(id) {
  if (!VIS.recentSignals) return;
  const sig = VIS.recentSignals.find(s => s.id === id);
  if (!sig) return;

  const metadata = typeof sig.metadata === 'object' ? sig.metadata : {};
  const defaults = getSymbolDefaults(sig.symbol);

  window.openInVisualizer({
    symbol: sig.symbol,
    direction: metadata.direction || (sig.signal_type === 'exit' ? 'short' : 'long'),
    entryPrice: sig.price || (defaults.atr > 50 ? 72000 : 3400),
    atrValue: parseFloat(metadata.atr_value || defaults.atr),
    slMultiplier: defaults.sl,
    rrrRatio: parseFloat(metadata.rrr_ratio || defaults.rrr),
    trailMultiplier: defaults.trail,
    showTrail: true,
    slPrice: parseFloat(metadata.sl || 0),
    tpPrice: parseFloat(metadata.tp || 0)
  });

  // Load symbol candlesticks
  loadVisChartData(sig.symbol);

  // Pre-fill RAW textarea with actual recorded signal JSON
  const textarea = document.getElementById('visRawMetadata');
  if (textarea) textarea.value = JSON.stringify(sig, null, 2);

  showToast(`✅ Loaded recorded signal for ${sig.symbol}!`, 'success');
};

/**
 * Helper to update text contents
 */
function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}


// ═══════════════════════════════════════════════════════════════
// 🌐 CROSS-TAB INTERACTION CONTROLLERS
// ═══════════════════════════════════════════════════════════════

/**
 * Interface 1: Load a specific custom trade configuration from outside
 */
window.openInVisualizer = function(data) {
  if (!data) return;

  if (data.symbol) VIS.currentSymbol = data.symbol;
  if (data.direction) VIS.direction = data.direction.toLowerCase();
  if (data.entryPrice) VIS.entryPrice = parseFloat(data.entryPrice);
  if (data.atrValue) VIS.atrValue = parseFloat(data.atrValue);
  if (data.slMultiplier) VIS.slMultiplier = parseFloat(data.slMultiplier);
  if (data.rrrRatio) VIS.rrrRatio = parseFloat(data.rrrRatio);
  if (data.trailMultiplier) VIS.trailMultiplier = parseFloat(data.trailMultiplier);
  if (data.showTrail !== undefined) VIS.showTrail = !!data.showTrail;

  // If explicit SL/TP prices are provided (overriding RRR), calculate RRR back
  if (data.slPrice && data.entryPrice && data.slPrice > 0) {
    const slRisk = Math.abs(data.entryPrice - data.slPrice);
    if (slRisk > 0 && VIS.atrValue > 0) {
      VIS.slMultiplier = slRisk / VIS.atrValue;
      if (data.tpPrice && data.tpPrice > 0) {
        const tpReward = Math.abs(data.entryPrice - data.tpPrice);
        VIS.rrrRatio = tpReward / slRisk;
      }
    }
  }

  // Pre-fill RAW textarea with data representation
  const payload = {
    symbol: VIS.currentSymbol || "BTCUSDT",
    direction: VIS.direction,
    atr_value: VIS.atrValue.toString(),
    sl: data.slPrice ? data.slPrice.toString() : "0",
    tp: data.tpPrice ? data.tpPrice.toString() : "0",
    rrr_ratio: VIS.rrrRatio.toFixed(1),
    sl_mode: "ATR",
    tp_mode: "Fixed RRR",
    trail_stop: "0"
  };

  const textarea = document.getElementById('visRawMetadata');
  if (textarea) textarea.value = JSON.stringify(payload, null, 2);

  // Switch to tab
  switchTab('visualizer');
};

/**
 * Interface 2: Visualize a capture entry from AI Vision Capture Studio
 */
window.visualizeCSCapture = function(event) {
  if (event) event.stopPropagation();

  const sym = document.getElementById('csVerdictSym')?.textContent;
  const analysis = document.getElementById('csAnalysisText')?.textContent || '';

  // Extract price from live ticker
  let entry = 72704.49;
  const symDefaults = getSymbolDefaults(sym);
  if (sym) {
    const tickEl = document.getElementById(`tp-${sym.toUpperCase()}`);
    if (tickEl) {
      const txt = tickEl.textContent.replace('$', '').replace(/,/g, '');
      entry = parseFloat(txt) || entry;
    } else {
      entry = symDefaults.atr > 50 ? 72000 : (symDefaults.atr > 5 ? 3400 : 160);
    }
  }

  // Search analysis text for metadata pattern
  let metadata = null;
  try {
    const match = analysis.match(/metadata:\s*(\{.*?\})/is) || analysis.match(/\{'direction':.*?\}/is);
    if (match && match[0]) {
      const clean = match[0].replace(/metadata:\s*/i, '')
                            .replace(/'/g, '"')
                            .replace(/True/g, 'true')
                            .replace(/False/g, 'false');
      metadata = JSON.parse(clean);
    }
  } catch (e) {}

  if (!metadata) {
    // Default fallback based on symbol characteristics
    metadata = {
      direction: analysis.toLowerCase().includes('short') ? 'short' : 'long',
      atr_value: symDefaults.atr.toString(),
      rrr_ratio: symDefaults.rrr.toString()
    };
  }

  window.openInVisualizer({
    symbol: sym,
    direction: metadata.direction,
    entryPrice: entry,
    atrValue: parseFloat(metadata.atr_value || symDefaults.atr),
    slMultiplier: symDefaults.sl,
    rrrRatio: parseFloat(metadata.rrr_ratio || symDefaults.rrr),
    trailMultiplier: symDefaults.trail,
    showTrail: true
  });
};

/**
 * Interface 3: Visualize historical signal card from Signals tab
 */
window.visualizeSignalCard = function(signalId, event) {
  if (event) event.stopPropagation();

  // Fetch target signal from parent signals feed array (res.signals in dashboard-signals.js)
  const card = document.getElementById(`sig-hist-${signalId}`) || document.querySelector(`#sig-group-${signalId}`);
  if (!card) return;

  // Extract values
  let sym = 'BTCUSDT';
  let price = 72000;
  let dir = 'long';
  let atr = 95.93;

  try {
    const symEl = card.querySelector('.sig-hist-symbol') || card.querySelector('.sig-symbol');
    if (symEl) sym = symEl.textContent.trim();

    const prEl = card.querySelector('.sig-hist-price') || card.querySelector('.sig-price');
    if (prEl) price = parseFloat(prEl.textContent.replace('$', '').replace(/,/g, '')) || price;

    const typeEl = card.querySelector('.sig-type-label') || card.querySelector('.sig-type-badge');
    if (typeEl) {
      const typeText = typeEl.textContent.toLowerCase();
      // Look at metadata direction
      const metaTag = card.querySelector('.sig-meta-tag');
      if (metaTag && metaTag.textContent.includes('ATR')) {
        atr = parseFloat(metaTag.textContent.replace('ATR', '').trim()) || atr;
      }
    }
  } catch (e) {}

  // Parse inner recommended exit SL/TP to determine direction
  try {
    const recExit = card.querySelector('.sig-rec-exit');
    if (recExit) {
      const slText = recExit.querySelector('.sl').textContent;
      const slVal = parseFloat(slText.replace(/[^0-9.]/g, ''));
      if (slVal > price) {
        dir = 'short';
      } else {
        dir = 'long';
      }
    }
  } catch (e) {}

  const defaults = getSymbolDefaults(sym);
  window.openInVisualizer({
    symbol: sym,
    direction: dir,
    entryPrice: price,
    atrValue: atr || defaults.atr,
    slMultiplier: defaults.sl,
    rrrRatio: defaults.rrr,
    trailMultiplier: defaults.trail,
    showTrail: true
  });
};

/**
 * Interface 4: Visualize live symbol directly from the live ticker row
 */
window.visualizeLiveTickerSymbol = function(symbol, event) {
  if (event) event.stopPropagation();

  const sym = String(symbol || 'BTCUSDT').toUpperCase();
  const defaults = getSymbolDefaults(sym);

  // Extract price
  let price = defaults.atr > 50 ? 72000 : (defaults.atr > 5 ? 3400 : 160);
  const priceEl = document.getElementById(`tp-${sym}`);
  if (priceEl) {
    price = parseFloat(priceEl.textContent.replace('$', '').replace(/,/g, '')) || price;
  }

  window.openInVisualizer({
    symbol: sym,
    direction: 'long', // Default to long for raw tickers
    entryPrice: price,
    atrValue: defaults.atr,
    slMultiplier: defaults.sl,
    rrrRatio: defaults.rrr,
    trailMultiplier: defaults.trail,
    showTrail: true
  });
};

/**
 * Hook switchTab visualizer module loading
 */
(function hookVisualizerTab() {
  const orig = window.onTabChange;
  window.onTabChange = function(tab) {
    orig && orig(tab);
    if (tab === 'visualizer') initVisualizerTab();
  };
})();
