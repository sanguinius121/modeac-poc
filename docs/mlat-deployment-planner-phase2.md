# MLAT Deployment Planner — Phase Tool-2

## Phạm vi và isolation

Phase Tool-2 thêm reception gate từ file readsb `outline.json` do người dùng upload thủ công. Tool vẫn chạy độc lập trên port 8095 và không đọc/ghi cấu hình production, không fetch station URL, không SSH, không đổi forwarding, không tích hợp readsb/tar1090 và không tự chọn 4-of-N.

Observed outline chỉ là lịch sử vị trí aircraft mà readsb đã quan sát được. Nó chịu ảnh hưởng traffic, thời gian quan sát, altitude và điều kiện thu; không phải ranh giới propagation bảo đảm.

## Geometry core refactor

Toán dùng chung đã được chuyển sang package trung lập `geometry_core/`:

- `coordinates.py`: WGS84/ECEF và local East/North;
- `distance.py`: haversine ground distance;
- `geometry.py`: horizontal TDOA Jacobian, singular values, condition và Monte Carlo error;
- `hull.py`: convex hull diagnostic;
- `monte_carlo.py`: remote branch separation;
- `quality.py`: ngưỡng GOOD/ACCEPTABLE/POOR/VERY POOR.

`tools/receiver_geometry_analysis.py` chỉ import core; hai offline tool layout/optimizer tiếp tục dùng cùng implementation qua module này. Planner import trực tiếp `geometry_core`. Fixture số trước/sau refactor có SHA256 giống tuyệt đối: `2d08948f1ecf76017912afc92f9727c2a8131519fff1a5ec618a6fc1226f10c7`.

## Schema readsb đã xác minh

Đã inspect file production đang được `/usr/bin/readsb --write-json /run/readsb --range-outline-hours 24` tạo:

```text
/run/readsb/outline.json
└── actualRange
    └── last24h
        └── points
            ├── [latitude, longitude, third_value]
            └── ...
```

File ngày nghiệm thu có 360 point. Cách hiểu tọa độ được xác minh trực tiếp bằng tar1090 source đang cài:

```javascript
const lat = points[p][k][0];
const lon = points[p][k][1];
ol.proj.fromLonLat([lon, lat]);
```

Do đó normalized representation của planner là `[lat, lon]`. Phần tử thứ ba không được tar1090 cài đặt dùng để vẽ polygon; planner chỉ ghi nhận range dưới tên trung tính `third_value` và không dùng nó cho eligibility hay geometry.

Schema path duy nhất Phase Tool-2 chấp nhận là `actualRange.last24h.points`. Không có station/source position trong hai file thật đã inspect, nên planner không invent origin và không phát cảnh báo mismatch. `last24h` cùng `readsb --help`/tham số production xác nhận cửa sổ observed 24 giờ.

Fixture test `tests/fixtures/readsb-outline-real-sanitized.json` là bản sanitized lấy mỗi point thứ sáu, giữ nguyên thứ tự azimuth và giá trị thực từ `/run/readsb/outline.json` ngày 2026-08-11.

## Reception provider architecture

```text
geometry engine
    |
    +-- SimulatedProvider.prepare/evaluate
    |       ground_distance <= max_range_km
    |
    `-- OutlineStore.prepare/evaluate
            point inside normalized observed polygon
