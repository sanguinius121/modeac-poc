# MLAT Deployment Planner — Phase Tool-1

## Phạm vi

Đây là công cụ web độc lập để thử bố trí receiver và quan sát coverage/geometry 2D MLAT. Tool không đọc Beast, không dùng ADS-B truth và không sửa hay gọi vào realtime solver, `readsb`, `mlat-server`, `tar1090`, `lighttpd` hoặc forwarding hiện hữu.

Phase Tool-1 chỉ có reception model hình tròn mô phỏng và một tập geometry gồm đúng bốn receiver do người dùng chọn. Không có `outline.json`, tự chọn best 4-of-N, optimizer, database hoặc tích hợp production.

## Kiến trúc

```text
Browser (Leaflet + Leaflet Draw)
       |
       | GET /api/preset, POST /api/analyze
       v
stdlib ThreadingHTTPServer :8095
       |
       +-- validation/data model arbitrary N
       +-- horizontal ground-range gate
       +-- surveillance polygon grid
       +-- strict manually selected 4RX geometry
       `-- tools.receiver_geometry_analysis (math source of truth)
```

Backend dùng Python standard library cho HTTP, NumPy/SciPy có sẵn trong project cho toán. Frontend là HTML/CSS/JavaScript thuần. Leaflet 1.9.4 và Leaflet Draw 1.0.4 được tải từ unpkg; vì vậy browser cần truy cập CDN ở lần tải trang. Không có systemd unit.

Các file chính:

- `deployment_planner/backend/models.py`: parse và validate receiver/request;
- `deployment_planner/backend/coverage.py`: khoảng cách great-circle theo mặt đất và reception gate;
- `deployment_planner/backend/geometry_engine.py`: polygon grid, strict 4RX, hull, Monte Carlo, branch diagnostic và summary;
- `deployment_planner/backend/api.py`: static server và REST API;
- `deployment_planner/frontend/`: Leaflet UI;
- `tests/test_deployment_planner.py`: regression, geometry, API và frontend contracts.

## Khởi động và dừng

Từ project:

```bash
cd /home/mlatserver/modeac-poc
python3 -m deployment_planner --host 0.0.0.0 --port 8095
```

Mở `http://100.100.24.4:8095/` từ máy truy cập được server. Dừng bằng `Ctrl-C` trong terminal chạy tool. Tool không tự khởi động cùng máy.

Health check:

```bash
curl http://127.0.0.1:8095/api/health
```

## Cách dùng

1. Chọn **Load Current Network** hoặc thêm receiver bằng **Add Receiver** rồi click bản đồ.
2. Kéo marker hoặc sửa tên, latitude, longitude, altitude, max range và trạng thái enabled ở sidebar.
3. Chọn đúng bốn receiver enabled trong **Active geometry set**. Data model vẫn lưu được arbitrary N; tool tuyệt đối không âm thầm chọn best-4.
4. Vẽ rectangle/polygon bằng control trên bản đồ. UI hiển thị diện tích xấp xỉ, bounding box và maximum span.
5. Chọn target altitude, timing noise, grid 20/10/5 km và nhấn **Analyze**.
6. Chuyển giữa **Geometry Quality**, **Receiver Count** và **Predicted P95 Error**. Click một ô để xem reception của từng receiver và metric geometry.
7. Dùng **Clear analysis results** để xóa heatmap và network summary cũ mà không xóa receiver hoặc surveillance area.

Mọi thay đổi cấu hình chỉ cập nhật marker/circle tại chỗ và đánh dấu kết quả cũ là stale. Simulation chỉ chạy lại khi nhấn **Analyze**, nên kéo marker không gây vòng Monte Carlo liên tục. Coverage circle dùng đường viền 2 px, opacity 0,8 và lớp fill 0,075 để nhìn rõ hơn nhưng không che heatmap.

## Data model và API

