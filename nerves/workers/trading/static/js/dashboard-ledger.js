/**
 * dashboard-ledger.js — Unified State Ledger Module
 * Visually represents multi-layer processing pipelines for trades & signals.
 */

const LEDGER = {
  page: 1,
  limit: 10,
  total: 0,
  symbolFilter: '',
  stateFilter: '',
  debounceTimer: null,
  initDone: false
};

const LEDGER_REASON_MAP = {
  "duplicate_signal": "Tín hiệu bị từ chối ở Tầng 1 (Gatekeeper) do trùng lặp (dedup 60s)",
  "invalid_timeframe": "Tín hiệu bị từ chối ở Tầng 1 (Gatekeeper) do khung thời gian không hợp lệ",
  "unknown_action": "Tín hiệu bị từ chối ở Tầng 1 (Gatekeeper) do hành động không xác định",
  "market_regime_chop_block": "Tín hiệu bị loại bỏ ở Tầng 2 (Macro Filter) do thị trường CHOP (Chop Regime Block)",
  "macro_trend_conflict": "Tín hiệu bị loại bỏ ở Tầng 2 (Macro Filter) do xu hướng vĩ mô không thuận lợi (Daily/4H SMA Veto)",
  "sepa_trend_template_failed": "Tín hiệu bị loại bỏ ở Tầng 3 (Strategy Filter) do Trend Template không đủ tiêu chuẩn (< 5/8)",
  "mean_reversion_indicators_failed": "Tín hiệu bị loại bỏ ở Tầng 3 (Strategy Filter) do không đạt điều kiện chỉ báo RSI & Bollinger Bands",
  "low_confidence": "Tín hiệu bị loại bỏ ở Tầng 4 (AI Analyzer) do điểm AI quá thấp (< 5/10)",
};

// Chain tab change hook to initialize Ledger tab when switched
const origOnTabChangeLedger = window.onTabChange;
window.onTabChange = function(tab) {
  if (origOnTabChangeLedger) origOnTabChangeLedger(tab);
  if (tab === 'ledger') {
    initLedgerTab();
  }
};

async function initLedgerTab() {
  if (LEDGER.initDone) {
    refreshLedgerData();
    return;
  }
  LEDGER.initDone = true;
  refreshLedgerData();
}

async function refreshLedgerData() {
  clearTimeout(LEDGER.debounceTimer);
  LEDGER.debounceTimer = setTimeout(async () => {
    LEDGER.symbolFilter = document.getElementById('ledgerFilterSymbol').value.trim().toUpperCase();
    LEDGER.stateFilter = document.getElementById('ledgerFilterState').value;
    LEDGER.page = 1;
    await loadLedgerSignals();
  }, 250);
}

