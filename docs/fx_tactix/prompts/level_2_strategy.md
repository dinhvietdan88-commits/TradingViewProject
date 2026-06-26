# Level 2 — Custom Strategy / Indicator Generator

> Prompt chính để Claude sinh Pine Script v5 từ mô tả tiếng Việt.

```
Bạn là Pine Script v5 expert. Sinh code đầy đủ, compile được trên TradingView, theo yêu cầu sau:

## MÔ TẢ STRATEGY
{{description}}

## RÀNG BUỘC
- Pine version: //@version=5
- Loại: {{strategy|indicator}}  (strategy = có entry/exit; indicator = chỉ plot)
- Risk management mặc định nếu là strategy:
  * Risk per trade: 2%
  * Stop-loss: 8% (hoặc theo mô tả)
  * Take-profit: 20% (R:R ≥ 2.5)
- Phải có:
  * Input parameters cho mọi magic number
  * Comment tiếng Việt giải thích logic chính
  * `plotshape` đánh dấu entry/exit
  * `alertcondition()` để dùng với webhook FastAPI
- KHÔNG dùng:
  * `request.security` lookahead=barmerge.lookahead_on (gây repaint)
  * Hàm deprecated của v4

## OUTPUT FORMAT
Trả về duy nhất 1 block code Pine v5 trong ```pinescript fences, KHÔNG kèm giải thích bên ngoài.
Tên strategy/indicator: snake_case, prefix "fx_" (ví dụ: fx_rsi_oversold_v1).
```

## Ví dụ sử dụng

Input `{{description}}`:
> Mua khi giá vượt EMA50 với volume > 2x trung bình 20 phiên, đóng vị thế khi RSI > 70 hoặc SL 8%.

Claude trả về Pine v5 code có thể paste thẳng vào Pine Editor.
