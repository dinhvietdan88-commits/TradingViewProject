// ═══ CONFIG ═══
const API_BASE = '';

// Token priority: URL param > localStorage
function getInitialToken() {
  const params = new URLSearchParams(window.location.search);
  const urlToken = params.get('token');
  if (urlToken) {
    localStorage.setItem('tv_token', urlToken);
    // Clean URL (remove token from address bar for security)
    const clean = window.location.pathname;
    window.history.replaceState({}, '', clean);
    return urlToken;
  }
  return localStorage.getItem('tv_token') || '';
}

let TOKEN = getInitialToken();
const headers = () => ({ 'Authorization': `Bearer ${TOKEN}`, 'Content-Type': 'application/json' });

// ═══ AUTH ═══
async function checkAuth() {
  // 1. Try session cookie (tg_session) — transparent, server validates
  try {
    const res = await fetch('/trades?limit=1', { credentials: 'same-origin' });
    if (res.ok) {
      document.getElementById('loginOverlay').style.display = 'none';
      return true;
    }
  } catch(e) {}

  // 2. Try saved Bearer token (backward compatible)
  if (TOKEN) {
    try {
      const res = await fetch('/trades?limit=1', { headers: headers() });
      if (res.ok) {
        document.getElementById('loginOverlay').style.display = 'none';
        return true;
      }
      // Token invalid — clear it
      TOKEN = '';
      localStorage.removeItem('tv_token');
    } catch(e) {}
  }

  // 3. Show login overlay (or redirect to /auth/login)
  // If server redirected to /auth/login, the browser will follow 302 automatically.
  // This handles the case where login overlay is present in dashboard.html
  document.getElementById('loginOverlay').style.display = 'flex';
  return false;
}

function handleLogout() {
  // Clear Bearer token
  TOKEN = '';
  localStorage.removeItem('tv_token');
  // Navigate to logout endpoint (clears session cookie server-side)
  window.location.href = '/auth/logout';
}

async function handleLogin() {
  const t = document.getElementById('loginToken').value.trim();
  if (!t) return;
  const errEl = document.getElementById('loginError');

  // Verify token before saving
  try {
    const res = await fetch('/trades?limit=1', {
      headers: { 'Authorization': `Bearer ${t}`, 'Content-Type': 'application/json' }
    });
    if (res.ok) {
      TOKEN = t;
      localStorage.setItem('tv_token', t);
      document.getElementById('loginOverlay').style.display = 'none';
      if (errEl) errEl.style.display = 'none';
      init();
    } else {
      if (errEl) { errEl.style.display = 'block'; errEl.textContent = 'Token không hợp lệ. Kiểm tra lại.'; }
    }
  } catch(e) {
    if (errEl) { errEl.style.display = 'block'; errEl.textContent = 'Không thể kết nối server.'; }
  }
}

// ═══ TOAST ═══
function showToast(msg, type = 'info') {
  const c = document.getElementById('toastContainer');
  if (!c) return;
  const d = document.createElement('div');
  d.className = `toast ${type}`;
  d.textContent = msg;
  c.appendChild(d);
  setTimeout(() => d.remove(), 4000);
}

// ═══ CLOCK ═══
function updateClock() {
  const now = new Date();
  const el = document.getElementById('clockDisplay');
  if (el) el.textContent = now.toLocaleTimeString('vi-VN', { hour12: false });
}

// ═══ TABS ═══
function switchTab(name) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  const panel = document.getElementById(`tab-${name}`);
  if (panel) panel.classList.add('active');
  document.querySelectorAll('.tab-btn').forEach(b => {
    if (b.dataset.tab === name) b.classList.add('active');
  });
  if (name === 'indicators') loadIndicators();
  if (name === 'notifications') loadNotifications();
  if (name === 'analysis') { loadBriefs(); startCSLivePolling(); } else { stopCSLivePolling(); }
  if (name === 'trade-analysis') loadTradeAnalysis();
  if (name === 'status') loadSystemStatus();
  if (name === 'scanner') {} // load on button click
  if (typeof window.onTabChange === 'function') window.onTabChange(name);
}

