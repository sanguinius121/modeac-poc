# Phase Tool-3.6 — Diện tích vùng thu theo trạm

## Chức năng và ý nghĩa

Mỗi receiver card và Network Summary nay hiển thị:

- **Diện tích vùng thu** (`coverage_area_km2`);
- **Diện tích trong vùng giám sát** (`coverage_inside_surveillance_km2`);
- **Tỷ lệ bao phủ vùng giám sát** (`surveillance_coverage_percent`).

Mẫu số của tỷ lệ luôn là **toàn bộ diện tích polygon giám sát**:

```text
intersection(receiver coverage, surveillance) / surveillance area × 100%
```

Do đó đây không phải phần trăm vùng thu của receiver nằm trong polygon. Nếu chưa có polygon giám sát, hai trường intersection/percent là `null`; diện tích vùng thu của receiver vẫn có giá trị.

## Nguồn và phương pháp diện tích

- `simulated`: UI ghi **Vùng thu giả định**. Diện tích toàn phần dùng spherical geodesic cap với bán kính cấu hình `R`, không dùng `πR²` phẳng. Boundary 360 điểm chỉ phục vụ phép giao polygon.
- `outline`: UI ghi **Vùng thu quan sát từ readsb**. Diện tích dùng đúng ring `[latitude, longitude]` đã được parser Phase Tool-2 chuẩn hóa và kiểm tra. Không thay outline bằng convex hull hoặc vòng tròn.
- Polygon và intersection được đưa vào cùng phép chiếu Lambert azimuthal equal-area trên cầu bán kính `6371,0088 km`, rồi tính theo km². Polygon đơn được tam giác hóa và các tam giác được cắt giao; không đổi degree² bằng hệ số cố định.

`outline.json` vẫn chỉ là footprint thu quan sát được trong `actualRange.last24h.points`, phụ thuộc traffic, altitude, antenna và thời gian quan sát. Diện tích outline không phải diện tích RF bảo đảm.

## API

`POST /api/coverage-areas` nhận `receivers` và `surveillance_polygon` tùy chọn, trả:

```json
{
  "surveillance_area_km2": 92692.227,
  "receivers": [{
    "receiver_id": "rx-t37",
    "receiver_name": "T37",
    "reception_model": "simulated",
    "source_label_vi": "Vùng thu giả định",
    "coverage_area_km2": 384748.321,
    "coverage_inside_surveillance_km2": 92688.489,
    "surveillance_coverage_percent": 99.996
  }],
  "area_method": "spherical_lambert_azimuthal_equal_area",
  "coordinate_order": "latitude,longitude"
}
```

`POST /api/analyze` giữ schema cũ và chỉ bổ sung `receiver_coverage`; cùng danh sách cũng được gắn vào `summary.receiver_coverage`. Geometry engine, reception eligibility, ranking best/worst, N-1 và 4-of-N không đọc các trường diện tích này.

## Giới hạn

- Mô hình cầu là phù hợp với quy mô vùng hiện tại nhưng không phải geodesy ellipsoid cadastral.
- Vòng tròn giao polygon được rời rạc hóa 360 điểm; số rất sát 0%/100% có thể có sai khác nhỏ do biên.
- Chỉ ring đơn hiện được Phase Tool-2 sinh ra; holes/multipolygon và antimeridian vẫn không được hỗ trợ.
- Không tính network union, vùng common 4+, terrain, radio horizon, probability hoặc optimizer.

Chạy planner như trước:

```bash
cd /home/mlatserver/modeac-poc
python3 -m deployment_planner --host 0.0.0.0 --port 8095
```

