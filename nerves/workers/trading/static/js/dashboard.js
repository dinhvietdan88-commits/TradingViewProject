/**
 * Minervini SEPA — Dashboard v2
 * Sprint 7.6: Tabbed SPA with Auth, Scanner, Watchlist, Status
 */

// ═══ CONFIG ═══════════════════════════════════════════
const API = '';
const PAGE_SIZE = 20;
let token = localStorage.getItem('dashboard_token') || '';
let currentPage = 0;
let currentSymbol = '';
let equityChart = null;
let scanResults = [];
let scanSortKey = 'trend_template_score';
let scanSortAsc = false;
let refreshTimer = null;

// ═══ AUTH ═══════════════════════════════════════════════
async function checkAuth() {
    if (!token) {
        // Try without token first — server may not require auth
        try {
            const r = await fetch(`${API}/api/system/status`);
            if (r.ok) { initApp(); return; }
        } catch {}
        showLogin();
        return;
    }
    try {
        const r = await apiFetch('/api/system/status');
        if (r) { initApp(); return; }
    } catch {}
    showLogin();
}

function showLogin() {
    document.getElementById('loginOverlay').style.display = 'flex';
}

window.handleLogin = function() {
    token = document.getElementById('loginToken').value.trim();
    if (!token) return;
    localStorage.setItem('dashboard_token', token);
    document.getElementById('loginError').style.display = 'none';
    apiFetch('/api/system/status').then(data => {
        if (data) {
            document.getElementById('loginOverlay').style.display = 'none';
            initApp();
        } else {
            document.getElementById('loginError').style.display = 'block';
            localStorage.removeItem('dashboard_token');
            token = '';
        }
    });
};

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('loginToken')?.addEventListener('keydown', e => {
        if (e.key === 'Enter') handleLogin();
    });
    document.getElementById('wlInput')?.addEventListener('keydown', e => {
        if (e.key === 'Enter') addSymbol();
    });
    checkAuth();
});

// ═══ API ═══════════════════════════════════════════════
async function apiFetch(path, opts = {}) {
    const params = new URLSearchParams(window.location.search);
    if (params.get('demo') === 'true') {
        const sep = path.includes('?') ? '&' : '?';
        path = `${path}${sep}demo=true`;
    }
    const headers = { ...(opts.headers || {}) };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    try {
        const r = await fetch(`${API}${path}`, { ...opts, headers });
        if (r.status === 401) { showLogin(); return null; }
        if (!r.ok) return null;
        return await r.json();
    } catch { return null; }
}

// ═══ TOAST ═════════════════════════════════════════════
function toast(msg, type = 'info') {
    const c = document.getElementById('toastContainer');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    const icons = { success: '✅', error: '❌', info: 'ℹ️' };
    el.innerHTML = `${icons[type] || ''} ${msg}`;
    c.appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 4000);
}

// ═══ TABS ══════════════════════════════════════════════
function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            const tabId = btn.dataset.tab;
            document.getElementById(`tab-${tabId}`).classList.add('active');
            onTabChange(tabId);
        });
    });
}

let statusTimer = null;
let scanTimer   = null;
let _lastScanTimestamp = null;   // track last seen scan to detect new ones
function onTabChange(tab) {
    if (statusTimer) { clearInterval(statusTimer); statusTimer = null; }
    if (scanTimer)   { clearInterval(scanTimer);   scanTimer   = null; }
    if (tab === 'watchlist') loadWatchlist();
    if (tab === 'scanner') {
        loadLastScan();
        // Auto-poll every 20s so Telegram /scan results appear without clicking
        scanTimer = setInterval(_pollScanUpdates, 20000);
    }
    if (tab === 'status') {
        loadStatus();
        statusTimer = setInterval(loadStatus, 5000);
    }
}

// ═══ CLOCK ═════════════════════════════════════════════
function startClock() {
    const update = () => {
        const el = document.getElementById('clockDisplay');
        if (el) el.textContent = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    };
    update();
    setInterval(update, 1000);
}

