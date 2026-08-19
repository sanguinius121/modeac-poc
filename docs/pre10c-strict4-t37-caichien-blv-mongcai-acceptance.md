# Acceptance — Pre-Test strict-4 T37 + Cái Chiên + Bạch Long Vĩ + Móng Cái

## Kết luận

**FAIL theo acceptance tổng thể.** Receiver, parser, clock, association, solver, REST/WS và tar1090 overlay đều hoạt động; nhưng tiêu chí không queue runaway/drop bất thường không đạt. Kết quả này không phủ định quartet: nó cho thấy quartet rất mạnh về common reception và clock, trong khi throughput của solver/pipeline hiện tại chưa theo kịp traffic.

Run chính kéo dài 260 giây, từ `2026-08-19T09:25:49Z` tới `09:30:10Z`, không vượt hard maximum 300 giây.

## Receiver và parser

Snapshot tại uptime khoảng 245–250 giây:

| Receiver | Connected | Frames | Type 1 | Type 2 | Type 3 | Parse errors | Reconnect |
|---|---|---:|---:|---:|---:|---:|---:|
| T37 | Có | 432349 | 264092 | 79612 | 88645 | 0 | 0 |
| Cái Chiên | Có | 203860 | 135141 | 34472 | 34247 | 0 | 0 |
| Bạch Long Vĩ | Có | 156941 | 105019 | 26683 | 25239 | 0 | 0 |
| Móng Cái | Có | 210938 | 151844 | 31748 | 27346 | 0 | 0 |

4/4 receiver ổn định. Frame queue bằng 0 ở snapshot, frame drop bằng 0.

## Clock

Tất cả sáu pair đạt `STRONG`, không rejected discontinuity và không model reset:

| Pair | Samples | P50 | P95 |
|---|---:|---:|---:|
| T37–Cái Chiên | 2000 | 0.0484 µs | 0.1433 µs |
| T37–Bạch Long Vĩ | 2000 | 0.0675 µs | 0.1903 µs |
| T37–Móng Cái | 2000 | 0.0488 µs | 0.1427 µs |
| Cái Chiên–Bạch Long Vĩ | 1807 | 0.0978 µs | 0.2674 µs |
| Cái Chiên–Móng Cái | 2000 | 0.1068 µs | 0.2737 µs |
| Bạch Long Vĩ–Móng Cái | 1368 | 0.0980 µs | 0.2769 µs |

T37 là common time domain, không phải tuyên bố clock vật lý của T37 tốt hơn tuyệt đối.

## Mode A/C

Snapshot được audit ở uptime 249.5 giây ghi:

- 1201 strict-4 cluster; log tiếp tục tới event ID 1245 trước khi dừng;
- 107 solver attempt = 88 `BLIND_UNIQUE` + 15 `BLIND_MULTIPLE` + 4 `BLIND_INCONSISTENT` tại snapshot;
- full-run log có thêm bốn unique đã publish, tổng `blind_unique` quan sát bằng log là 92;
- event queue high-water 200, near-final 199;
- ít nhất 894 event queue drop;
- latency arrival-to-publication P50 128.6 s, P95 213.4 s.

Các số strict đầy đủ cuối run không được snapshot sau stop; vì vậy 1245 là lower bound có chứng cứ từ event ID, còn bảng API 1201 là mốc nhất quán tại 249.5 giây. Không nội suy thành con số giả chính xác.

Anonymous tracking có update và overlay nhận Mode A/C event. Tuy nhiên backlog gây track stale, tạo nhiều track cùng code theo thời gian và một số tốc độ biểu kiến phi vật lý. Ở một snapshot giữa run, code `0706` xuất hiện ở nhiều anonymous track và có speed báo cáo tới khoảng 18.3 km/s. Đây là dấu hiệu pipeline/track timing không ổn định, không phải bằng chứng association identity vì raw code vốn không phải identity.

## Mode-S

Full log có 3856 strict-4 event đưa thành công vào queue. Last accepted event mang event ID 5395; phần chênh phản ánh queue-full drops, vì counter strict tăng trước `put_nowait`. Phân bố 3856 event đã enqueue:

| DF | Strict-4 enqueue | Solver attempts | UNIQUE | MULTIPLE | INCONSISTENT |
|---:|---:|---:|---:|---:|---:|
| 0 | 471 | 51 | 47 | 4 | 0 |
| 4 | 248 | 21 | 17 | 4 | 0 |
| 5 | 50 | 7 | 7 | 0 | 0 |
| 11 | 1103 | 107 | 100 | 7 | 0 |
| 16 | 38 | 2 | 2 | 0 | 0 |
| 17 | 1562 | 179 | 160 | 19 | 0 |
| 20 | 338 | 26 | 24 | 2 | 0 |
| 21 | 46 | 7 | 7 | 0 | 0 |
| **Tổng** | **3856** | **400** | **364** | **36** | **0** |