async function loadLedgerSignals() {
  const listEl = document.getElementById('ledgerSignalsList');
  if (!listEl) return;

  listEl.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 40px;"><div class="spinner"></div><p style="margin-top: 10px;">Đang tải danh sách Ledger...</p></div>';

  const offset = (LEDGER.page - 1) * LEDGER.limit;
  let url = `/api/signals?limit=${LEDGER.limit}&offset=${offset}`;
  if (LEDGER.symbolFilter) {
    url += `&symbol=${encodeURIComponent(LEDGER.symbolFilter)}`;
  }
  if (LEDGER.stateFilter) {
    url += `&state=${encodeURIComponent(LEDGER.stateFilter)}`;
  }

  const res = await apiFetch(url);
  if (!res || !res.signals || res.signals.length === 0) {
    listEl.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 40px; border: 1px dashed var(--border-color); border-radius: 12px;">Không tìm thấy tín hiệu nào trong Sổ cái</div>';
    updateLedgerPagination(0);
    return;
  }

  LEDGER.total = res.total || 0;
  updateLedgerPagination(LEDGER.total);

  listEl.innerHTML = res.signals.map(sig => {
    const isBuy = (sig.action || '').toLowerCase() === 'buy';
    const actionClass = isBuy ? 'buy' : 'sell';
    const actionText = isBuy ? 'BUY' : 'SELL';
    
    // Process timeline steps: 1=Gatekeeper, 2=Macro, 3=Strategy, 4=Execution
    let s1 = 'disabled', s2 = 'disabled', s3 = 'disabled', s4 = 'disabled';
    let s1Text = 'Chờ xử lý', s2Text = 'Chờ xử lý', s3Text = 'Chờ xử lý', s4Text = 'Chờ xử lý';
    
    const state = sig.state || 'INGESTED';
    const reason = sig.rejection_reason || '';
    
    if (state === 'REJECTED') {
      if (reason === 'duplicate_signal' || reason === 'invalid_timeframe' || reason === 'unknown_action') {
        s1 = 'failed'; s1Text = 'Từ chối';
      } else if (reason === 'market_regime_chop_block' || reason === 'macro_trend_conflict') {
        s1 = 'passed'; s1Text = 'Đã duyệt';
        s2 = 'failed'; s2Text = 'Từ chối';
      } else if (reason === 'sepa_trend_template_failed' || reason === 'mean_reversion_indicators_failed') {
        s1 = 'passed'; s1Text = 'Đã duyệt';
        s2 = 'passed'; s2Text = 'Đã duyệt';
        s3 = 'failed'; s3Text = 'Từ chối';
      } else {
        s1 = 'passed'; s1Text = 'Đã duyệt';
        s2 = 'passed'; s2Text = 'Đã duyệt';
        s3 = 'passed'; s3Text = 'Đã duyệt';
        s4 = 'failed'; s4Text = 'Từ chối';
      }
    } else if (state === 'COMPLETED') {
      s1 = 'passed'; s1Text = 'Đã duyệt';
      s2 = 'passed'; s2Text = 'Đã duyệt';
      s3 = 'passed'; s3Text = 'Đã duyệt';
      s4 = 'passed'; s4Text = 'Đã duyệt';
    } else if (state === 'STRATEGY_PASSED') {
      s1 = 'passed'; s1Text = 'Đã duyệt';
      s2 = 'passed'; s2Text = 'Đã duyệt';
      s3 = 'passed'; s3Text = 'Đã duyệt';
      s4 = 'active'; s4Text = 'Đang xử lý';
    } else if (state === 'MACRO_PASSED') {
      s1 = 'passed'; s1Text = 'Đã duyệt';
      s2 = 'passed'; s2Text = 'Đã duyệt';
      s3 = 'active'; s3Text = 'Đang xử lý';
    } else {
      // INGESTED
      s1 = 'passed'; s1Text = 'Đã duyệt';
      s2 = 'active'; s2Text = 'Đang xử lý';
    }
    
    let rejectionHtml = '';
    if (state === 'REJECTED' && reason) {
      const detailedReason = LEDGER_REASON_MAP[reason] || `Tầng 4 (Execution Engine) — Lỗi: ${reason}`;
      rejectionHtml = `<div class="ledger-rejection-info">🛑 ${detailedReason}</div>`;
    }

    return `
      <div class="ledger-card">
        <div class="ledger-card-header">
          <div class="ledger-card-title">
            <span class="ledger-symbol">${sig.symbol}</span>
            <span class="ledger-action ${actionClass}">${actionText}</span>
          </div>
          <div class="ledger-meta">
            <span>ID: <strong>#${sig.id}</strong></span>
            <span>Khung TG: <strong>${sig.mode || '60'}</strong></span>
            <span>Giá: <strong>$${sig.price ? sig.price.toLocaleString() : '—'}</strong></span>
            <span>Lúc: <strong>${sig.created_at}</strong></span>
          </div>
        </div>
        
        <div class="ledger-steps">
          <div class="ledger-step ${s1}">
            <span class="ledger-step-title">Tầng 1: Gatekeeper</span>
            <span class="ledger-step-status">${s1Text}</span>
          </div>
          <div class="ledger-step ${s2}">
            <span class="ledger-step-title">Tầng 2: Macro Filter</span>
            <span class="ledger-step-status">${s2Text}</span>
          </div>
          <div class="ledger-step ${s3}">
            <span class="ledger-step-title">Tầng 3: Strategy Filter</span>
            <span class="ledger-step-status">${s3Text}</span>
          </div>
          <div class="ledger-step ${s4}">
            <span class="ledger-step-title">Tầng 4: Execution</span>
            <span class="ledger-step-status">${s4Text}</span>
          </div>
        </div>
        
        ${rejectionHtml}
      </div>
    `;
  }).join('');
}

function updateLedgerPagination(total) {
  const prevBtn = document.getElementById('ledgerPrevBtn');
  const nextBtn = document.getElementById('ledgerNextBtn');
  const pageNum = document.getElementById('ledgerPageNum');
  
  if (!prevBtn || !nextBtn || !pageNum) return;
  
  const totalPages = Math.max(1, Math.ceil(total / LEDGER.limit));
  pageNum.textContent = `Trang ${LEDGER.page} / ${totalPages}`;
  
  prevBtn.disabled = LEDGER.page <= 1;
  nextBtn.disabled = LEDGER.page >= totalPages;
}

function ledgerPrevPage() {
  if (LEDGER.page > 1) {
    LEDGER.page--;
    loadLedgerSignals();
  }
}

function ledgerNextPage() {
  const totalPages = Math.ceil(LEDGER.total / LEDGER.limit);
  if (LEDGER.page < totalPages) {
    LEDGER.page++;
    loadLedgerSignals();
  }
}