// ═══ API FETCH ═══
async function apiFetch(url, opts = {}) {
  const params = new URLSearchParams(window.location.search);
  if (params.get('demo') === 'true') {
    const sep = url.includes('?') ? '&' : '?';
    url = `${url}${sep}demo=true`;
  }
  try {
    const res = await fetch(API_BASE + url, {
      credentials: 'include',           // always send session cookie
      headers: headers(),
      ...opts,
    });

    // Auth failures: 401 or redirect to login page
    if (res.status === 401 || res.redirected && res.url.includes('auth/login') || res.url.includes('auth/login')) {
      const overlay = document.getElementById('loginOverlay');
      if (overlay) overlay.style.display = 'flex';
      const errEl = document.getElementById('loginError');
      if (errEl) { errEl.textContent = 'Session expired. Please re-authenticate.'; errEl.style.display = 'block'; }
      return null;
    }

    if (!res.ok) {
      console.warn('[apiFetch] Non-OK response:', res.status, url);
      return null;
    }
    return await res.json();
  } catch (e) {
    console.error('API error:', url, e);
    return null;
  }
}

// ═══ KPI — USE /trades/stats ENDPOINT ═══
async function loadKPIs() {
  const grid = document.getElementById('kpiGrid');
  if (!grid) return;
  const stats = await apiFetch('/trades/stats');
  if (!stats) { grid.innerHTML = '<div class="empty-state"><p>No data</p></div>'; return; }
  const wr = stats.win_rate || 0;
  const pnl = stats.total_pnl || 0;
  grid.innerHTML = `
    <div class="kpi-card"><div class="kpi-label">Total Trades</div><div class="kpi-value">${stats.total_trades}</div></div>
    <div class="kpi-card"><div class="kpi-label">Win Rate</div><div class="kpi-value">${wr}%</div>
      <div class="kpi-delta ${wr >= 50 ? 'up' : 'down'}">${wr >= 50 ? '▲' : '▼'} ${wr}%</div></div>
    <div class="kpi-card"><div class="kpi-label">Total P&L</div><div class="kpi-value" style="color:${pnl >= 0 ? 'var(--buy)' : 'var(--sell)'}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}</div></div>
    <div class="kpi-card"><div class="kpi-label">Profit Factor</div><div class="kpi-value">${stats.profit_factor === Infinity ? '∞' : stats.profit_factor}</div>
      <div class="kpi-delta">DD: ${stats.max_drawdown}</div></div>
  `;
}

// ═══ TRADES TABLE — USE /trades ENDPOINT ═══
let tradePage = 1;
async function loadTrades(page = 1) {
  tradePage = page;
  const limit = 15;
  const offset = (page - 1) * limit;
  const data = await apiFetch(`/trades?limit=${limit}&offset=${offset}`);
  const tbody = document.getElementById('tradesBody');
  if (!data || !data.trades || data.trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9"><div class="empty-state"><h3>No trades yet</h3></div></td></tr>';
    return;
  }
  tbody.innerHTML = data.trades.map((t, i) => {
    const side = (t.side || '').toUpperCase();
    const isBuy = side.includes('BUY');
    const pnl = t.pnl || 0;
    const dt = t.created_at || '—';
    const status = (t.status || '—').toUpperCase();
    return `<tr>
      <td>${offset + i + 1}</td>
      <td style="font-family:var(--mono);font-size:0.78rem">${dt}</td>
      <td><strong>${t.symbol || '—'}</strong></td>
      <td><span class="badge ${isBuy ? 'badge-buy' : 'badge-sell'}">${side}</span></td>
      <td>${t.combined_score || '—'}</td>
      <td style="font-family:var(--mono)">${t.executed_qty || t.requested_qty || '—'}</td>
      <td style="font-family:var(--mono)">${t.executed_price || '—'}</td>
      <td style="color:${pnl >= 0 ? 'var(--buy)' : 'var(--sell)'}; font-family:var(--mono)">${pnl !== null && pnl !== undefined ? (pnl >= 0 ? '+' : '') + pnl.toFixed(2) : '—'}</td>
      <td><span class="badge ${status === 'FILLED' ? 'badge-ok' : 'badge-fail'}">${status}</span></td>
    </tr>`;
  }).join('');
  document.getElementById('tradeCount').textContent = `Page ${page}`;
  const pag = document.getElementById('pagination');
  const totalPages = Math.ceil((data.total || 1) / limit);
  let pgHtml = '';
  for (let p = 1; p <= Math.min(totalPages, 10); p++) {
    pgHtml += `<button class="${p === page ? 'active' : ''}" onclick="loadTrades(${p})">${p}</button>`;
  }
  pag.innerHTML = pgHtml;
}

