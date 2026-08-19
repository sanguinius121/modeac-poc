# Phase 10A — Acceptance report 5RX common reception

## Kết luận

**PASS.** Năm receiver kết nối ổn định; Beast parse không lỗi; MongCai có direct clock mapping về T37 ở mức `STRONG`; queue bounded và không drop; thống kê 4-of-5/subset hoàn tất; production code không đổi và fixed-4 Mode-S đối chiếu khớp tuyệt đối.

Phase 10B chưa được triển khai.

## Run và common analysis window

- Run: `test10a/20260818T011249Z`
- Listener start: 2026-08-18 01:12:49.600 UTC
- MongCai reconnect/backoff warm-up: 44,803 s
- Common 5RX window: 01:13:34.412416–01:18:34.291218 UTC
- Common duration: **299,878801516 s**
- Tổng lifetime process capture kể cả warm-up: 344,998 s
- Capture dài dưới hard maximum 600 s.

Một run trước tại `test10a/20260818T010651Z` bị reject do Queue được tạo ngoài event loop trên Python 3.8; không dùng dữ liệu đó cho kết luận. Sau khi sửa lifecycle, smoke test chứng minh queue final=0/drop=0 rồi acceptance được chạy lại từ đầu.

## Receiver health

Số frame dưới đây là raw capture, gồm warm-up đối với các receiver kết nối trước MongCai. Reception/clock table ở các phần sau chỉ dùng common 5RX window.

| Receiver | Frames | Type 1 | Type 2 | Type 3 | Timestamp zero | Parse errors | Connect/reconnect |
|---|---:|---:|---:|---:|---:|---:|---:|
| T37 | 663.885 | 485.279 | 95.634 | 82.972 | 8 | 0 | 1 / 0 |
| Dao_Cai_chien | 307.522 | 229.210 | 43.927 | 34.385 | 8 | 0 | 1 / 0 |
| QK4 | 55.560 | 33.545 | 8.896 | 13.119 | 11 | 0 | 1 / 0 |
| BachLongVi | 222.252 | 155.138 | 38.966 | 28.148 | 8 | 0 | 1 / 0 |
| MongCai | 235.822 | 174.006 | 33.266 | 28.550 | 8 | 0 | 1 / 0 |

Năm disconnect cuối log là đóng listener có chủ đích sau duration, không phải reconnect/instability giữa run.

## Clock quality — 10 pair

| Pair | Geometry samples | Retained | P50 (µs) | P95 (µs) | Quality |
|---|---:|---:|---:|---:|---|
| T37–CaiChien | 4.401 | 2.000 | 0,056 | 0,159 | STRONG |
| T37–QK4 | 243 | 243 | 0,319 | 0,715 | STRONG |
| T37–BachLongVi | 1.706 | 1.706 | 0,204 | 0,472 | STRONG |
| **T37–MongCai** | **1.250** | **1.250** | **0,087** | **0,251** | **STRONG** |
| CaiChien–QK4 | 13 | 13 | — | — | UNAVAILABLE |
| CaiChien–BachLongVi | 740 | 740 | 0,052 | 0,159 | STRONG |
| CaiChien–MongCai | 673 | 673 | 0,051 | 0,158 | STRONG |
| QK4–BachLongVi | 205 | 205 | 0,146 | 0,368 | STRONG |
| QK4–MongCai | 0 | 0 | — | — | UNAVAILABLE |
| BachLongVi–MongCai | 221 | 221 | 0,089 | 0,222 | STRONG |

Kết quả: **8/10 STRONG, 0 PASS/MARGINAL/BAD, 2 UNAVAILABLE**. Hai link unavailable do thiếu common decoded airborne-position DF17 trong cửa sổ, không phải residual xấu. Bốn direct link từ T37 đều STRONG, vì vậy MongCai và toàn bộ receiver có usable mapping vào T37 time domain.

## Reception funnel

Các cột `4RX` và `5RX` là distribution từ full-five clustering; `any4` được deduplicate từ năm strict subset. Do xử lý ambiguity độc lập theo subset, `any4` có thể lớn hơn riêng cột full-cluster `4RX` một lượng nhỏ.

| Family | Observations | 2RX | 3RX | full-cluster 4RX | 5RX | any 4-of-5 | Baseline fixed-4 | Increase |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Mode A/C | 955.386 | 125.588 | 21.054 | 740 | 0 | **748** | 0 | +748 / n/a |
| All Mode-S | 365.971 | 60.226 | 23.728 | 3.766 | 0 | **3.766** | 35 | +3.731 / +10.660,0% |
| DF0 | 48.487 | 9.117 | 3.155 | 330 | 0 | 330 | 2 | +328 / +16.400,0% |
| DF4 | 17.814 | 3.171 | 1.399 | 197 | 0 | 197 | 1 | +196 / +19.600,0% |
| DF5 | 4.206 | 676 | 232 | 31 | 0 | 31 | 0 | +31 / n/a |
| DF11 | 127.915 | 18.967 | 8.587 | 1.943 | 0 | 1.943 | 16 | +1.927 / +12.043,75% |
| DF16 | 3.949 | 749 | 158 | 6 | 0 | **6** | 0 | +6 / n/a |
| DF17 | 107.884 | 18.342 | 7.518 | 1.032 | 0 | 1.032 | 13 | +1.019 / +7.838,46% |
| DF20 | 47.868 | 7.989 | 2.410 | 202 | 0 | 202 | 2 | +200 / +10.000,0% |
| DF21 | 7.847 | 1.215 | 269 | 25 | 0 | 25 | 1 | +24 / +2.400,0% |

