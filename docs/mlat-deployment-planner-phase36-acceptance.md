# Phase Tool-3.6 — Acceptance report

## Kết luận

**PASS** trong phạm vi tính và hiển thị diện tích vùng thu theo từng receiver. Không có thay đổi đối với geometry core, strict 4RX, 4-of-N, realtime pipeline hoặc production service.

## Kết quả đại diện

Với polygon mặc định hiện tại, phép equal-area trả diện tích vùng giám sát **92.692,227 km²**. Simulated radius 350 km trả **384.748,321 km²** cho mỗi receiver.

| Receiver | Nguồn | Vùng thu km² | Trong giám sát km² | Bao phủ giám sát |
|---|---|---:|---:|---:|
| T37 | giả định 350 km | 384.748,321 | 92.688,489 | 99,996% |
| QK4 | giả định 350 km | 384.748,321 | 45.303,493 | 48,875% |
| CaiChien | giả định 350 km | 384.748,321 | 92.689,141 | 99,997% |
| BachLongVi | giả định 350 km | 384.748,321 | 92.692,227 | 100,000% |

Các bất biến `0 ≤ intersection ≤ min(receiver area, surveillance area)` và `0 ≤ percent ≤ 100` đều đạt. Case mixed simulated + outline sanitized trả đúng hai nguồn riêng; không dùng max-range để thay diện tích outline.

## Test

```text
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 92 tests
OK
```

10 test Phase Tool-3.6 bao phủ: geodesic circle 350 km; outline polygon; thứ tự lat/lon; surveillance area; polygon intersection; đúng mẫu số percent; mixed receivers; no-polygon null; invalid outline giữ validation cũ; frontend/API contract.

API smoke test trên process tạm cổng 8096:

```text
GET  /api/health          → phase Tool-3.6
POST /api/coverage-areas  → 200, trường diện tích hữu hạn
GET  /app.js              → UI labels và endpoint mới có mặt
```

Process tạm đã dừng sau kiểm tra.

Planner manual trên cổng 8095 đã được khởi động lại riêng để nạp backend mới. Kiểm tra live sau restart:

```text
GET  http://127.0.0.1:8095/api/health          → phase Tool-3.6
POST http://127.0.0.1:8095/api/coverage-areas  → 200
readsb / mlat-server / tar1090                  → active / active / active
```

Live case một outline 336 điểm đã lưu trả source `outline`, diện tích vùng thu **523.285,517 km²**, giao polygon nhỏ **454,714 / 464,747 km²**, tương ứng **97,841%**. Kết quả hữu hạn và nằm trong cả hai diện tích đầu vào.

Planner vẫn là process manual, không có systemd/autostart mới.

## File thay đổi

- `deployment_planner/backend/coverage_area.py` — mới;
- `deployment_planner/backend/api.py`;
- `deployment_planner/frontend/app.js`;
- `deployment_planner/frontend/style.css`;
- `tests/test_deployment_planner_phase36.py` — mới;
- hai tài liệu Phase Tool-3.6 này — mới.

Các SHA256 `geometry_core/*.py` sau task giống baseline đã ghi trước khi sửa. Không file `geometry_core`, realtime, tar1090 overlay, production config hay service unit nào bị sửa.
