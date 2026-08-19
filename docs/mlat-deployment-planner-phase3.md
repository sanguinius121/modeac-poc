# MLAT Deployment Planner — Phase Tool-3

## Phạm vi và kiến trúc

Phase Tool-3 chỉ mở rộng planner độc lập trên cổng 8095. Nó không sửa hoặc cung cấp dữ liệu cho `readsb`, `mlat-server`, realtime Mode A/C/Mode-S, Beast forwarding hay tar1090. Realtime backend hiện vẫn là fixed strict-4.

Luồng tính toán tại mỗi grid point:

1. provider Phase Tool-2 (`simulated` hoặc uploaded `outline`) quyết định receiver enabled nào thật sự eligible;
2. nếu có dưới 4 receiver thì `NO_MLAT`;
3. nếu có N≥4, engine liệt kê đầy đủ `C(N,4)`, không cắt bớt;
4. mỗi subset được tính bằng chính `geometry_core`: Jacobian ngang WGS84/ECEF, condition, Monte Carlo P95, remote TDOA branch separation và subset hull;
5. trả compact best/worst/count/robustness trên grid; bảng đầy đủ chỉ được tính/trả on-demand bởi `POST /api/analyze-point`.

Reception vẫn authoritative. Subset không bao giờ chứa receiver ngoài radius/outline. Geometry diagnostic của một subset được cache trong một analysis (stations, TDOA signatures, branch separation và hull); eligibility của provider cũng được prepare một lần cho cả grid. Monte Carlo dùng stream cố định theo `SHA256(seed:receiver_id)`, nên thêm receiver không làm đổi noise samples của receiver đã có.

## Strategy và ranking

`POST /api/analyze` nhận `geometry_strategy`:

- `strict_4` — bốn receiver trong `geometry_receiver_ids`, tương thích Phase 1/2;
- `best_4_of_n` — mặc định;
- `worst_4_of_n` — hiển thị subset xấu nhất;
- `full_n_diagnostic` — best-4 vẫn là primary, đồng thời tính generalized all-available-N condition/P95.

BEST dùng thứ tự minh bạch, không có hidden score:

1. branch-safe trước branch-unsafe (`separation >= 0.5 µs`, subset không collinear);
2. P95 thấp hơn;
3. condition thấp hơn;
4. inside subset hull trước outside hull;
5. tuple receiver ID lexical để tie-break deterministic.

WORST đảo ưu tiên chẩn đoán: branch-unsafe trước, sau đó P95 lớn hơn, condition lớn hơn, outside hull, cuối cùng ID lexical. Clock quality live không có trong planner nên không được giả lập hoặc đưa vào ranking. Mọi subset dùng nguyên quality thresholds của `geometry_core`.

Full-N dùng generalized centered Jacobian/covariance cho toàn bộ receiver available. Đây chỉ là **FULL-N GEOMETRY DIAGNOSTIC**, chưa phải production solve mode và không thay primary best-4. Nhiều receiver không đồng nghĩa strict-N luôn tối ưu về vận hành; planner dùng best subset và số alternative tốt để thể hiện điều đó.

## Robustness, leave-one-out và contribution

Mỗi point có `available_receiver_count`, `subset_count`, best/worst P95/condition/quality, số GOOD/ACCEPTABLE/POOR/VERY_POOR, `good_subset_fraction` và `n_minus_1_survivable`.

Định nghĩa N-1 GOOD survivability: với **mỗi** receiver currently available bị mất riêng lẻ, vẫn tồn tại ít nhất một 4RX subset còn lại có quality GOOD. Vì vậy N<5 luôn false. Với 5RX, năm subset chính là năm phép leave-one-out; bảng on-demand cho thấy receiver bị bỏ và metric tương ứng.

Receiver importance tại một point là:

```text
best P95 khi không dùng receiver / best P95 khi có toàn bộ candidate
```

Summary báo median/P90 ratio theo grid. Đây là diagnostic geometry contribution, không phải causal RF contribution hoặc clock score. Failure selector loại tạm một receiver khỏi analysis mà không sửa cấu hình saved/enabled.

## UI

Các heatmap: best quality, worst quality, receiver count, GOOD subset count, robustness fraction, N-1 survivability, receiver importance và primary predicted P95. Popup compact hiển thị reception từng receiver, best/worst, GOOD count và N-1; nút **Show all subsets** gọi `/api/analyze-point` và trả bảng sorted gồm P95, condition, branch safety, hull và quality.

`Active geometry set` được đổi nhãn thành **Strict-4 baseline**; bốn marker vẫn màu xanh lá và chỉ dùng cho strict regression/comparison. Best-4 là default. Cảnh báo planning-only luôn hiện ở mode 4-of-N.

## API guard và hiệu năng

API không hard-code 5/6/7 receiver. Nó tính chính xác `C(N,4)`. Nếu maximum subset/point >70, request phải xác nhận `allow_high_subset_count=true`; UI cho Continue/Cancel. Trên 1000 subset/point bị chặn cứng. Không silent truncation. Grid vẫn có giới hạn 25.000 point.

Endpoint:

```text
POST /api/analyze
POST /api/analyze-point   # body giữ nguyên config và thêm point: [lat, lon]
```

Grid compact không chứa mọi subset. Endpoint point hiện recompute analysis từ stateless configuration rồi chọn grid point khớp/gần nhất; click từ chính heatmap khớp chính xác. Đây là lựa chọn đơn giản, deterministic cho MVP, chưa có cross-request result cache.

Benchmark tái lập:

```bash
python3 -m tools.benchmark_planner_phase3 --n 6 --step 10
python3 -m tools.benchmark_planner_phase3 --synthetic 5
```

## Chạy và dừng

```bash
cd /home/mlatserver/modeac-poc
python3 -m deployment_planner --host 0.0.0.0 --port 8095
```

Mở `http://100.100.24.4:8095/`, dừng bằng `Ctrl-C`. Planner không có systemd/autostart. Outline vẫn chỉ upload thủ công; receiver offline nên Phase Tool-3 không implement automatic outline fetch.

## Giới hạn và chuẩn bị Tool-4/realtime tương lai

- RF radius của candidate chỉ là simulated horizontal reception, không phải khảo sát thực địa.
- `outline.json` là footprint aircraft đã quan sát, không đảm bảo RF mọi hướng và không scale theo target altitude.
- P95 là geometry/noise model, không bao gồm multipath, bias clock live hoặc atmospheric/model errors.
- Worst-4 cố ý nhạy với subset yếu; thêm receiver có thể làm worst xấu hơn dù best tốt hơn.
- API/data model đã arbitrary-N, deterministic và tách provider/geometry, đủ nền tảng để Tool-4 di chuyển candidate rồi re-run/compare. Realtime 4-of-N vẫn cần association, clock-state, scheduling, solver validation và soak riêng; không thể chỉ nối planner vào production.