Một DF18 observation cũng xuất hiện nhưng không tạo common cluster; nó được giữ trong machine-readable report thay vì mở rộng scope.

## Năm subset 4RX

| Subset | Mode A/C | All Mode-S | DF16 |
|---|---:|---:|---:|
| T37+CaiChien+QK4+BachLongVi (baseline) | 0 | 35 | 0 |
| T37+CaiChien+QK4+MongCai | 0 | 1 | 0 |
| **T37+CaiChien+BachLongVi+MongCai** | **748** | **3.730** | **6** |
| T37+QK4+BachLongVi+MongCai | 0 | 0 | 0 |
| CaiChien+QK4+BachLongVi+MongCai | 0 | 0 | 0 |

[MEASURED] Subset không có QK4 chiếm gần toàn bộ gain trong capture này. Đây là evidence về common reception tại thời điểm đo, chưa phải evidence rằng subset đó cho localization tốt nhất.

## DF16 với MongCai

- Total observations trong common window: **3.949** (T37 1.964, CaiChien 889, QK4 45, BachLongVi 431, MongCai 620).
- Receiver distribution trong common window: 2RX **749**, 3RX **158**, 4RX **6**, 5RX **0**.
- Any 4-of-5: **6**.
- Subset thấy cả sáu event: **T37+CaiChien+BachLongVi+MongCai**.
- Baseline fixed-4 và bốn subset khác: 0.

[MEASURED] Câu trả lời cho câu hỏi Phase 10A là **có**, DF16 tạo sáu common cluster 4-of-5 khi MongCai tham gia. Không suy rộng kết quả này thành utility lâu dài hay localization success.

## Performance và integrity

| Metric | Result |
|---|---:|
| CPU average | 30,43% của một logical CPU |
| CPU sampled peak | 99,04% |
| RSS peak | 51.864 KiB (~50,6 MiB) |
| Queue configured max | 100.000 |
| Queue high-water | 25.799 (25,8%) |
| Queue final | 0 |
| Queue drops | 0 |
| Parser errors | 0 ở cả 5 receiver |
| Reconnect trong acceptance | 0 |

Peak CPU ngắn xuất hiện khi ghi CSV tốc độ cao; không kèm queue runaway, drop, reconnect hay parser error. Đây là performance của capture diagnostic, không phải benchmark solver realtime.

## Regression và production safety

- 107/107 test PASS: 92 test hiện hữu + 15 test Phase 10A.
- SHA256 của mọi file trong `realtime/` khớp baseline trước task.
- Đối chiếu `realtime.modes.association.cluster_transmissions` trên cùng common window/baseline subset khớp chính xác: all Mode-S 35; DF0/4/5/11/16/17/20/21 lần lượt 2/1/0/16/0/13/2/1.
- `readsb`, `mlat-server`, `tar1090` vẫn active khi kiểm tra baseline; PoC realtime inactive theo chủ ý để nhường năm input cho capture.
- Không sửa forwarding, production port, API, tracker, solver hoặc output.

## Acceptance criteria

| Tiêu chí | Kết quả |
|---|---|
| 5/5 receiver connect ổn định | PASS |
| Beast parse | PASS |
| Parser error nghiêm trọng | PASS — zero |
| Queue không runaway | PASS — 25,8%, final zero, no drop |
| MongCai usable clock hoặc limitation rõ | PASS — direct T37 link STRONG |
| 4-of-5 statistics đúng/đủ | PASS |
| Baseline fixed-4 không đổi | PASS — source hash + exact Mode-S regression |
| Receiver/subset contribution rõ | PASS |

## Giới hạn và bước tiếp theo

- Hai clock pair phụ với QK4 chưa đủ sample; cần quan sát ở capture khác nếu muốn full pair diagnostics tốt hơn.
- Không có strict-5 trong cửa sổ này, chủ yếu phù hợp với reception overlap thấp của QK4; không kết luận strict-5 luôn bằng zero.
- Yield gain chưa qua solver/DF17 truth validation. Không dùng count này để promote realtime.
- Kiến trúc 10B chỉ được khuyến nghị trong `docs/phase10-4ofn-plan.md`; task này không triển khai 10B.