// ═══ EQUITY CHART — USE /trades/equity ENDPOINT ═══
let eqChart = null;
async function loadEquityChart() {
  const data = await apiFetch('/trades/equity');
  if (!data || !data.labels || data.labels.length === 0) return;
  const ctx = document.getElementById('equityChart');
  if (!ctx) return;
  if (eqChart) eqChart.destroy();

  // Gradient for equity line
  const ctxDraw = ctx.getContext('2d');
  const eqGrad = ctxDraw.createLinearGradient(0, 0, 0, 300);
  eqGrad.addColorStop(0, 'rgba(108,99,255,0.25)');
  eqGrad.addColorStop(1, 'rgba(108,99,255,0.02)');

  // Gradient for drawdown area
  const ddGrad = ctxDraw.createLinearGradient(0, 0, 0, 300);
  ddGrad.addColorStop(0, 'rgba(255,77,109,0.03)');
  ddGrad.addColorStop(1, 'rgba(255,77,109,0.2)');

  eqChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.labels.map((l, i) => i + 1),
      datasets: [
        {
          label: 'Cumulative P&L',
          data: data.cumulative_pnl,
          borderColor: '#6c63ff',
          backgroundColor: eqGrad,
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: '#6c63ff',
          borderWidth: 2.5,
          yAxisID: 'y',
          order: 1,
        },
        {
          label: 'Drawdown %',
          data: (data.drawdown_pct || []).map(v => -v),
          borderColor: 'rgba(255,77,109,0.6)',
          backgroundColor: ddGrad,
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointHoverBackgroundColor: '#ff4d6d',
          borderWidth: 1.5,
          borderDash: [4, 3],
          yAxisID: 'y1',
          order: 2,
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: true,
          position: 'top',
          labels: {
            color: '#9ca3af',
            font: { size: 11, family: "'Inter', sans-serif" },
            boxWidth: 14,
            padding: 16,
            usePointStyle: true,
          }
        },
        tooltip: {
          backgroundColor: 'rgba(17,19,24,0.95)',
          borderColor: 'rgba(255,255,255,0.1)',
          borderWidth: 1,
          titleColor: '#e8eaf0',
          bodyColor: '#9ca3af',
          padding: 12,
          callbacks: {
            label: (tooltipCtx) => {
              const idx = tooltipCtx.dataIndex;
              if (tooltipCtx.datasetIndex === 0) {
                const t = data.trades[idx];
                return t ? `P&L: ${t.pnl >= 0 ? '+' : ''}${t.pnl} → Cum: ${t.cumulative}` : '';
              } else {
                const dd = data.drawdown_pct ? data.drawdown_pct[idx] : 0;
                return `Drawdown: -${dd}%`;
              }
            },
            title: (items) => {
              const idx = items[0]?.dataIndex;
              const t = data.trades[idx];
              return t ? `${t.symbol} ${t.side} — #${idx + 1}` : `Trade #${idx + 1}`;
            }
          }
        }
      },
      scales: {
        x: { display: false },
        y: {
          position: 'left',
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: {
            color: '#6c63ff',
            font: { size: 11 },
            callback: v => v >= 0 ? `+${v}` : v,
          },
          title: {
            display: true,
            text: 'P&L (USDT)',
            color: '#6c63ff',
            font: { size: 10, weight: '500' },
          }
        },
        y1: {
          position: 'right',
          grid: { drawOnChartArea: false },
          ticks: {
            color: '#ff4d6d',
            font: { size: 10 },
            callback: v => `${v}%`,
          },
          title: {
            display: true,
            text: 'Drawdown',
            color: '#ff4d6d',
            font: { size: 10, weight: '500' },
          },
          reverse: false,
        }
      }
    }
  });
}

