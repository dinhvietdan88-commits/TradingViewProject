/**
 * Reports management module for Minervini SEPA Dashboard.
 * Custom implementation mapping backtest & optimization reports.
 */

// List of available reports
const AVAILABLE_REPORTS = [
  {
    id: 'supertrend_equity_curve',
    title: 'Supertrend Equity Curve',
    file: 'supertrend_equity_curve.html',
    icon: '📈',
    desc: 'Đường cong vốn tài khoản, hiệu suất chiến lược và mức sụt giảm tài sản (Drawdown) của Supertrend.'
  },
  {
    id: 'pattern_analysis',
    title: 'Pattern Analysis',
    file: 'pattern_analysis.html',
    icon: '🧠',
    desc: 'Phân tích thống kê tần suất, hiệu suất thắng và tỷ lệ R:R của các mô hình giá SEPA (VCP, Cup...).'
  },
  {
    id: 'monthly_pattern_analysis',
    title: 'Monthly Pattern Analysis',
    file: 'monthly_pattern_analysis.html',
    icon: '📅',
    desc: 'Thống kê phân bổ mô hình giá theo từng tháng giao dịch giúp tìm ra các chu kỳ thị trường tối ưu.'
  },
  {
    id: 'walkforward_validation',
    title: 'Walkforward Validation',
    file: 'walkforward_validation.html',
    icon: '🎯',
    desc: 'Kiểm chứng walkforward (WFO) đa chu kỳ ngoài mẫu thử, xác nhận độ tin cậy của tham số chỉ báo.'
  },
  {
    id: 'position_sizing',
    title: 'Position Sizing Analysis',
    file: 'position_sizing.html',
    icon: '⚖️',
    desc: 'Đánh giá quản lý rủi ro và tối ưu hóa tỷ lệ phân bổ vốn Kelly dựa trên thống kê chuỗi giao dịch.'
  },
  {
    id: 'walkforward_rolling',
    title: 'Walkforward Rolling Window',
    file: 'walkforward_rolling.html',
    icon: '🔄',
    desc: 'Kết quả Walkforward tối ưu hóa theo phương pháp cửa sổ cuốn chiếu (Rolling Window).'
  },
  {
    id: 'walkforward_3month',
    title: 'Walkforward 3-Month Cycle',
    file: 'walkforward_3month.html',
    icon: '📊',
    desc: 'Báo cáo tối ưu hóa chu kỳ ngắn hạn 3 tháng ngoài mẫu giúp phản ứng nhanh với thị trường.'
  },
  {
    id: 'trade_replay',
    title: 'Trade Replay & Simulation',
    file: 'trade_replay.html',
    icon: '🎥',
    desc: 'Trình phát và giả lập (Replay) lại diễn biến các lệnh giao dịch lịch sử từng cây nến.'
  }
];

let activeReportId = null;

// Initialize Reports Panel
function initReports() {
  const reportsList = document.getElementById('reportsList');
  if (!reportsList) return;

  // Build the list of reports
  reportsList.innerHTML = AVAILABLE_REPORTS.map(rep => `
    <div class="rep-card" id="rep-card-${rep.id}" onclick="selectReport('${rep.id}')">
      <div class="rep-card-icon">${rep.icon}</div>
      <div class="rep-card-info">
        <div class="rep-card-title">${rep.title}</div>
        <div class="rep-card-desc">${rep.desc}</div>
      </div>
    </div>
  `).join('');
}

// Select a report and load it in iframe
function selectReport(id) {
  const report = AVAILABLE_REPORTS.find(r => r.id === id);
  if (!report) return;

  activeReportId = id;

  // Update active class in sidebar
  document.querySelectorAll('.rep-card').forEach(card => card.classList.remove('active'));
  const activeCard = document.getElementById(`rep-card-${id}`);
  if (activeCard) activeCard.classList.add('active');

  // Update header metadata
  document.getElementById('repViewerIcon').textContent = report.icon;
  document.getElementById('repViewerTitle').textContent = report.title;
  document.getElementById('repViewerFile').textContent = report.file;

  const externalLink = document.getElementById('repExternalLink');
  const reportUrl = `/reports/${report.file}`;
  externalLink.href = reportUrl;

  // Show header and iframe, hide empty state
  document.getElementById('repViewerHeader').classList.remove('d-none');
  document.getElementById('repEmptyState').classList.add('d-none');

  const iframe = document.getElementById('repIframe');
  iframe.classList.remove('d-none');
  iframe.src = reportUrl;

  if (typeof showToast === 'function') {
    showToast(`Đang tải báo cáo: ${report.title}...`, 'info');
  }
}

// Refresh the current active report iframe
function refreshActiveReport() {
  if (!activeReportId) return;
  const iframe = document.getElementById('repIframe');
  if (iframe) {
    const currentSrc = iframe.src;
    iframe.src = '';
    // Force a reload by resetting the source
    setTimeout(() => {
      iframe.src = currentSrc;
      if (typeof showToast === 'function') {
        showToast('Đang tải lại báo cáo...', 'info');
      }
    }, 50);
  }
}

// Hook into switchTab
(function() {
  const _orig = window.switchTab;
  window.switchTab = function(tab) {
    // Call original switchTab
    _orig.apply(this, arguments);

    // If reports tab is clicked, initialize it
    if (tab === 'reports') {
      initReports();
    }
  };
})();
