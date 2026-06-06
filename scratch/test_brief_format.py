import sys
from datetime import datetime

# Force UTF-8 encoding for stdout
sys.stdout.reconfigure(encoding="utf-8")

# Add server/workers to path
sys.path.append(
    r"C:\Users\pesil\working\mj_trading\TradingViewProject\nerves\workers\trading"
)

from brief import _format_brief_text  # noqa: E402
from analysis import ScanResult, TrendTemplateResult, VCPResult  # noqa: E402


def main():
    # Mock scan results
    scan_results = [
        ScanResult(
            symbol="TAOUSDT",
            price=261.00,
            change_pct=-1.5,
            trend_template=TrendTemplateResult(3, {}, "Stage 1 (Base)", "Passed 3/8"),
            vcp=VCPResult(False, 0.96, 1.0, None, False, "No contraction"),
            volume=50000.0,
            volume_avg=52000.0,
            exchange="binance",
        ),
        ScanResult(
            symbol="BTCUSDT",
            price=73672.62,
            change_pct=0.5,
            trend_template=TrendTemplateResult(
                0, {}, "Stage 3/4 (Avoid)", "Passed 0/8"
            ),
            vcp=VCPResult(False, 1.55, 1.0, None, False, "High volume"),
            volume=1500.0,
            volume_avg=1000.0,
            exchange="binance",
        ),
        ScanResult(
            symbol="ETHUSDT",
            price=2014.13,
            change_pct=-0.2,
            trend_template=TrendTemplateResult(
                0, {}, "Stage 3/4 (Avoid)", "Passed 0/8"
            ),
            vcp=VCPResult(False, 1.38, 1.0, None, False, "Normal volume"),
            volume=12000.0,
            volume_avg=9000.0,
            exchange="binance",
        ),
        ScanResult(
            symbol="SOLUSDT",
            price=82.16,
            change_pct=-2.4,
            trend_template=TrendTemplateResult(
                0, {}, "Stage 3/4 (Avoid)", "Passed 0/8"
            ),
            vcp=VCPResult(False, 0.94, 1.0, None, False, "Low volume"),
            volume=85000.0,
            volume_avg=90000.0,
            exchange="binance",
        ),
        ScanResult(
            symbol="NVDA",
            price=0.0,
            change_pct=0.0,
            trend_template=TrendTemplateResult(0, {}, "Unknown", "Error"),
            vcp=VCPResult(False, 1.0, 1.0, None, False, "Error"),
            volume=0.0,
            volume_avg=None,
            exchange="binance",
            error="Failed to fetch candles for NVDA on binance after 5 attempts.",
        ),
    ]

    ai_analysis = "Kiến nghị: Không giao dịch tại thời điểm hiện tại. BTC và các Altcoin lớn đang nằm trong xu hướng giảm ngắn hạn dưới SMA50 và SMA200."
    timestamp = datetime.now()

    formatted = _format_brief_text(scan_results, ai_analysis, timestamp)
    print("--- FORMATTED TELEGRAM BRIEF ---")
    print(formatted)


if __name__ == "__main__":
    main()