// ═══ SYSTEM STATUS — USE /api/system/status ENDPOINT ═══
async function loadSystemStatus() {
  const grid = document.getElementById('statusGrid');
  if (!grid) return;
  const data = await apiFetch('/api/system/status');
  if (!data) { grid.innerHTML = '<p class="muted-label">Cannot reach server</p>'; return; }
  const s = data.server || {};
  const mcp = data.mcp || {};
  const rag_st = data.rag || {};
  const tg = data.telegram_bot || {};
  const sched = data.scheduler || {};
  const db = data.database || {};
  
  const apiHealth = data.health_api_server || 'UNKNOWN';
  const cdpHealth = data.health_cdp || 'UNKNOWN';
  const dbHealth = data.health_database || 'UNKNOWN';
  const runnerStatus = data.test_runner_status || 'UNKNOWN';
  const lastRun = data.last_test_run || {};
  const lastRunTime = lastRun.timestamp ? lastRun.timestamp.replace('T', ' ').substring(0, 19) : 'N/A';

  grid.innerHTML = `
    <div class="status-card"><div class="status-card-icon">💚</div><div class="status-card-body">
      <div class="status-card-name">Server</div><div class="status-card-val status-ok">v${s.version} — ${s.uptime}</div></div></div>
    <div class="status-card"><div class="status-card-icon">📡</div><div class="status-card-body">
      <div class="status-card-name">MCP (CDP:9222)</div><div class="status-card-val ${mcp.connected ? 'status-ok' : 'status-warn'}">${mcp.connected ? 'Connected' : mcp.enabled ? 'Disconnected' : 'Disabled'}</div></div></div>
    <div class="status-card"><div class="status-card-icon">📚</div><div class="status-card-body">
      <div class="status-card-name">RAG Knowledge</div><div class="status-card-val ${rag_st.enabled ? 'status-ok' : 'status-warn'}">${rag_st.enabled ? rag_st.vectors_count + ' vectors' : 'Disabled'}</div></div></div>
    <div class="status-card"><div class="status-card-icon">🤖</div><div class="status-card-body">
      <div class="status-card-name">Telegram Bot</div><div class="status-card-val ${tg.enabled ? 'status-ok' : 'status-warn'}">${tg.enabled ? 'Running' : 'Off'}</div></div></div>
    <div class="status-card"><div class="status-card-icon">🌅</div><div class="status-card-body">
      <div class="status-card-name">Morning Brief</div><div class="status-card-val ${sched.enabled ? 'status-ok' : 'status-warn'}">${sched.enabled ? 'Cron: ' + sched.cron_time : 'Disabled'}</div></div></div>
    <div class="status-card"><div class="status-card-icon">🗄</div><div class="status-card-body">
      <div class="status-card-name">Database</div><div class="status-card-val status-ok">${db.signals_count || 0} signals / ${db.trades_count || 0} trades / ${db.briefs_count || 0} briefs</div></div></div>
    <div class="status-card"><div class="status-card-icon">🔐</div><div class="status-card-body">
      <div class="status-card-name">Auth</div><div class="status-card-val">${data.auth_required ? 'Token Required' : 'Open Access'}</div></div></div>
    <div class="status-card"><div class="status-card-icon">🩺</div><div class="status-card-body">
      <div class="status-card-name">API Server Health</div><div class="status-card-val ${apiHealth === 'OK' ? 'status-ok' : 'status-warn'}">${apiHealth}</div></div></div>
    <div class="status-card"><div class="status-card-icon">🎛</div><div class="status-card-body">
      <div class="status-card-name">CDP Liveness</div><div class="status-card-val ${cdpHealth === 'OK' ? 'status-ok' : 'status-warn'}">${cdpHealth}</div></div></div>
    <div class="status-card"><div class="status-card-icon">💾</div><div class="status-card-body">
      <div class="status-card-name">Database Health</div><div class="status-card-val ${dbHealth === 'OK' ? 'status-ok' : 'status-warn'}">${dbHealth}</div></div></div>
    <div class="status-card"><div class="status-card-icon">⚙️</div><div class="status-card-body">
      <div class="status-card-name">Auto-Test Runner</div><div class="status-card-val ${runnerStatus === 'PASSING' ? 'status-ok' : 'status-warn'}">${runnerStatus} <span style="font-size:0.75rem;opacity:0.7">(${lastRunTime})</span></div></div></div>
  `;
  updateCDPBadge(mcp);
  updateProtectionStatus(data.protection || {});
  loadWebhookLog();
  if (typeof refreshVBSStatus === 'function') {
    refreshVBSStatus();
  }
  if (typeof window.onRiskExchangeChange === 'function') {
    window.onRiskExchangeChange();
  }
}

function updateCDPBadge(mcp) {
  const badge = document.getElementById('cdpBadge');
  const label = document.getElementById('cdpLabel');
  if (!badge || !label) return;
  if (mcp && mcp.connected) {
    badge.className = 'cdp-badge connected'; label.textContent = 'CDP: Connected';
  } else if (mcp && mcp.enabled) {
    badge.className = 'cdp-badge error'; label.textContent = 'CDP: Offline';
  } else {
    badge.className = 'cdp-badge'; label.textContent = 'CDP: Disabled';
  }
}