// ═══ INIT APP ══════════════════════════════════════════
function initApp() {
    document.getElementById('loginOverlay').style.display = 'none';
    initTabs();
    startClock();
    loadOverview();
    loadWatchlist();
    refreshTimer = setInterval(loadOverview, 30000);
}

async function loadOverview() {
    await Promise.all([loadStats(), loadEquityCurve(), loadTrades(), loadBriefs()]);
}

// ═══ KPI STATS ════════════════════════════════════════
async function loadStats() {
    const grid = document.getElementById('kpiGrid');
    const params = currentSymbol ? `?symbol=${currentSymbol}` : '';
    const s = await apiFetch(`/trades/stats${params}`);
    if (!s) { grid.innerHTML = '<div class="empty-state"><div class="icon">📊</div><h3>No Data</h3></div>'; return; }

    grid.innerHTML = `
        <div class="kpi-card">
            <div class="kpi-label">Win Rate</div>
            <div class="kpi-value ${s.win_rate >= 50 ? 'positive' : 'negative'}">${s.win_rate}%</div>
            <div class="kpi-sub">${s.winning_trades}W / ${s.losing_trades}L</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Profit Factor</div>
            <div class="kpi-value ${s.profit_factor >= 1.5 ? 'positive' : s.profit_factor >= 1 ? 'neutral' : 'negative'}">${s.profit_factor === Infinity ? '∞' : s.profit_factor}</div>
            <div class="kpi-sub">${s.total_trades} trades</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Total P&L</div>
            <div class="kpi-value ${s.total_pnl >= 0 ? 'positive' : 'negative'}">$${s.total_pnl >= 0 ? '+' : ''}${s.total_pnl.toLocaleString()}</div>
            <div class="kpi-sub">Cumulative</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Max Drawdown</div>
            <div class="kpi-value negative">${s.max_drawdown === 0 ? '$0' : '$' + s.max_drawdown.toLocaleString()}</div>
            <div class="kpi-sub">Peak to trough</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Best Trade</div>
            <div class="kpi-value positive">$${s.best_trade > 0 ? '+' : ''}${s.best_trade.toLocaleString()}</div>
            <div class="kpi-sub">Avg win: $${s.avg_win}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Worst Trade</div>
            <div class="kpi-value negative">$${s.worst_trade.toLocaleString()}</div>
            <div class="kpi-sub">Avg loss: $${s.avg_loss}</div>
        </div>`;
}

// ═══ EQUITY CURVE ═════════════════════════════════════
async function loadEquityCurve() {
    const canvas = document.getElementById('equityChart');
    const params = currentSymbol ? `?symbol=${currentSymbol}` : '';
    const data = await apiFetch(`/trades/equity${params}`);

    if (!data || !data.labels || data.labels.length === 0) {
        canvas.parentElement.innerHTML = '<div class="empty-state"><div class="icon">📈</div><h3>No Equity Data</h3><p>Complete trades with P&L to see your equity curve.</p></div>';
        return;
    }

    const labels = data.labels.map(d => new Date(d).toLocaleDateString('vi-VN', { month: 'short', day: 'numeric' }));
    if (equityChart) equityChart.destroy();

    const ctx = canvas.getContext('2d');
    const grad = ctx.createLinearGradient(0, 0, 0, 300);
    const last = data.cumulative_pnl[data.cumulative_pnl.length - 1];
    grad.addColorStop(0, last >= 0 ? 'rgba(16,185,129,0.25)' : 'rgba(239,68,68,0.25)');
    grad.addColorStop(1, last >= 0 ? 'rgba(16,185,129,0)' : 'rgba(239,68,68,0)');
    const clr = last >= 0 ? '#10b981' : '#ef4444';

    equityChart = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets: [{ label: 'P&L ($)', data: data.cumulative_pnl, borderColor: clr, backgroundColor: grad, borderWidth: 2.5, fill: true, tension: 0.35, pointRadius: data.labels.length > 50 ? 0 : 3, pointHoverRadius: 6, pointBackgroundColor: clr, pointBorderColor: '#0a0e17', pointBorderWidth: 2 }] },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: { display: false }, tooltip: { backgroundColor: 'rgba(17,24,39,0.95)', borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1, titleFont: { family: 'Inter', size: 12 }, bodyFont: { family: 'Inter', size: 13, weight: '600' }, padding: 12, cornerRadius: 10, callbacks: { label: c => `P&L: $${c.raw >= 0 ? '+' : ''}${c.raw.toLocaleString()}` } } },
            scales: { x: { grid: { color: 'rgba(255,255,255,0.03)' }, ticks: { color: '#64748b', font: { size: 11, family: 'Inter' }, maxTicksLimit: 10 } }, y: { grid: { color: 'rgba(255,255,255,0.03)' }, ticks: { color: '#64748b', font: { size: 11, family: 'Inter' }, callback: v => '$' + v.toLocaleString() } } }
        }
    });
}

