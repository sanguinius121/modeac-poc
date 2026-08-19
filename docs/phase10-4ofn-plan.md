# Phase 10 — Kế hoạch mở rộng realtime MLAT từ strict fixed-4 sang 4-of-N

## Phạm vi và nguyên tắc

Phase 10 mở rộng PoC Mode A/C và Mode-S từ bốn receiver cố định sang khả năng chọn một tập bốn receiver trong N receiver. Việc mở rộng phải tuần tự: đo reception trước, tổng quát hóa association, xác minh solver offline, so sánh khoa học, chạy shadow realtime, rồi mới quyết định promotion.

Các nguyên tắc xuyên suốt:

- không thay đổi production `readsb`, `mlat-server`, tar1090 hay Beast forwarding;
- không dùng truth để tác động ngược vào association hoặc solver;
- Mode A/C vẫn anonymous, Mode-S giữ quy tắc identity hiện tại;
- exact payload, clock-normalized time, physical propagation bound, ambiguity rejection và reciprocal-nearest không được nới;
- mỗi phase có artifact đóng băng, regression test và tiêu chí dừng riêng.

## Sáu sub-phase

### Phase 10A — 5RX capture, clock và common reception

Bind riêng năm Beast input, thêm MongCai vào công cụ chẩn đoán, xác minh parser/clock và đo reception funnel 2RX/3RX/any-4-of-5/strict-5. Thống kê năm subset 4RX, từng DF và so sánh với fixed-4 hiện tại. Không localization và không sửa realtime. Phase này đã được triển khai trong task hiện tại.

### Phase 10B — Association generic N-RX

Tổng quát hóa cấu trúc buffer và association để nhận N receiver, phát hiện một physical transmission một lần, biểu diễn các subset 4RX hợp lệ mà không đếm trùng. Phase này chỉ thay đổi association/state nội bộ; chưa tự động chọn subset thắng để publish vị trí.

Điều kiện vào: kết quả 10A đủ tin cậy, semantics fixed-4 có regression fixture, và chính sách observation ownership giữa các subset được thiết kế rõ.

### Phase 10C — Offline 4-of-N solver và DF17 truth validation

Cho từng event đã freeze, chạy solver trên các subset đủ điều kiện; đánh giá branch, residual, condition, clock quality và sai số hậu kiểm DF17. Xây dựng chính sách xếp hạng subset hoàn toàn offline, gồm tie-break xác định và xử lý khi các subset cho nghiệm không đồng thuận.

### Phase 10D — So sánh Mode A/C và Mode-S

So sánh fixed-4 với 4-of-N theo yield, classification `BLIND_UNIQUE`/`BLIND_MULTIPLE`/`BLIND_INCONSISTENT`, continuity, latency và chất lượng vị trí. Mode A/C và Mode-S phải được báo cáo riêng; không chuyển identity Mode-S sang track Mode A/C.

### Phase 10E — Realtime shadow mode và performance soak

Chạy 4-of-N song song ở chế độ shadow: tính nhưng không publish, không thay đổi track/API hiện hữu. Theo dõi queue, CPU/RSS, stale drops, duplicate event, clock degradation, subset switching và chênh lệch với fixed-4 trong soak có giới hạn.

### Phase 10F — Promotion decision và final acceptance

Đánh giá evidence của 10A–10E, quyết định promote, giữ shadow hay dừng. Nếu promote, cần feature flag/rollback, schema compatibility, production soak và acceptance riêng. Promotion không mặc nhiên xảy ra chỉ vì yield tăng.

## Ranh giới task hiện tại

Task hiện tại kết thúc ở Phase 10A. Không triển khai dynamic solver, subset winner, cross-subset consensus, N-1 realtime, truth-based selection hoặc promotion MongCai vào output production.

## Khuyến nghị kiến trúc sơ bộ cho Phase 10B

[IMPLEMENTATION] Các giả định fixed-4 hiện nằm ở:

- `realtime/config.py`: `STATIONS` và `ORDER` chỉ có bốn trạm;
- `realtime/clock_sync.py`: tạo pair từ `ORDER`, tham chiếu `T37`, và `ready()` yêu cầu toàn bộ ba link trực tiếp còn lại;
- `realtime/association.py`: `StrictAssociator` yêu cầu mọi phần tử `ORDER`, tạo đúng sáu TDOA và phát `STRICT_4RX`;
- `realtime/modes/realtime.py`: buffer chỉ hoàn tất khi mọi station trong `ORDER` có observation, sau đó xóa toàn bộ payload row;
- `realtime/localization.py` và `realtime/modes/localization.py`: `ORDER`/`PAIRS` là global fixed-4 và solver nhận đúng một tập bốn trạm;
- `realtime/main.py`, `state.py` và API diagnostics: tên counter/event, queue flow và log đều giả định một event strict-4 duy nhất.

Minimal refactor được khuyến nghị:

1. Tách topology receiver (`N`) khỏi `minimum_receivers=4`, nhưng giữ T37 là common time-domain trong bước đầu.
2. Tạo một association core generic chỉ trả về một transmission cùng tập observation hợp lệ/maximal; không để mỗi subset tự tiêu thụ observation độc lập trong realtime.
3. Biểu diễn rõ `available_stations`, `valid_subsets`, observation IDs và measurement timestamp trong event bất biến.
4. Tách subset enumeration/policy khỏi parser, clock và association; dùng tie-break deterministic.
5. Chưa sửa solver trong 10B. Adapter fixed-4 cũ tiếp tục lấy đúng baseline subset để regression bit-for-bit về event count/semantics.
6. Bổ sung bounded buffers/counters theo N và bảo vệ combinatorial growth trước khi bật shadow.

Rủi ro chính là đếm trùng cùng transmission qua nhiều subset, tái sử dụng observation, ambiguity khi raw Mode A/C lặp lại, xóa buffer quá sớm, chọn subset có clock unavailable, đổi measurement timestamp, và làm sai identity Mode-S. Các rủi ro solver/branch/subset winner thuộc 10C, không nên giải quyết lẫn trong 10B.