function updateProtectionStatus(protection) {
  const regimeBadge = document.getElementById('regimeBadge');
  const shieldBadge = document.getElementById('shieldBadge');
  
  if (regimeBadge) {
    const regime = protection.market_regime || 'TRENDING';
    if (regime === 'CHOP') {
      regimeBadge.className = 'p-badge chop';
      regimeBadge.textContent = 'Chop 🟡';
    } else {
      regimeBadge.className = 'p-badge trending';
      regimeBadge.textContent = 'Trending 🟢';
    }
  }
  
  if (shieldBadge) {
    const safeMode = protection.safe_mode_active || false;
    const dd = protection.safe_mode_drawdown || 0.0;
    if (safeMode) {
      shieldBadge.className = 'p-badge safe-mode';
      shieldBadge.textContent = `Safe Mode 🔴 (${dd.toFixed(1)}% DD)`;
    } else {
      shieldBadge.className = 'p-badge normal';
      shieldBadge.textContent = 'Normal 🟢';
    }
  }
}

async function loadCDPStatus() {
  const data = await apiFetch('/api/system/status');
  if (data) {
    updateCDPBadge(data.mcp || {});
    updateProtectionStatus(data.protection || {});
  }
}

async function loadWebhookLog() {
  const el = document.getElementById('webhookLog');
  if (!el) return;
  const data = await apiFetch('/trades?limit=20');
  if (!data || !data.trades || data.trades.length === 0) {
    el.innerHTML = '<p class="muted-label">No log entries</p>'; return;
  }
  el.innerHTML = data.trades.map(t => {
    const ts = t.created_at ? t.created_at.split(' ')[1] || t.created_at : '—';
    const side = (t.side || '').toUpperCase();
    const cls = side.includes('BUY') ? 'buy-line' : side.includes('SELL') ? 'sell-line' : '';
    return `<div class="wl-line ${cls}"><span class="ts">${ts}</span> ${side} ${t.symbol || '—'} @ ${t.executed_price || '—'} [${(t.status||'').toUpperCase()}]</div>`;
  }).join('');
}

// ═══ QUICK ORDER — USE /webhook ENDPOINT ═══
let orderSide = 'BUY';
function openOrderModal() { document.getElementById('orderModal').style.display = 'flex'; }
function closeOrderModal() { document.getElementById('orderModal').style.display = 'none'; }
function setSide(s) {
  orderSide = s;
  document.getElementById('btnBuy').className = `side-btn ${s === 'BUY' ? 'active buy' : 'buy'}`;
  document.getElementById('btnSell').className = `side-btn ${s === 'SELL' ? 'active sell' : 'sell'}`;
  updateRR();
}
function updateRR() {
  const price = parseFloat(document.getElementById('orderPrice').value) || 0;
  const sl = parseFloat(document.getElementById('orderSL').value) || 0;
  const tp = parseFloat(document.getElementById('orderTP').value) || 0;
  const el = document.getElementById('rrDisplay');
  if (!el) return;
  if (!price || !sl || !tp) { el.textContent = 'R:R — / —'; return; }
  const risk = Math.abs(price - sl);
  const reward = Math.abs(tp - price);
  const rr = risk > 0 ? (reward / risk).toFixed(2) : '—';
  el.textContent = `R:R  1 : ${rr}  |  Risk: ${risk.toFixed(2)}  Reward: ${reward.toFixed(2)}`;
  el.style.color = parseFloat(rr) >= 2 ? 'var(--buy)' : parseFloat(rr) >= 1 ? 'var(--warn)' : 'var(--sell)';
}

async function submitOrder() {
  const symbol = document.getElementById('orderSymbol').value.trim().toUpperCase();
  const price = document.getElementById('orderPrice').value;
  const qty = document.getElementById('orderQty').value;
  if (!symbol) { showToast('Nhập symbol!', 'error'); return; }

  const payload = {
    symbol,
    action: orderSide.toLowerCase(),
    price: price || '',
    quoteQty: parseFloat(qty) || 10,
    interval: '60',
    source: 'dashboard',
  };
  const sl = document.getElementById('orderSL').value;
  const tp = document.getElementById('orderTP').value;
  if (sl) payload.sl = sl;
  if (tp) payload.tp = tp;

  showToast(`Đang gửi lệnh ${orderSide} ${symbol}...`, 'info');
  const res = await apiFetch('/webhook', { method: 'POST', body: JSON.stringify(payload) });
  if (res && res.received) {
    showToast(`✅ Lệnh ${orderSide} ${symbol} đã gửi! Signal #${res.signal_id}`, 'success');
    closeOrderModal();
    setTimeout(() => { loadTrades(); loadKPIs(); }, 2000);
  } else {
    showToast('❌ Gửi lệnh thất bại', 'error');
  }
}

