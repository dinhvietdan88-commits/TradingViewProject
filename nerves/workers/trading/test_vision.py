import asyncio
import os
import sys

# Load environment variables
from dotenv import load_dotenv

load_dotenv()

# Add the server directory to python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from vision import analyze_chart_vision  # noqa: E402


async def main():
    screenshot_path = r"C:\Users\pesil\working\mj_trading\TradingViewProject\tradingview-mcp\screenshots\tv_undefined_2026-05-12T03-28-20-091Z.png"

    # Fake signal data
    signal_data = {
        "symbol": "BTCUSDT",
        "action": "alert",
        "price": "Current",
        "timeframe": "4h",
        "strategy": "A.007 + MIS v1/v2 Combined",
    }

    # Override the default prompt for this specific deep behavioral analysis request
    import vision

    vision.VISION_USER_PROMPT = """
Sếp đang mở chart BTCUSDT khung 4H. Trên chart đang chạy 2 strategy:
- "A.007 + MIS v1 Combined (Auto Paper Trading)"
- "A.007 + MIS v2 Combined (Auto Paper Trading)"

Sếp yêu cầu: "sử dụng TradingView-MCP để xem các Forecasting Short position. Tôi cần anh trở thành chuyên gia phân tích sâu hành vi của tôi."

HÃY ĐÓNG VAI LÀ CHUYÊN GIA TÂM LÝ GIAO DỊCH VÀ PHÂN TÍCH KỸ THUẬT LÃO LUYỆN (SEPA/MINERVINI):
1. Quét biểu đồ và các chỉ báo (đặc biệt là 2 chiến lược A.007 + MIS trên) để tìm các dấu hiệu "Forecasting Short position" (dự báo điểm vào lệnh Short).
2. Phân tích sâu hành vi (Behavioral Analysis): Tại sao sếp lại muốn Short lúc này? Đang có dấu hiệu FOMO, chặn đầu xe lửa, hay đây là một Setup phá vỡ giả (Spring/Upthrust) đúng kỷ luật?
3. Cảnh báo rủi ro tâm lý và đưa ra lời khuyên cứng rắn.
4. Đưa ra Kế hoạch Giao dịch (Trading Plan) cho lệnh Short (nếu hợp lý), bao gồm: Entry, Stop Loss, Take Profit, R:R.
5. Cuối cùng, chấm điểm kỷ luật (0/10 đến 10/10).
"""
    print("Sending screenshot to Gemini Vision for deep behavioral analysis...")
    analysis = await analyze_chart_vision(screenshot_path, signal_data)
    import json

    with open("analysis_result.md", "w", encoding="utf-8") as f:
        f.write(json.dumps(analysis, indent=4, ensure_ascii=False))
    print("Analysis saved to analysis_result.md")


if __name__ == "__main__":
    asyncio.run(main())