// ═══ TRADES ════════════════════════════════════════════
async function loadTrades() {
    const tbody = document.getElementById('tradesBody');
    const pag = document.getElementById('pagination');
    const params = new URLSearchParams({ limit: PAGE_SIZE, offset: currentPage * PAGE_SIZE });
    if (currentSymbol) params.set('symbol', currentSymbol);
    const data = await apiFetch(`/trades?${params}`);

    if (!data || !data.trades?.length) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty-state"><div class="icon">📋</div><h3>No Trades</h3></td></tr>';
        pag.innerHTML = '';
        return;
    }

    tbody.innerHTML = data.trades.map((t, i) => {
        const date = t.created_at ? new Date(t.created_at).toLocaleString('vi-VN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '-';
        const side = (t.side || '').toLowerCase();
        const pnl = t.pnl != null ? t.pnl : null;
        const pnlCls = pnl != null ? (pnl >= 0 ? 'pnl-positive' : 'pnl-negative') : '';
        const pnlTxt = pnl != null ? `$${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}` : '-';
        const stCls = (t.status || '').toLowerCase() === 'filled' ? 'filled' : 'failed';
        return `<tr>
            <td>${currentPage * PAGE_SIZE + i + 1}</td><td>${date}</td>
            <td style="color:var(--text-primary);font-weight:500">${t.symbol || '-'}</td>
            <td><span class="side-badge ${side}">${(t.side || '-').toUpperCase()}</span></td>
            <td>${t.combined_score || '-'}</td>
            <td>${t.executed_qty || t.requested_qty || '-'}</td>
            <td>${t.executed_price ? '$' + Number(t.executed_price).toLocaleString() : '-'}</td>
            <td class="${pnlCls}">${pnlTxt}</td>
            <td><span class="status-badge ${stCls}">${t.status || '-'}</span></td></tr>`;
    }).join('');

    const totalPages = Math.ceil(data.total / PAGE_SIZE);
    if (totalPages > 1) {
        let b = `<button class="page-btn" onclick="goPage(0)" ${currentPage === 0 ? 'disabled' : ''}>«</button>`;
        b += `<button class="page-btn" onclick="goPage(${currentPage - 1})" ${currentPage === 0 ? 'disabled' : ''}>‹</button>`;
        const s = Math.max(0, currentPage - 2), e = Math.min(totalPages, s + 5);
        for (let i = s; i < e; i++) b += `<button class="page-btn ${i === currentPage ? 'active' : ''}" onclick="goPage(${i})">${i + 1}</button>`;
        b += `<button class="page-btn" onclick="goPage(${currentPage + 1})" ${currentPage >= totalPages - 1 ? 'disabled' : ''}>›</button>`;
        b += `<button class="page-btn" onclick="goPage(${totalPages - 1})" ${currentPage >= totalPages - 1 ? 'disabled' : ''}>»</button>`;
        pag.innerHTML = b;
    } else { pag.innerHTML = ''; }
    document.getElementById('tradeCount').textContent = `${data.total} trades`;
}