// ═══ BRIEF TRIGGER — USE /api/brief/trigger ═══
async function triggerBrief() {
  showToast('🌅 Đang tạo Morning Brief...', 'info');
  const res = await apiFetch('/api/brief/trigger', { method: 'POST' });
  if (res) showToast('Morning Brief đang chạy!', 'success');
  else showToast('Brief trigger failed', 'error');
}

// ═══ INIT ═══
async function init() {
  const authed = await checkAuth();
  if (!authed) return;
  updateClock();
  setInterval(updateClock, 1000);
  loadKPIs();
  loadTrades();
  loadEquityChart();
  loadCDPStatus();
  loadRiskGates();
  loadRiskLogs();
  if (typeof loadSignalStats === 'function') {
    loadSignalStats();
  }
  setInterval(() => {
    loadKPIs();
    loadCDPStatus();
    loadRiskGates();
    loadRiskLogs();
    if (typeof loadSignalStats === 'function') {
      loadSignalStats();
    }
  }, 30000);
}

['orderPrice', 'orderSL', 'orderTP'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('input', updateRR);
});

async function refreshVBSStatus() {
  const el = document.getElementById('vbsStatusContent');
  if (!el) return;
  el.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  const data = await apiFetch('/api/queue-status');
  if (!data) {
    el.innerHTML = '<p class="muted-label">Không thể kết nối VPS Buffer Service</p>';
    return;
  }
  if (!data.enabled) {
    el.innerHTML = `
      <div class="status-card-val text-muted" style="grid-column: 1 / -1; padding: 20px; text-align: center;">
        VPS Buffer Service (VBS) is disabled. Set <code>VPS_BUFFER_ENABLED=true</code> to enable queueing.
      </div>
    `;
    return;
  }
  
  if (data.error) {
    el.innerHTML = `
      <div class="status-card-val status-warn" style="grid-column: 1 / -1; padding: 20px; text-align: center;">
        Lỗi kết nối VPS: ${data.error}
      </div>
    `;
    return;
  }

  const s = data.summary || {};
  const oldestStr = s.oldest_pending_age_minutes !== null ? `${Math.round(s.oldest_pending_age_minutes)}m` : '—';
  
  let signalsHtml = '';
  if (data.pending_signals && data.pending_signals.length > 0) {
    signalsHtml = data.pending_signals.map(sig => `
      <div style="display:flex; justify-content:space-between; align-items:center; padding: 8px 12px; background: rgba(255,255,255,0.02); border-radius: 4px; border: 1px solid rgba(255,255,255,0.04); font-size: 0.8rem; font-family: var(--mono)">
        <div>
          <span class="badge ${sig.action === 'buy' ? 'badge-buy' : 'badge-sell'}">${sig.action.toUpperCase()}</span>
          <strong>${sig.symbol}</strong>
          <span style="opacity:0.5; margin-left:8px">ID #${sig.queue_id}</span>
        </div>
        <div>
          <span style="opacity:0.6">Nhận lúc: ${sig.received_at}</span>
          <span style="color:var(--warn); margin-left:12px">TTL: ${Math.round(sig.ttl_remaining_minutes)}m</span>
        </div>
      </div>
    `).join('');
  } else {
    signalsHtml = '<div style="text-align:center; padding: 12px; opacity:0.5">Không có signal nào đang chờ xử lý</div>';
  }

  el.innerHTML = `
    <div style="grid-column: 1 / -1; display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 16px;">
      <div class="status-card" style="margin:0"><div class="status-card-icon">📥</div><div class="status-card-body">
        <div class="status-card-name">Pending Queue</div><div class="status-card-val ${s.pending > 0 ? 'status-warn' : 'status-ok'}">${s.pending} signals</div></div></div>
      <div class="status-card" style="margin:0"><div class="status-card-icon">⚡</div><div class="status-card-body">
        <div class="status-card-name">Dispatched</div><div class="status-card-val">${s.dispatched} signals</div></div></div>
      <div class="status-card" style="margin:0"><div class="status-card-icon">✅</div><div class="status-card-body">
        <div class="status-card-name">ACKed Today</div><div class="status-card-val status-ok">${s.acked_today} signals</div></div></div>
      <div class="status-card" style="margin:0"><div class="status-card-icon">❌</div><div class="status-card-body">
        <div class="status-card-name">Stale Today</div><div class="status-card-val ${s.stale_today > 0 ? 'status-warn' : 'status-ok'}">${s.stale_today} signals</div></div></div>
      <div class="status-card" style="margin:0"><div class="status-card-icon">⏱️</div><div class="status-card-body">
        <div class="status-card-name">Oldest Pending</div><div class="status-card-val">${oldestStr}</div></div></div>
    </div>
    <div style="grid-column: 1 / -1;">
      <div class="section-title mb-8" style="font-size:0.85rem">📋 Pending Signals in Queue</div>
      <div style="display:flex; flex-direction:column; gap:6px;">
        ${signalsHtml}
      </div>
    </div>
  `;
}

