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
  if (name === 'analysis') loadBriefs();
  if (name === 'status') loadSystemStatus();
  if (name === 'scanner') {} // load on button click
}

// ═══ API FETCH ═══
async function apiFetch(url, opts = {}) {
  try {
    const res = await fetch(API_BASE + url, { headers: headers(), ...opts });
    if (res.status === 401) {
      document.getElementById('loginOverlay').style.display = 'flex';
      document.getElementById('loginError').style.display = 'block';
      return null;
    }
    if (!res.ok) return null;
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
  eqChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.labels.map((l, i) => i + 1),
      datasets: [{
        label: 'Cumulative P&L',
        data: data.cumulative_pnl,
        borderColor: '#6c63ff',
        backgroundColor: 'rgba(108,99,255,0.08)',
        fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const t = data.trades[ctx.dataIndex];
              return t ? `${t.symbol} ${t.side}: ${t.pnl >= 0 ? '+' : ''}${t.pnl} → Cum: ${t.cumulative}` : '';
            }
          }
        }
      },
      scales: {
        x: { display: false },
        y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#6b7280', font: { size: 11 } } }
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
  `;
  updateCDPBadge(mcp);
  loadWebhookLog();
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

async function loadCDPStatus() {
  const data = await apiFetch('/api/system/status');
  if (data) updateCDPBadge(data.mcp || {});
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
  setInterval(() => { loadKPIs(); loadCDPStatus(); }, 30000);
}

['orderPrice', 'orderSL', 'orderTP'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('input', updateRR);
});

document.addEventListener('DOMContentLoaded', init);
