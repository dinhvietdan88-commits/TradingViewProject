# 🚶 MIS v10 — Walk-forward stability test (4 quý)

**Symbol / TF**: BYBIT:BTCUSDT.P · 60m
**Equity ban đầu mỗi quý**: 1,000 USDT (isolated, không compound giữa các quý)
**Strategy**: v10 baseline tham số gốc (TP=3·ATR, SL=2·ATR, no cooldown, no trail, allow long+short)
**Method**: gate `in_window = time >= start_dt and time < end_dt` chặn entry ngoài window; `close_all` cuối window để đóng position mở.
**Ngày test**: 2026-05-09

---

## 1. Kết quả 4 quý

| Quý | Range | Total P&L | % | MDD | Trades | WR | PF | Verdict |
|---|---|---|---|---|---|---|---|---|
| **Q1** | 2025-01-01 → 2025-04-30 | **−21.29** | −2.13% | 50.06 (5.01%) | 16 | 31.25% (5/16) | 0.628 | ❌ Lỗ |
| **Q2** | 2025-05-01 → 2025-08-31 | **−7.69** | −0.77% | 12.65 (1.26%) | 14 | 42.86% (6/14) | 0.635 | ❌ Lỗ |
| **Q3** | 2025-09-01 → 2025-12-31 | **+5.99** | +0.60% | 16.40 (1.64%) | 13 | 38.46% (5/13) | 1.294 | ⚠️ Sát hoà |
| **Q4** | 2026-01-01 → 2026-05-09 | **+21.25** | +2.12% | 16.45 (1.63%) | 17 | 58.82% (10/17) | 1.595 | ✅ Lãi |
| **Σ isolated** | — | **−1.74** | −0.17% | — | 60 | 41.67% (26/60) | — | Hoà |
| **v10 full-period** (so sánh) | 2025-01 → 2026-05 | **+146.71** | +14.47% | 96.82 (9.17%) | 87 | 70.11% (61/87) | 1.695 | 🏆 |

---

## 2. Phát hiện lớn: v10 KHÔNG robust quarter-by-quarter

### 2.1. Phân phối lợi nhuận cực lệch
- 3/4 quý hoà hoặc lỗ. Chỉ 1 quý (Q4) thực sự có lãi đáng kể.
- Tổng 4 quý isolated = **−1.74 USDT** (gần như hoà), trong khi full-period báo +146.71. Discrepancy ~+148 USDT.
- WR trung bình 4 quý = **41.67%**, không phải 70% như full-period.

### 2.2. Sự khác biệt giữa "isolated WF" và "full-period"

Có 3 nguồn gây discrepancy:

1. **Carry-over trades**: trong full-period, lệnh entry tháng 12/2024 nhưng exit trong Jan 2025 vẫn được tính P&L vào range hiển thị. WF isolated Q1 không bắt được những trade đó (entry trước Jan 1 2025 bị `in_window=false` chặn).
2. **Compound sizing**: trong full-period, equity grow từ 1000 → 1146 trong 16 tháng. Position size = 2% equity → lệnh ở Q4 dùng vốn lớn hơn Q1. Isolated WF reset equity = 1000 mỗi quý → mất hiệu ứng tích luỹ.
3. **Forced exit ở boundary**: `close_all` cuối mỗi quý cắt lệnh đang mở (có thể đang lãi MFE chưa đạt TP) → biased về phía lỗ. Full-period không có cut này.

### 2.3. Tuy nhiên, ngay cả khi điều chỉnh discrepancy, kết quả vẫn yếu

- Trade-count trung bình 4 quý = 15 lệnh. Tổng 60 lệnh isolated. Nếu thêm ~27 trades carry-over có thể ra 87 — nhưng **carry-over thực tế hiếm khi đem về +148 USDT** trong 16 tháng cho strategy 1H.
- Khả năng cao: **full-period +146.71 USDT là kết quả của một số ít lệnh fat-tail kéo dài** (một-hai trade lớn mỗi cụm) thay vì hiệu suất đều đặn.
- **WR full-period 70%** nhiều khả năng cũng được "kéo lên" bởi compound sizing — các quý sau có nhiều lệnh hơn (vì equity lớn hơn → 2% lớn hơn → vốn vẫn đủ để vào tiếp các signal nhỏ) và những lệnh đó hit TP=3·ATR sớm.

---

## 3. Phân tích regime BTC từng quý

| Quý | Regime BTC | v10 phù hợp? |
|---|---|---|
| Q1 2025 (Jan-Apr) | **Sideways → mini-bear** (sau peak Q4 2024) | ❌ MACD whipsaw nhiều; PF 0.628 |
| Q2 2025 (May-Aug) | **Range** | ❌ EMA stack đan; PF 0.635 |
| Q3 2025 (Sep-Dec) | **Bullish chậm** | ⚠️ Vài trend tốt; PF 1.294 |
| Q4 2026 (Jan-May) | **Bull rồi pullback** | ✅ Lệnh long bắt được trend; PF 1.595 |

→ **v10 chỉ hoạt động trong regime trend rõ rệt** (Q4). Trong sideways/chop (Q1, Q2), nó rò rỉ alpha qua MACD whipsaw — đúng như giả thuyết ban đầu trong báo cáo phân tích lần đầu.