window.goPage = function(p) { currentPage = Math.max(0, p); loadTrades(); };

// ═══ BRIEFS ═══════════════════════════════════════════
async function loadBriefs() {
    const el = document.getElementById('briefsList');
    const data = await apiFetch('/api/briefs?limit=5');

    if (!data || !data.briefs?.length) {
        el.innerHTML = '<div class="empty-state"><div class="icon">🌅</div><h3>No Briefs Yet</h3><p>Trigger a morning brief to see results here.</p></div>';
        return;
    }

    el.innerHTML = data.briefs.map(b => {
        const dt = b.created_at ? new Date(b.created_at + 'Z').toLocaleString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '-';
        const preview = (b.ai_analysis || 'No AI analysis').substring(0, 120);
        const detail = b.brief_text || b.ai_analysis || '';
        return `<div class="brief-card" onclick="this.classList.toggle('expanded')">
            <div class="brief-header">
                <span class="brief-date">🌅 ${dt}</span>
                <span class="brief-count">${b.symbols_scanned || 0} symbols • ${b.success ? '✅' : '❌'}</span>
            </div>
            <div class="brief-preview">${preview}...</div>
            <div class="brief-detail">${detail}</div>
        </div>`;
    }).join('');
}

window.triggerBrief = async function() {
    toast('Triggering morning brief...', 'info');
    const r = await apiFetch('/api/brief/trigger', { method: 'POST' });
    if (r) toast('Brief triggered! Check Telegram in 30-60s.', 'success');
    else toast('Failed to trigger brief.', 'error');
};

// ═══ SCANNER ══════════════════════════════════════════

/** Fetch the cached scan results (last run, any source) and render the table. */
async function loadLastScan() {
    const data = await apiFetch('/api/scan/last');
    if (!data || !data.results) return;   // 204 = no scan yet

    scanResults = data.results;
    _lastScanTimestamp = data.timestamp;

    const ts  = data.timestamp ? new Date(data.timestamp).toLocaleTimeString('vi-VN') : '?';
    const src = _srcLabel(data.source);
    document.getElementById('scanStatus').textContent =
        `${data.scanned} symbols · ${ts} · ${src}`;
    renderScanTable();
}

/** Silent background poller — called every 20s when scanner tab is active. */
async function _pollScanUpdates() {
    const data = await apiFetch('/api/scan/last');
    if (!data || !data.results) return;
    if (data.timestamp === _lastScanTimestamp) return;   // nothing new

    // New scan detected (e.g. from Telegram /scan or scheduler)
    scanResults         = data.results;
    _lastScanTimestamp  = data.timestamp;

    const ts  = new Date(data.timestamp).toLocaleTimeString('vi-VN');
    const src = _srcLabel(data.source);
    document.getElementById('scanStatus').textContent =
        `${data.scanned} symbols · ${ts} · ${src}`;
    renderScanTable();

    if (data.source !== 'web') {
        toast(`🔄 Scanner cập nhật từ ${src}`, 'info');
    }
}

function _srcLabel(source) {
    if (source === 'telegram')  return '📱 Telegram';
    if (source === 'scheduler') return '⏰ Scheduler';
    return '🌐 Dashboard';
}

window.triggerScan = async function() {
    const btn = document.getElementById('scanBtn');
    btn.disabled = true;
    btn.textContent = '⏳ Scanning...';
    document.getElementById('scanStatus').textContent = 'Running scan...';

    const data = await apiFetch('/api/scan/trigger', { method: 'POST' });
    btn.disabled = false;
    btn.textContent = '🔍 Run Scan';

    if (!data || !data.results) {
        toast('Scan failed. Check MCP connection.', 'error');
        document.getElementById('scanStatus').textContent = 'Scan failed';
        return;
    }

    scanResults = data.results;
    document.getElementById('scanStatus').textContent =
        `${data.scanned} symbols · ${new Date(data.timestamp).toLocaleTimeString('vi-VN')} · 🌐 Dashboard`;
    renderScanTable();
    toast(`Scan complete: ${data.scanned} symbols`, 'success');
};

