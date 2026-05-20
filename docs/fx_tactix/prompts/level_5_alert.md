# Level 5 — Alert + Bot Wiring

```
Cho Pine strategy sau:

```pinescript
{{pine_code}}
```

Hãy bổ sung:
1. `alertcondition()` cho mỗi entry/exit signal — message format JSON chuẩn cho FastAPI webhook của chúng tôi:
   ```json
   {
     "symbol": "{{ticker}}",
     "action": "buy|sell",
     "price": "{{close}}",
     "alert_type": "fx_tactix_v1",
     "timeframe": "{{interval}}",
     "secret": "INSERT_WEBHOOK_SECRET"
   }
   ```
2. Comment hướng dẫn user cách paste alert message vào TradingView Alert Dialog
3. Lưu ý risk: alert phải dùng "Once Per Bar Close" để tránh repaint

Trả về Pine v5 code đã bổ sung, kèm hướng dẫn 3 dòng bên dưới fence.
```