```

Parser/storage nằm trong `deployment_planner/reception/outline.py`; geometry engine không biết schema JSON. Provider chuẩn bị eligibility cho toàn grid. Outline point-in-polygon được vector hóa bằng NumPy và boundary-inclusive.

Target/receiver altitude vẫn đi vào geometry core. Outline gate là footprint ngang và không được scale theo target altitude. Outline mode cũng không áp thêm `max_range_km`; range trong receiver chỉ dùng cho comparison circle tùy chọn.

Với arbitrary N, Receiver Count đếm mọi receiver enabled theo provider riêng. Geometry vẫn dùng đúng bốn receiver người dùng chọn. Nếu một selected receiver unavailable, điểm là `NO_MLAT` dù receiver thứ năm đang eligible.

## Upload và storage

API:

- `POST /api/outlines`: multipart field `file`;
- `GET /api/outlines`: danh sách metadata;
- `GET /api/outlines/{outline_id}`: resource và normalized rings;
- `DELETE /api/outlines/{outline_id}`: xóa resource;
- `POST /api/analyze`: tương thích Phase 1, receiver có thể là `simulated` hoặc `outline`.

Upload được lưu dưới `deployment_planner/runtime/outlines/outline-*/` gồm byte `original.json` và `normalized.json`. Runtime hiện có persistence qua restart, nhưng vẫn được xem là project runtime, không phải database/back-up. Giới hạn:

- file JSON: 2 MiB;
- 10.000 point/resource;
- 64 resource/runtime;
- unique UUID-based ID, không overwrite theo filename.

Validation từ chối JSON/schema sai, NaN/inf, coordinate ngoài miền, record malformed, dưới ba point riêng biệt, self-intersection, longitude wrap chưa hỗ trợ và request quá lớn. Adjacent duplicate/repeated closing point được normalize bỏ đi.

Khi UI xóa outline đang tham chiếu, mọi receiver dùng ID đó được reset deterministic về `simulated`. Config cũ bên ngoài UI giữ dangling ID sẽ bị `/api/analyze` từ chối và nêu đúng tên receiver.

## Workflow frontend

Mỗi receiver có:

- reception model `Simulated radius` hoặc `Observed readsb outline`;
- upload/replace/remove outline;
- trạng thái Uploading → Parsing → Valid/error;
- filename, point count, observed period, upload time, maximum outline distance tính từ receiver đang cấu hình;
- show/hide reception area riêng;
- optional simulated comparison circle khi ở outline mode.

Global **Show all reception areas**/**Hide all reception areas** điều khiển overlay. Outline dùng bảng màu receiver-specific xanh lam/tím/cyan/cam, không dùng màu quality. Popup grid hiển thị `inside/outside observed readsb outline` hoặc khoảng cách/radius simulated, cùng cảnh báo selected strict-4 không substitution.

Analyze bị disable nếu outline của receiver enabled đang upload, invalid hoặc missing. Export chỉ lưu `outline_id`/filename/source; không embed raw JSON. Khi import sau khi runtime resource mất, người dùng phải re-upload.

## Khởi động

```bash
cd /home/mlatserver/modeac-poc
python3 -m deployment_planner --host 0.0.0.0 --port 8095
```

Mở `http://100.100.24.4:8095/`; dừng bằng `Ctrl-C`. Không có systemd/autostart.

## Hiệu năng

Polygon thiết kế, 360-point outline thật, 256 Monte Carlo draws:

| Case | 20 km | 10 km | 5 km |
|---|---:|---:|---:|
| 4 outline | 0,135 s | 0,490 s | 1,638 s |
| 3 outline + 1 simulated | 0,123 s | 0,439 s | 1,625 s |

10 km vẫn đủ nhanh để tương tác. Việc cache theo unique outline ID còn tránh kiểm tra lại khi nhiều receiver dùng cùng một resource trong benchmark; với bốn outline khác nhau, mỗi polygon vẫn được vector hóa riêng.

## Giới hạn và Phase Tool-2.5

- Server chỉ có một outline production của readsb trung tâm, không có bốn file riêng T37/QK4/CaiChien/BLV; chưa thể kết luận RF station-by-station.
- Không hỗ trợ holes/multipolygon, antimeridian wrap hoặc self-intersecting rings.
- Không có altitude-specific outline gate.
- Runtime ID có persistence best-effort nhưng export không self-contained.
- Chưa có 4-of-N; selected strict-4 là cố định.
- `outline_source` dành sẵn `upload`; giá trị `automatic` bị từ chối rõ ràng. Tool-2.5 nên thêm một fetch service riêng có allowlist, timeout, size limit, refresh metadata và atomic replacement; không đưa network I/O vào geometry provider.