function renderScanTable() {
    let rows = [...scanResults];
    const filter = document.getElementById('scanFilter')?.value;
    if (filter) rows = rows.filter(r => r.symbol === filter);

    rows.sort((a, b) => {
        let va = a[scanSortKey], vb = b[scanSortKey];
        if (typeof va === 'boolean') { va = va ? 1 : 0; vb = vb ? 1 : 0; }
        if (va == null) va = -Infinity;
        if (vb == null) vb = -Infinity;
        return scanSortAsc ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
    });

    const tbody = document.getElementById('scanBody');
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state"><div class="icon">📊</div><h3>No Results</h3></td></tr>';
        return;
    }

    tbody.innerHTML = rows.map(r => {
        if (r.error) return `<tr><td>${r.symbol}</td><td colspan="7" style="color:var(--accent-red)">❌ ${r.error}</td></tr>`;
        const scoreCls = r.trend_template_score >= 7 ? 'high' : r.trend_template_score >= 5 ? 'mid' : 'low';
        const chgCls = r.change_pct >= 0 ? 'pnl-positive' : 'pnl-negative';
        return `<tr>
            <td style="color:var(--text-primary);font-weight:600">${r.symbol}</td>
            <td>$${Number(r.price).toLocaleString(undefined, {minimumFractionDigits: 2})}</td>
            <td class="${chgCls}">${r.change_pct >= 0 ? '+' : ''}${r.change_pct.toFixed(2)}%</td>
            <td><span class="score-badge ${scoreCls}">${r.trend_template_score}/8</span></td>
            <td style="font-size:0.75rem">${r.trend_template_stage || '-'}</td>
            <td>${r.vcp_detected ? '<span class="vcp-star">⭐</span> YES' : '<span style="color:var(--text-muted)">—</span>'}</td>
            <td>${r.volume_ratio}x</td>
            <td style="font-size:0.75rem;max-width:200px;overflow:hidden;text-overflow:ellipsis">${r.vcp_note || '-'}</td></tr>`;
    }).join('');

    // Update sort indicators
    document.querySelectorAll('#scanTable thead th[data-sort]').forEach(th => {
        th.classList.toggle('sorted', th.dataset.sort === scanSortKey);
        const icon = th.querySelector('.sort-icon');
        if (icon) icon.remove();
        if (th.dataset.sort === scanSortKey) {
            th.insertAdjacentHTML('beforeend', `<span class="sort-icon">${scanSortAsc ? '▲' : '▼'}</span>`);
        }
    });
}

// Sort handler
document.addEventListener('click', e => {
    const th = e.target.closest('#scanTable thead th[data-sort]');
    if (!th) return;
    const key = th.dataset.sort;
    if (scanSortKey === key) scanSortAsc = !scanSortAsc;
    else { scanSortKey = key; scanSortAsc = false; }
    renderScanTable();
});

// ═══ WATCHLIST ════════════════════════════════════════
async function loadWatchlist() {
    const data = await apiFetch('/api/watchlist');
    if (!data) return;

    const symbols = data.symbols || [];
    document.getElementById('wlBadge').textContent = symbols.length;
    const grid = document.getElementById('wlGrid');

    if (!symbols.length) {
        grid.innerHTML = '<div class="empty-state"><div class="icon">📋</div><h3>Watchlist Empty</h3><p>Add symbols to get started.</p></div>';
        return;
    }

    grid.innerHTML = symbols.map(s => `
        <div class="wl-chip" id="wl-${s}">
            <span>${s}</span>
            <button class="remove-btn" onclick="removeSymbol('${s}')" title="Remove">×</button>
        </div>`).join('');

    // Populate scan filter
    const sel = document.getElementById('scanFilter');
    if (sel) {
        const current = sel.value;
        sel.innerHTML = '<option value="">All Symbols</option>' + symbols.map(s => `<option value="${s}" ${s === current ? 'selected' : ''}>${s}</option>`).join('');
    }
}