---

## 4. Đính chính lần thứ hai cho báo cáo trước

Trong báo cáo [MIS_v10_subexperiments_AB.md](MIS_v10_subexperiments_AB.md) trước, em kết luận "v10 đã near-optimal cho khung BTC 1H 2025-2026". Walk-forward cho thấy:

- **Phán đoán đó chỉ đúng ở mức full-period aggregate**.
- Khi tách quarter-by-quarter, v10 không vượt break-even ở 3/4 windows.
- Full-period +146.71 là **kết quả của Q4 + carry-over + compound** chứ không phải sức mạnh đều đặn.

→ Khả năng **overfit** với Q4 BTC bull regime. Forward performance ngoài 2026-05 có thể tiêu cực.

---

## 5. Hệ luỵ thiết kế

### 5.1. v10 không đủ tin cậy cho live trading nếu không có regime filter

Vì hiệu suất phụ thuộc nặng vào regime trend, cần:
- **Trend Template gate** (TT 8 SMA của Minervini) hoặc tương đương để chỉ kích hoạt khi BTC ở Stage 2 confirmed.
- **ADX filter** (e.g., ADX > 25) hoặc **EMA200 slope filter** để chặn entry trong sideways.
- Đây chính là motivation của nhóm B (port v1.5/v1.6).

### 5.2. Kết quả Q1 −21.29 và Q2 −7.69 là cảnh báo nghiêm trọng

- BTC trong nửa đầu 2025 không có downtrend cấu trúc dài. Sideways thuần.
- Strategy vẫn entry MACD-cross-up khi EMA stack tạm xếp tầng → bị whipsaw.
- Cộng dồn 8 tháng đầu 2025: −28.98 USDT trên equity 1000 = **−2.9% drawdown từ chop alone**.

### 5.3. Việc tăng tần suất KHÔNG tự cải thiện expectancy

- Tổng 60 lệnh isolated, WR 41.67%, gần break-even.
- Group A sub-experiments trước đó (e.g., A1 nâng TP) cũng không cứu khi xét quarter-by-quarter — chỉ đẩy WR xuống thấp hơn nữa.

---

## 6. Đề xuất hướng đi tiếp theo

### 6.1. (Mạnh) Chuyển hẳn nhóm B với regime filter
Port logic v1.5/v1.6 sang `pine/v1/strategy_multi_indicator_v12B.pine`:
1. **TT gate (8 SMA criteria)** — chỉ entry khi BTC ở Stage 2.
2. **VCP dry-up gate** — institutional accumulation signal.
3. **Stage 2 freshness** — bắt first-leg, tránh late-stage entry.
4. **Risk-based position sizing** — `qty = (equity·1%)/sl_distance` thay vì 2% flat.
5. **Hard SL cap 8%** — safety khi ATR phình.

Sau đó chạy lại WF 4 quý để confirm robustness.

### 6.2. (Trung) Thêm regime filter đơn giản vào v10
Giữ kiến trúc v10, thêm 1-2 filter:
- **ADX > 25** trên 1H để chặn chop.
- **EMA200 slope > 0 trong N bars** để confirm trend hướng.

Test xem có nâng PF của Q1, Q2 lên trên 1.0 không.

### 6.3. (Yếu) Test trên timeframe khác
4H có thể giảm whipsaw và tăng tỷ lệ winning regime, nhưng giảm số mẫu mạnh.

---

## 7. Quyết định cần từ anh

1. **Triển khai 6.1 (nhóm B v12B với TT gate + VCP)?** Em fork file mới, port logic v1.5/v1.6, chạy WF 4 quý → so sánh.
2. **Hay 6.2 (thêm ADX/slope filter giữ kiến trúc v10)?** Nhanh hơn, chỉ thêm 1-2 lines Pine.
3. **Hay test 6.3 (4H timeframe)** trước khi quyết upgrade?

---

## 8. Raw data

| Quý | Source dates | Total P&L | Trades | WR | PF | MDD |
|---|---|---|---|---|---|---|
| Q1 | 2025-01-01 → 2025-05-01 | −21.29 | 16 | 31.25% | 0.628 | 50.06 |
| Q2 | 2025-05-01 → 2025-09-01 | −7.69 | 14 | 42.86% | 0.635 | 12.65 |
| Q3 | 2025-09-01 → 2026-01-01 | +5.99 | 13 | 38.46% | 1.294 | 16.40 |
| Q4 | 2026-01-01 → 2026-05-10 | +21.25 | 17 | 58.82% | 1.595 | 16.45 |

Pine source mỗi quý: v10 logic gốc + `in_window = time >= start_dt and time < end_dt` gate trên entries; `close_all` khi `not in_window`. File source không lưu vào repo (chỉ inject editor) — replay lại bằng cách đổi `start_dt` / `end_dt` trong template.

---

**Files**:
- [pine/v1/strategy_multi_indicator_v10.pine](../../pine/v1/strategy_multi_indicator_v10.pine) — baseline
- [docs/reports/MIS_v10_subexperiments_AB.md](MIS_v10_subexperiments_AB.md) — sub-experiments trước
- [docs/reports/MIS_v10_vs_v11A_AB_comparison.md](MIS_v10_vs_v11A_AB_comparison.md) — A/B v10 vs v11A
