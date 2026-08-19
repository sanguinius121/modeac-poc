# Phase Tool-2 — Acceptance Report

Ngày: 2026-08-11, Asia/Ho_Chi_Minh

## Kết quả

**PASS trong phạm vi Phase Tool-2 manual upload.** Phase 1 simulated workflow, API và geometry thresholds được giữ nguyên; observed outline và mixed provider hoạt động; không implement auto-fetch, optimizer hay 4-of-N.

## File chính tạo/sửa

- Tạo `geometry_core/` và chuyển geometry implementation dùng chung vào package này.
- Sửa ba offline tools để giữ CLI trực tiếp và dùng common core.
- Tạo `deployment_planner/reception/` gồm provider base, simulated và outline store/parser.
- Mở rộng receiver model, geometry engine và API.
- Mở rộng `deployment_planner/frontend/` cho upload/overlay/mixed UX.
- Tạo fixture thật sanitized và `tests/test_deployment_planner_phase2.py`.
- Tạo hai tài liệu Phase Tool-2.

## Schema/fixture thực tế

- Live source: `/run/readsb/outline.json`, 9.408 byte và 360 point tại thời điểm inspect.
- Verified field: `actualRange.last24h.points`.
- Ordering: `[latitude, longitude, third_value]`, xác minh bằng installed tar1090 source và known station-area containment.
- Fixture sanitized: 60 point lấy từ chính file live, không phải rectangle synthetic.
- Known interior: `21.024587, 105.773481`; exterior: `0,0`.
- Third value không được dùng vì source tar1090 đã inspect không gán semantics cho nó.

## Regression/refactor

Representative WGS84/Jacobian/condition/P95/TDOA-signature hash trước và sau refactor đều là:

```text
2d08948f1ecf76017912afc92f9727c2a8131519fff1a5ec618a6fc1226f10c7
```

Offline `receiver_geometry_analysis.py` đã chạy tạo CSV/PNG/HTML/JSON sau refactor. Ba CLI import/`--help` bình thường. Hai full layout smoke run được chủ động dừng vì script cũ luôn chạy generic-area sweep đầy đủ; không có process thử nghiệm còn sót lại.

## Tests

Lệnh cuối:

```bash
python3 -m unittest discover -s tests -v
```

Kết quả: **57/57 PASS**. Test Phase 2 bao gồm real schema/order, normalization, point-in-polygon scalar/vector, malformed JSON/schema/coordinates, self-intersection, size limit, upload/get/list/delete, metadata, full-outline geometry regression, all-outline, mixed 3+1, half-region exclusion, arbitrary N count, strict selected-4/no substitution, missing ID và frontend lifecycle/contracts.

## API/browser acceptance

Live manual API workflow trên 8095:

- upload `/run/readsb/outline.json`: HTTP 201, valid, 360 points;
- mixed 3 outline + 1 simulated, grid 10 km: 928 points, analysis 0,623 s;
- invalid `not-json`: HTTP 422 với thông báo parse rõ ràng;
- delete resource: thành công, không dangling runtime resource;
- `/api/health`: `phase=Tool-2`.

Firefox headless tải frontend thật, Leaflet, Phase Tool-2 controls, caveat, show/hide global, analysis controls và assets không có HTTP error. Ảnh: `deployment_planner/acceptance/planner-phase2.png`. Event contracts xác nhận add/drag/edit, upload/replace/remove, model switch, outline overlay, comparison circle, show/hide, popup reason, summary và disabled Analyze lifecycle.

## Performance

Sau vectorized prepared point-in-polygon, 360-point real outline:

| Case | 20 km | 10 km | 5 km |
|---|---:|---:|---:|
| 4 outline | 0,135 s | 0,490 s | 1,638 s |
| 3 outline + 1 simulated | 0,123 s | 0,439 s | 1,625 s |

## Technical simulated-vs-outline comparison

Do chỉ có một outline production trung tâm, comparison sau **không phải đánh giá bốn station**; cùng outline được nhân cho bốn receiver để kiểm tra gate/summary:

| Gate @ 10 km | strict-4 common | GOOD | GOOD+ACCEPTABLE | NO MLAT | median / P90 P95 |
|---|---:|---:|---:|---:|---:|
| simulated 350 km | 48,815% | 23,922% | 43,427% | 51,185% | 518 / 1.603 m |
| duplicated observed outline | 100% | 25,862% | 66,487% | 0% | 1.060 / 4.320 m |

Observed outline bao phủ rộng hơn trong fixture này nên đưa thêm nhiều điểm geometry xấu vào population P95. Không được diễn giải khác biệt là RF performance của T37/QK4/CaiChien/BLV.

## Production isolation

Không chạy `sudo`, không sửa/restart production service, không đọc station qua mạng và không thay đổi forwarding. Kiểm tra cuối:

- `readsb`, `mlat-server`, `tar1090`, `lighttpd`: active;
- production ports 30004 và 30104: LISTEN;
- `socat-beast`: inactive cả baseline và cuối;
- ports 29996–29999 và PoC backend 8090 không lắng nghe cả baseline và cuối của task này;
- planner 8095 đã dừng sau acceptance;
- runtime outline test files: 0;
- không còn process benchmark/offline tool thử nghiệm.

## Known limitations

- Chưa có outline riêng cho bốn current receivers.
- No holes/multipolygon/longitude wrap/self-intersection acceptance.
- Horizontal observed footprint, không altitude scaling.
- Runtime storage không phải database/backup.
- Export config cần re-upload nếu resource ID không còn.
- Strict selected 4RX; không substitution hoặc best-4.