async function loadRiskGates() {
  const container = document.getElementById('riskGatesGrid');
  if (!container) return;

  const statuses = await apiFetch('/api/risk/status');
  if (!statuses) {
    container.innerHTML = '<p class="muted-label">Risk stats unavailable</p>';
    return;
  }

  container.innerHTML = statuses.map(s => {
    const cbState = s.state.toUpperCase();
    const stateClass = cbState === 'CLOSED' ? 'closed' : (cbState === 'HALF-OPEN' ? 'half-open' : 'open');
    const displayState = cbState === 'CLOSED' ? 'CB: CLOSED' : (cbState === 'HALF-OPEN' ? 'CB: HALF-OPEN' : 'CB: OPEN');

    const lossPct = s.dailyLossCap > 0 ? Math.min(100, (s.dailyLoss / s.dailyLossCap) * 100) : 0;
    const lossFillClass = s.dailyLoss >= s.dailyLossCap ? 'danger' : 'normal';

    const ddPct = s.drawdownCap > 0 ? Math.min(100, (s.drawdown / s.drawdownCap) * 100) : 0;
    const ddFillClass = s.drawdown >= s.drawdownCap ? 'danger' : 'drawdown';

    let actionBtnHtml = '';
    if (cbState === 'CLOSED') {
      actionBtnHtml = `<button class="override-btn" onclick="toggleCircuitBreaker('${s.exchange}', 'trip')">Force Trip</button>`;
    } else {
      actionBtnHtml = `<button class="reset-btn" onclick="toggleCircuitBreaker('${s.exchange}', 'reset')">Reset Closed</button>`;
    }

    return `
      <div class="risk-card">
        <div class="risk-card-header">
          <span class="risk-card-name" style="display: flex; align-items: center;">
            ${s.exchange}
            <button class="settings-gear-btn" onclick="openRiskSettings('${s.exchange}')" title="Configure Risk Thresholds">⚙️</button>
          </span>
          <span class="cb-badge ${stateClass}">${displayState}</span>
        </div>
        <div class="risk-gauges">
          <div class="gauge-item">
            <div class="gauge-header">
              <span>Daily Loss (24h)</span>
              <span class="val">$${s.dailyLoss.toFixed(2)} / $${s.dailyLossCap.toFixed(2)}</span>
            </div>
            <div class="gauge-bar-bg">
              <div class="gauge-bar-fill ${lossFillClass}" style="width: ${lossPct}%"></div>
            </div>
          </div>
          <div class="gauge-item">
            <div class="gauge-header">
              <span>Rolling Drawdown</span>
              <span class="val">${s.drawdown.toFixed(2)}% / ${s.drawdownCap.toFixed(2)}%</span>
            </div>
            <div class="gauge-bar-bg">
              <div class="gauge-bar-fill ${ddFillClass}" style="width: ${ddPct}%"></div>
            </div>
          </div>
        </div>
        <div class="risk-card-footer">
          <span>Latency: ${s.latencyMs}ms</span>
          ${actionBtnHtml}
        </div>
      </div>
    `;
  }).join('');
}

window.toggleCircuitBreaker = async function(exchange, action) {
  showToast(`Updating circuit breaker for ${exchange}...`, 'info');
  const res = await apiFetch('/api/risk/override', {
    method: 'POST',
    body: JSON.stringify({ exchange, action })
  });
  if (res && res.status === 'success') {
    showToast(`✅ ${res.message}`, 'success');
    loadRiskGates();
    loadRiskLogs();
    loadCDPStatus();
  } else {
    showToast(`❌ Override action failed`, 'error');
  }
};