Receiver có `id`, `name`, `lat`, `lon`, `altitude_m`, `reception_model`, `max_range_km`, `enabled`. Trường `reception_model` đã dành cho `simulated`/`outline`, nhưng `outline` chủ động trả HTTP 501 `Not implemented in Phase Tool-1`.

Endpoints:

- `GET /api/health`;
- `GET /api/preset`;
- `POST /api/analyze` với `receivers`, `surveillance_polygon`, `target_altitude_m`, `timing_noise_us`, `grid_step_km`, `geometry_receiver_ids`.

Giới hạn hiện tại là 25.000 grid point ở backend. Frontend cảnh báo khi ước lượng vượt 12.000 điểm. Có export/import cấu hình JSON trong browser, không lưu server-side.

## Semantics coverage

Reception dùng khoảng cách great-circle **nằm ngang trên mặt đất** từ grid point đến receiver:

```text
receivable = ground_distance_km <= receiver.max_range_km
```

Altitude receiver và target không tham gia gate RF hình tròn, nhưng đều đi vào WGS84/ECEF geometry solver. Coverage circle chỉ mô tả eligibility, không mô tả chất lượng geometry.

`receiver_count` là số receiver enabled nằm trong range. Geometry chỉ chạy nếu cả bốn receiver được chọn đều receivable. Với arbitrary N, dù bốn receiver khác đang thu được, một receiver thuộc selected 4RX bị out-of-range vẫn cho `NO_MLAT`; đây là strict manual subset, không phải 4-of-N.

## Geometry metrics

Planner gọi trực tiếp logic đã kiểm chứng trong `tools/receiver_geometry_analysis.py`:

- WGS84 geodetic-to-ECEF và local East/North axes;
- horizontal TDOA Jacobian với common-time projection;
- singular values và condition number;
- horizontal error Monte Carlo ở timing noise đã chọn;
- convex hull của bốn receiver;
- remote TDOA-signature branch separation, bỏ các điểm gần hơn 25 km.

Monte Carlo dùng 256 draw/point và seed cố định `20260811` để kết quả tái lập. Receiver thẳng hàng hoặc metric không hữu hạn được đánh dấu branch-unsafe/`VERY_POOR`; JSON trả `null` cho metric không xác định thay vì giả lập một số hữu hạn.

Ngưỡng được reuse nguyên trạng:

| Class | Điều kiện |
|---|---|
| GOOD | P95 ≤ 500 m, condition ≤ 10, branch separation ≥ 1.0 µs |
| ACCEPTABLE | P95 ≤ 1500 m, condition ≤ 30, separation ≥ 0.5 µs |
| POOR | P95 ≤ 5000 m, condition ≤ 100, separation ≥ 0.2 µs |
| VERY POOR | Các trường hợp geometry còn lại khi selected 4RX đều thu được |
| NO MLAT | Ít nhất một receiver trong selected 4RX ngoài simulated range |

Màu xám luôn có nghĩa thiếu common reception của selected 4RX, không phải geometry kém.

## Giới hạn và hướng Phase Tool-2

- Range tròn không phải propagation/terrain/antenna model thực tế.
- Frontend cần CDN để tải Leaflet; nên vendor asset nội bộ nếu cần vận hành offline.
- Chỉ strict manually-selected 4RX; chưa có 4-of-N.
- Polygon grid dùng local equirectangular projection để lấy mẫu/ước lượng diện tích; solver bên trong vẫn dùng WGS84/ECEF.
- Branch search chính xác theo nearest TDOA signature trên chính grid đã chọn; resolution có thể ảnh hưởng separation.
- Không có worker/job queue; một HTTP request chạy một analysis đồng bộ trong server thread.

Trước Phase Tool-2 nên tách phần toán hiện nằm trong script `tools/receiver_geometry_analysis.py` thành module `geometry_core` trung lập rồi để cả tool offline và planner import module đó. Phase Tool-2 có thể thêm provider `outline` sau reception interface hiện tại, nhưng không nên gộp parser outline vào geometry engine.
