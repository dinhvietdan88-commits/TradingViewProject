// ═══ TRADE ANALYSIS MODULE ═══════════════════════════════════
// Powers the Trade Analysis tab: filters, KPIs, charts, table.

let taWinLossChart = null;
let taPnlChart = null;
let taStatusFilter = '';
let taPage = 1;

// ── STATUS PILL TOGGLE ──
function setTAStatus(val, btn) {
  taStatusFilter = val;
  document.querySelectorAll('.ta-pill').forEach(p => p.classList.remove('active'));
  if (btn) btn.classList.add('active');
}

// ── MAIN LOADER ──
async function loadTradeAnalysis(page = 1) {
  taPage = page;
  const fromDate = document.getElementById('taFromDate')?.value || '';
  const toDate = document.getElementById('taToDate')?.value || '';
  const symbol = document.getElementById('taSymbolFilter')?.value || '';
  const limit = 50;
  const offset = (page - 1) * limit;

  let url = `/trades/analysis?limit=${limit}&offset=${offset}`;
  if (fromDate) url += `&from_date=${fromDate}`;
  if (toDate) url += `&to_date=${toDate}`;
  if (symbol) url += `&symbol=${encodeURIComponent(symbol)}`;
  if (taStatusFilter) url += `&status=${taStatusFilter}`;

  const data = await apiFetch(url);
  if (!data) return;

  // Populate symbol dropdown (first load)
  populateSymbolDropdown(data.stats?.symbols_traded || []);

  // Render KPIs
  renderAnalysisKPIs(data.stats || {});

  // Render Charts
  renderWinLossChart(data.stats || {});
  renderPnlChart(data.trades || []);

  // Render Table
  renderAnalysisTable(data.trades || [], data.total || 0, limit, offset);
}

// ── POPULATE SYMBOL DROPDOWN ──
function populateSymbolDropdown(symbols) {
  const sel = document.getElementById('taSymbolFilter');
  if (!sel || sel.options.length > 1) return; // only populate once
  symbols.sort().forEach(s => {
    const opt = document.createElement('option');
    opt.value = s;
    opt.textContent = s;
    sel.appendChild(opt);
  });
}

// ── RENDER KPIs ──
function renderAnalysisKPIs(stats) {
  const wr = stats.win_rate || 0;
  const pnl = stats.total_pnl || 0;
  const pf = stats.profit_factor;

  const wrEl = document.getElementById('taKpiWinRate');
  if (wrEl) {
    wrEl.textContent = `${wr}%`;
    wrEl.style.color = wr >= 50 ? 'var(--buy)' : 'var(--sell)';
  }

  const pnlEl = document.getElementById('taKpiPnl');
  if (pnlEl) {
    pnlEl.textContent = `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}`;
    pnlEl.style.color = pnl >= 0 ? 'var(--buy)' : 'var(--sell)';
  }

  const trEl = document.getElementById('taKpiTrades');
  if (trEl) trEl.textContent = `${stats.winning_trades || 0}W / ${stats.losing_trades || 0}L`;

  const pfEl = document.getElementById('taKpiPF');
  if (pfEl) pfEl.textContent = pf === Infinity ? '∞' : (pf || 0).toFixed(2);

  const strEl = document.getElementById('taKpiStreak');
  if (strEl) strEl.textContent = `${stats.max_win_streak || 0}W / ${stats.max_loss_streak || 0}L`;

  const awEl = document.getElementById('taKpiAvgWin');
  if (awEl) {
    const avgW = stats.avg_win || 0;
    const avgL = stats.avg_loss || 0;
    awEl.textContent = `+${avgW.toFixed(2)} / ${avgL.toFixed(2)}`;
  }
}