window.addSymbol = async function() {
    const input = document.getElementById('wlInput');
    const sym = input.value.trim().toUpperCase();
    if (!sym) return;
    input.value = '';
    const r = await apiFetch('/api/watchlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: sym }) });
    if (r?.added) { toast(`${sym} added to watchlist`, 'success'); loadWatchlist(); }
    else if (r?.reason === 'already_exists') toast(`${sym} already in watchlist`, 'info');
    else toast('Failed to add symbol', 'error');
};

window.removeSymbol = async function(sym) {
    const chip = document.getElementById(`wl-${sym}`);
    if (chip) chip.style.opacity = '0.3';
    const r = await apiFetch(`/api/watchlist/${sym}`, { method: 'DELETE' });
    if (r?.removed) { toast(`${sym} removed`, 'success'); loadWatchlist(); }
    else { toast('Failed to remove symbol', 'error'); if (chip) chip.style.opacity = '1'; }
};

window.syncWatchlist = async function() {
    toast('Syncing from TradingView...', 'info');
    const r = await apiFetch('/api/watchlist/sync', { method: 'PUT' });
    if (r?.synced) { toast(`Synced! Added ${r.added} symbols`, 'success'); loadWatchlist(); }
    else toast(r?.error || 'Sync failed', 'error');
};

// ═══ STATUS ═══════════════════════════════════════════
async function loadStatus() {
    const grid = document.getElementById('statusGrid');
    const data = await apiFetch('/api/system/status');

    if (!data) {
        grid.innerHTML = '<div class="empty-state"><div class="icon">⚡</div><h3>Status Unavailable</h3></div>';
        return;
    }

    const card = (icon, iconCls, name, detail, indicatorCls) =>
        `<div class="status-card">
            <div class="status-icon ${iconCls}">${icon}</div>
            <div class="status-info"><div class="name">${name}</div><div class="detail">${detail}</div></div>
            <div class="status-indicator ${indicatorCls}"></div>
        </div>`;

    grid.innerHTML = [
        card('🖥️', 'online', 'Server', `v${data.server.version} • Uptime: ${data.server.uptime}`, 'on'),
        card('📡', data.mcp.connected ? 'online' : data.mcp.enabled ? 'offline' : 'warning',
            'TradingView MCP', data.mcp.enabled ? (data.mcp.connected ? 'Connected (CDP:9222)' : 'Disconnected') : 'Disabled',
            data.mcp.connected ? 'on' : data.mcp.enabled ? 'off' : 'disabled'),
        card('⏰', data.scheduler.enabled ? 'online' : 'warning',
            'Morning Brief Scheduler', data.scheduler.enabled ? `Scheduled at ${data.scheduler.cron_time} ICT` + (data.scheduler.last_brief ? ` • Last: ${new Date(data.scheduler.last_brief).toLocaleString('vi-VN')}` : '') : 'Disabled',
            data.scheduler.enabled ? 'on' : 'disabled'),
        card('🧠', data.rag.enabled ? 'online' : 'warning',
            'RAG Knowledge Base', data.rag.enabled ? `${data.rag.vectors_count} vectors loaded` : 'Disabled',
            data.rag.enabled ? 'on' : 'disabled'),
        card('🤖', data.telegram_bot.enabled ? 'online' : 'warning',
            'Telegram Bot', data.telegram_bot.enabled ? 'Active (Polling)' : 'Disabled',
            data.telegram_bot.enabled ? 'on' : 'disabled'),
        card('💾', 'online', 'Database',
            `${data.database.signals_count} signals • ${data.database.trades_count} trades • ${data.database.briefs_count} briefs`, 'on'),
    ].join('');

    // Update server dot
    document.getElementById('serverDot').className = 'status-dot';
}
