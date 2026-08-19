# Phase Tool-1 — Acceptance Report

Ngày nghiệm thu: 2026-08-11 (Asia/Ho_Chi_Minh)

## Kết luận

**PASS cho phạm vi MVP Phase Tool-1.** Planner chạy manual trên cổng 8095, tái sử dụng metric hiện hữu, hỗ trợ arbitrary N trong data model nhưng chỉ tính đúng bốn receiver được chọn thủ công. Không có production service/config nào bị sửa hoặc restart.

## File tạo/sửa

- Tạo package `deployment_planner/` gồm entry point, backend, frontend và ảnh nghiệm thu.
- Tạo `tests/test_deployment_planner.py`.
- Tạo tài liệu này và `docs/mlat-deployment-planner-phase1.md`.
- Không sửa `realtime/`, production tar1090 overlay, service unit hay receiver forwarding.

Frontend dùng Leaflet/Leaflet Draw và Canvas circle-marker layer. Backend dùng `ThreadingHTTPServer`, REST JSON và import trực tiếp geometry core hiện hữu. Port 8095 đã được kiểm tra trống trước khi chạy.

## Automated tests

Lệnh:

```bash
python3 -m unittest discover -s tests -v
```

Kết quả cuối: **40/40 PASS**. Toàn bộ 24 test hiện hữu (realtime, unified frontend và tar1090 overlay) tiếp tục PASS; 16 test/contract mới của planner cũng PASS. Các nhóm kiểm tra mới bao gồm validation, reception gate, polygon grid, hull/condition/P95/class, linear branch safety, outside-hull/close-pair, `NO_MLAT`, JSON finite, arbitrary N/manual 4RX, HTTP API, current-network regression và frontend controls.

## Current-network regression

Preset dùng đúng:

| Receiver | Latitude | Longitude | Altitude |
|---|---:|---:|---:|
| T37 | 21.485594 | 107.773191 | 60 m |
| QK4 | 18.760032 | 105.659087 | 20 m |
| CaiChien | 21.320940 | 107.766116 | 28 m |
| BachLongVi | 20.132285 | 107.724413 | 28 m |

Trên các điểm đại diện của polygon thiết kế, condition và Monte Carlo P95 của API được so trực tiếp với `tools.receiver_geometry_analysis.geometry_metrics` dùng cùng seed/draws:

- condition khớp tới 12 chữ số thập phân;
- predicted P95 khớp tới 9 chữ số thập phân;
- receiver count/range gate và classification dùng đúng cùng semantics/ngưỡng.

Ví dụ baseline grid 10 km: 928 điểm; GOOD 222, ACCEPTABLE 181, POOR 39, VERY_POOR 11, NO_MLAT 475; median predicted P95 trên điểm có MLAT là 518,08 m.

## Hiệu năng

Đo trực tiếp cùng polygon thiết kế, altitude 2500 m, noise 0,25 µs, 256 Monte Carlo draws:

| Grid | Points | Engine | Wall |
|---:|---:|---:|---:|
| 20 km | 232 | 0,163 s | 0,163 s |
| 10 km | 928 | 0,285 s | 0,285 s |
| 5 km | 3.709 | 1,064 s | 1,065 s |

Grid mặc định 10 km đủ nhanh để dùng tương tác trên vùng hiện tại. Browser không chạy Monte Carlo; chỉ đợi fetch và render kết quả.

## Nghiệm thu giao diện và logic tương tác

Firefox headless đã tải trang thật từ `http://127.0.0.1:8095/`; bốn receiver editor/marker, polygon, coverage circles, control Leaflet Draw và legend hiển thị đúng. Ảnh: `deployment_planner/acceptance/planner-initial.png`.

Các event handler/contract được kiểm tra tự động cho add, drag-end, sửa name/lat/lon/altitude/range, enable/delete, coverage toggle, rectangle/polygon, stale state, Analyze, ba visualization mode, popup detail, summary và import/export.

Phép A/B xác nhận thay đổi vị trí đi vào engine: chuyển T37 từ preset sang `21.0, 109.0` làm 231/928 grid point đổi quality; median P95 đổi từ 518,08 m thành 275,48 m. Thay range của một selected receiver xuống 1 km làm toàn bộ vùng test thành `NO_MLAT`.

`outline` đã được gọi qua API và trả HTTP 501 rõ ràng; không có partial parser.

## Production status

Trong lúc nghiệm thu:

- `readsb`: active;
- `mlat-server`: active;
- `tar1090`: active;
- `lighttpd`: active;
- ports 30004 và 30104: LISTEN;
- Beast ports 29996–29999: LISTEN;
- unified PoC backend 8090: LISTEN.

`socat-beast.service` được quan sát là inactive trước/sau kiểm tra; planner không điều khiển hay thay đổi service này. Không dùng `sudo`, `systemctl start/stop/restart`, không sửa production config.

## Known limitations

- Coverage chỉ là bán kính mặt đất mô phỏng, không phải cam kết RF.
- Chỉ selected strict 4RX; chưa có 4-of-N.
- Không có outline, optimizer, ADS-B truth, readsb/tar1090 integration.
- Leaflet assets hiện lấy từ CDN.
- Manual runtime, không systemd/autostart.
- Nên refactor geometry source of truth thành package trung lập trước Phase Tool-2; hiện planner import trực tiếp module tool cũ để đảm bảo kết quả giống tuyệt đối.