// ── WIN/LOSS DONUT CHART ──
function renderWinLossChart(stats) {
  const ctx = document.getElementById('taWinLossChart');
  if (!ctx) return;
  if (taWinLossChart) taWinLossChart.destroy();

  const wins = stats.winning_trades || 0;
  const losses = stats.losing_trades || 0;

  taWinLossChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Wins', 'Losses'],
      datasets: [{
        data: [wins, losses],
        backgroundColor: ['rgba(0,200,150,0.8)', 'rgba(255,77,109,0.8)'],
        borderColor: ['rgba(0,200,150,1)', 'rgba(255,77,109,1)'],
        borderWidth: 2,
        hoverOffset: 8,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '65%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            color: '#9ca3af',
            font: { size: 12, family: "'Inter', sans-serif" },
            padding: 16,
            usePointStyle: true,
          }
        },
        tooltip: {
          backgroundColor: 'rgba(17,19,24,0.95)',
          titleColor: '#e8eaf0',
          bodyColor: '#9ca3af',
          padding: 10,
        }
      }
    }
  });
}

// ── P&L PER TRADE BAR CHART ──
function renderPnlChart(trades) {
  const ctx = document.getElementById('taPnlChart');
  if (!ctx) return;
  if (taPnlChart) taPnlChart.destroy();

  // Filter to FILLED trades with P&L, show last 50 chronologically
  const filled = trades
    .filter(t => t.status === 'FILLED' && t.pnl !== null && t.pnl !== undefined)
    .reverse()
    .slice(-50);

  const labels = filled.map((t, i) => i + 1);
  const pnlData = filled.map(t => t.pnl || 0);
  const colors = pnlData.map(v => v >= 0 ? 'rgba(0,200,150,0.7)' : 'rgba(255,77,109,0.7)');
  const borderColors = pnlData.map(v => v >= 0 ? '#00c896' : '#ff4d6d');

  taPnlChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'P&L',
        data: pnlData,
        backgroundColor: colors,
        borderColor: borderColors,
        borderWidth: 1,
        borderRadius: 3,
        barPercentage: 0.8,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(17,19,24,0.95)',
          titleColor: '#e8eaf0',
          bodyColor: '#9ca3af',
          padding: 10,
          callbacks: {
            title: (items) => {
              const idx = items[0]?.dataIndex;
              const t = filled[idx];
              return t ? `${t.symbol} — ${t.side}` : '';
            },
            label: (item) => {
              const v = item.raw;
              return `P&L: ${v >= 0 ? '+' : ''}${v.toFixed(2)} USDT`;
            }
          }
        }
      },
      scales: {
        x: {
          display: false,
        },
        y: {
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: {
            color: '#6b7280',
            font: { size: 10 },
            callback: v => v >= 0 ? `+${v}` : v,
          }
        }
      }
    }
  });
}

// ── TRADE TABLE ──
function renderAnalysisTable(trades, total, limit, offset) {
  const tbody = document.getElementById('taTradesBody');
  const countEl = document.getElementById('taTradeCount');
  if (!tbody) return;

  if (!trades || trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9"><div class="empty-state"><div class="icon">📊</div><h3>No trades match filters</h3></div></td></tr>';
    if (countEl) countEl.textContent = '0 results';
    return;
  }

  if (countEl) countEl.textContent = `${total} results — Page ${taPage}`;

  tbody.innerHTML = trades.map((t, i) => {
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
      <td><span class="badge ${status === 'FILLED' ? 'badge-ok' : status === 'REJECTED' ? 'badge-fail' : 'badge-warn'}">${status}</span></td>
      <td>
        <button class="qbtn btn-sm-3" style="padding: 2px 6px; font-size: 0.72rem;"
                onclick="openInVisualizer({
                  direction: '${side === 'BUY' ? 'long' : 'short'}',
                  entryPrice: ${t.executed_price || 0},
                  slPrice: ${t.stop_loss_price || 0},
                  tpPrice: ${t.take_profit_price || 0},
                  atrValue: ${t.symbol.toUpperCase().includes('ETH') ? 15.0 : (t.symbol.toUpperCase().includes('SOL') ? 0.8 : 95.93)},
                  symbol: '${t.symbol}'
                })">📐 Visualize</button>
      </td>
    </tr>`;
  }).join('');

  // Pagination
  const pag = document.getElementById('taPagination');
  if (pag) {
    const totalPages = Math.ceil(total / limit);
    let pgHtml = '';
    for (let p = 1; p <= Math.min(totalPages, 10); p++) {
      pgHtml += `<button class="${p === taPage ? 'active' : ''}" onclick="loadTradeAnalysis(${p})">${p}</button>`;
    }
    pag.innerHTML = pgHtml;
  }
}