window.openRiskSettings = async function(exchange) {
  // Switch to System Tab
  switchTab('status');
  
  // Set dropdown value and load exchange settings
  const select = document.getElementById('riskSelectExchange');
  if (select) {
    select.value = exchange.toLowerCase();
    await window.onRiskExchangeChange();
  }
  
  // Scroll to riskSettingsPanel with smooth animation
  const panel = document.getElementById('riskSettingsPanel');
  if (panel) {
    panel.scrollIntoView({ behavior: 'smooth' });
    // Flash background for visual feedback
    panel.style.transition = 'background 0.3s';
    panel.style.background = 'rgba(108, 99, 255, 0.1)';
    setTimeout(() => {
      panel.style.background = '';
    }, 1000);
  }
};

window.onRiskExchangeChange = async function() {
  const select = document.getElementById('riskSelectExchange');
  if (!select) return;
  const exchange = select.value;
  
  const settings = await apiFetch(`/api/risk/settings?exchange=${exchange}`);
  if (!settings) {
    showToast(`❌ Không thể tải cài đặt rủi ro cho ${exchange}`, 'error');
    return;
  }
  
  const dailyLossEl = document.getElementById('tabRiskDailyLossCap');
  const ddCapEl = document.getElementById('tabRiskDrawdownCap');
  const maxQuoteEl = document.getElementById('tabRiskMaxQuoteQty');
  const slipEl = document.getElementById('tabRiskSlippageLimit');
  const safeModeEl = document.getElementById('tabRiskSafeMode');
  
  if (dailyLossEl) dailyLossEl.value = settings.daily_loss_cap;
  if (ddCapEl) ddCapEl.value = settings.drawdown_cap;
  if (maxQuoteEl) maxQuoteEl.value = settings.max_quote_qty;
  if (slipEl) slipEl.value = settings.slippage_limit;
  if (safeModeEl) safeModeEl.value = settings.safe_mode;
};

window.submitTabRiskSettings = async function() {
  const select = document.getElementById('riskSelectExchange');
  if (!select) return;
  const exchange = select.value;
  
  const payload = {
    exchange: exchange,
    daily_loss_cap: parseFloat(document.getElementById('tabRiskDailyLossCap').value),
    drawdown_cap: parseFloat(document.getElementById('tabRiskDrawdownCap').value),
    max_quote_qty: parseFloat(document.getElementById('tabRiskMaxQuoteQty').value),
    slippage_limit: parseFloat(document.getElementById('tabRiskSlippageLimit').value),
    safe_mode: parseInt(document.getElementById('tabRiskSafeMode').value)
  };
  
  showToast(`Đang lưu cài đặt rủi ro cho ${exchange}...`, 'info');
  const res = await apiFetch('/api/risk/settings', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
  
  if (res && res.status === 'success') {
    showToast(`✅ ${res.message}`, 'success');
    loadRiskGates();
    loadRiskLogs();
    loadCDPStatus();
  } else {
    showToast(`❌ Lưu cài đặt rủi ro thất bại`, 'error');
  }
};

async function loadRiskLogs() {
  const container = document.getElementById('cbActivityLogs');
  const countEl = document.getElementById('cbLogsCount');
  if (!container) return;
  
  const logs = await apiFetch('/api/risk/logs?limit=10');
  if (!logs) {
    container.innerHTML = '<p class="muted-label">Logs unavailable</p>';
    return;
  }
  
  if (countEl) countEl.textContent = `${logs.length} entries`;
  
  if (logs.length === 0) {
    container.innerHTML = '<p class="muted-label" style="text-align:center; padding:10px; font-size:0.75rem;">No transitions logged</p>';
    return;
  }
  
  container.innerHTML = logs.map(l => {
    const ts = l.timestamp ? l.timestamp.split(' ')[1] || l.timestamp : '—';
    const badgeClass = l.new_state.toUpperCase() === 'OPEN' ? 'open' : 'closed';
    return `
      <div class="cb-log-item">
        <div class="cb-log-item-meta">
          <strong>${l.exchange.toUpperCase()}</strong>
          <span class="cb-log-badge ${badgeClass}">${l.prev_state} ➜ ${l.new_state}</span>
        </div>
        <div class="cb-log-item-msg">${l.trigger_reason}</div>
        <div class="cb-log-item-meta">
          <span>${ts}</span>
          <span>Symbol: ${l.symbol}</span>
        </div>
      </div>
    `;
  }).join('');
}

document.addEventListener('DOMContentLoaded', init);