DF16 có strict-4 và có hai solver result `BLIND_UNIQUE`. Yield solver thấp hơn strict association không phải do đổi semantics, mà chủ yếu do queue cap và stale gate.

Snapshot uptime 250 giây:

- Mode-S strict counter 5181, sau đó log đạt event ID 5395;
- event queue high-water 64, near-final 61;
- ít nhất 1471 queue-full drop và 3261 stale drop;
- association latency P50/P95: 0.0456/0.0834 ms;
- solver latency P50/P95: 1848/2648 ms;
- end-to-end latency P50/P95: 4708/5688 ms.

Mode-S có một track/ICAO registry nên không thấy duplicate ID cùng ICAO trong frontend. Tuy nhiên một số update bị track gate reject hoặc có speed trên ngưỡng hàng không hợp lý do sai số vị trí/tolerance ở khoảng thời gian ngắn; do đó chưa thể gọi tracking hoàn toàn ổn định.

## DF17 truth hậu kiểm

Quy trình giữ blind-first: backend solve và ghi frozen latitude/longitude/measurement time; sampler riêng đọc `/run/readsb/aircraft.json`; analyzer chỉ ghép sau run. Truth không tham gia branch selection.

Với tolerance thời gian tối đa 2 giây, có 51 match. Time delta thực tế P50 khoảng 0.312 s, P95 khoảng 0.630 s, max 1.041 s. Horizontal error:

| Metric | Error |
|---|---:|
| P50 | 509 m |
| P90 | 1435 m |
| P95 | 2740 m |
| P99 | 6948 m |

P99 từ 51 mẫu rất nhạy với vài outlier, nên chỉ là diagnostic. Sai lệch thời gian còn đóng góp một phần lỗi theo chuyển động target. Không có sample nào sai gross trên 25 km; vì vậy không thấy obvious wrong-branch trong 51 match. Formal branch correctness không thể tính chính xác vì log frozen chỉ giữ selected branch, không lưu toàn bộ competing branches; không được tuyên bố 100% branch-correct.

## Tar1090 và timestamp semantics

Trong cửa sổ browser 45 giây:

- production plane collection: 139;
- layer `PoC Mode-S MLAT` và `PoC Mode A/C MLAT` tồn tại độc lập;
- status: Backend OK, Receivers 4/4, Clock 6/6 OK;
- cả hai WebSocket `LIVE`, reconnect 0;
- overlay nhận 133 Mode-S và 21 Mode A/C lifecycle event;
- maximum registry trong cửa sổ: 21 Mode-S, 1 Mode A/C;
- 0 REST error, 0 invalid track, 0 out-of-order drop, 0 browser console error.

Mode-S marker xuất hiện rõ (21 visible ở snapshot). Mode A/C có target trong status và event đã đến frontend; tại final DOM snapshot marker hiện tại bằng 0 vì measurement đã cũ hơn stale-remove 120 giây. Đây là hành vi đúng frontend policy nhưng cũng là hậu quả trực tiếp của backend backlog.

Frontend chứng minh age semantics đúng: event trễ hiển thị age tại receipt từ khoảng 30–121 giây cho Mode-S và 173–195 giây cho Mode A/C, không reset `Last seen` về 0 khi nhận REST/WS muộn.

Production index và overlay không bị sửa trong task; installed/source overlay cùng hash. `readsb`, `mlat-server`, `tar1090` vẫn active, restart count 0 và cổng 30004/30104 vẫn listen sau run. PoC không còn listen 8090/29995/29996/29998/29999 sau test.

## Performance

- Backend CPU: trung bình 305.4% của một core, peak 357.4% (bốn process gồm main + ba solver worker).
- RSS peak: 215.1 MiB.
- Mode A/C queue high-water 200; Mode-S high-water 64.
- Frame queue cuối/snapshot: 0; frame drop: 0.
- Parser error: 0; receiver reconnect: 0.
- Association rất nhanh; solver và scheduling/backpressure là bottleneck.

## Tests và regression

Baseline trước sửa: 125/125 PASS. Sau sửa: **135/135 PASS**, gồm 10 test mới cho quartet, cổng/toạ độ, loại QK3/QK4, reference T37, mapping Móng Cái, DF16, default-profile regression, solver geometry compatibility và additive API schema.

Không thay production RF data path, Beast forwarding, readsb, mlat-server, production aircraft state hay tar1090 source. Không inject/re-encode PoC position.

## Quyết định trước Phase 10C

Quartet này **đạt về receiver stability, common reception, clock và khả năng tạo vị trí**, nên là candidate strict-4 geometry tốt. Nhưng pipeline hiện tại **chưa đạt realtime acceptance** ở traffic quan sát: queue saturation, drops và Mode A/C age hàng phút là blocker. Chưa nên lấy cấu hình hiện tại làm baseline vận hành cho Phase 10C cho tới khi có một task riêng xử lý scheduling/backpressure/stale policy mà không làm đổi scientific semantics.

**Phase 10C không được bắt đầu.**
