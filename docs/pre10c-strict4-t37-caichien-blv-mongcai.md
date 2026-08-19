# Pre-Test strict-4 T37 + Cái Chiên + Bạch Long Vĩ + Móng Cái

## Phạm vi

Tài liệu này mô tả profile chẩn đoán trước Phase 10C. Profile chỉ dùng đúng bốn receiver:

| Receiver | Cổng | Vĩ độ | Kinh độ | Cao độ |
|---|---:|---:|---:|---:|
| T37 | 29996 | 21.485594 | 107.773191 | 60 m |
| Dao_Cai_chien | 29998 | 21.320940 | 107.766116 | 28 m |
| BachLongVi | 29999 | 20.132285 | 107.724413 | 28 m |
| MongCai | 29995 | 21.550206 | 107.938978 | 36 m |

QK3 và QK4 không được bind, không tham gia association và không đi vào solver. Task không triển khai 4-of-N, không enumerate subset và không bắt đầu Phase 10C.

## Kiến trúc thay đổi

`realtime/pre10c_config.py` khai báo profile cố định và T37 là clock reference. `realtime/pre10c_strict4.py` kích hoạt profile trước khi import backend. Cách này giữ nguyên `realtime/config.py`, quartet mặc định và service unit hiện hữu.

`realtime/localization.py` có thêm `configure_solver_geometry()`. Hàm chỉ thay bộ tọa độ, thứ tự receiver, sáu pair, origin và multi-start tương ứng trong module solver Test 7C. Objective least-squares, weighted residual, altitude grid, clustering branch và các ngưỡng `BLIND_UNIQUE`/`BLIND_MULTIPLE`/`BLIND_INCONSISTENT` không đổi.

Run chẩn đoán solve DF0/4/5/11/16/20/21; DF17 chỉ được solve khi chỉ định `--publish-df17-mlat`. Đây là mở rộng riêng để đo DF16 và hậu kiểm DF17. API `/api/modes/stats` thêm trường tương thích ngược `solver_by_df`; backend ghi `modes_solver_result` cho mọi classification cùng measurement time và publication age.

Lệnh chạy thủ công:

```bash
cd /home/mlatserver/modeac-poc
python3 -m realtime.pre10c_strict4 --duration 260 --publish-df17-mlat
```

Không có service production nào được sửa hoặc bật tự động bởi profile này.

## Files thay đổi

- sửa `realtime/main.py`;
- sửa `realtime/localization.py`;
- sửa `realtime/api.py`;
- thêm `realtime/pre10c_config.py`;
- thêm `realtime/pre10c_strict4.py`;
- thêm `tools/pre10c_truth_sampler.py`;
- thêm `tools/pre10c_analyze.py`;
- thêm `tests/test_pre10c_strict4.py`;
- tạo hai tài liệu Pre-Test.

Không sửa `realtime/config.py`, association implementation, tracker, Beast parser, clock fitting, Mode-S decoder, service unit hoặc tar1090 overlay. File overlay đang cài và source cùng SHA256 `e80b63229cf737270106e9d1a6aa243bae5672f2b8990f9b1bb94a92c136f573`.

Checkpoint trước sửa nằm tại `backups/pre10c-strict4-t37-20260819T092111Z/`. Baseline test trước sửa: 125/125 PASS.

## Semantics được giữ nguyên

- Beast Type 1/2/3 và timestamp correction hiện hữu được tái sử dụng.
- Clock calibration vẫn chỉ dựa trên DF17 và map về miền T37.
- Mode-S vẫn yêu cầu exact payload, physical gate, reciprocal nearest và uniqueness.
- Mode A/C vẫn coi raw code là candidate association, không phải aircraft identity.
- Solver vẫn blind; ADS-B truth chỉ được snapshot riêng để so sánh hậu kiểm.
- Mode-S track vẫn ICAO-associated; Mode A/C track vẫn anonymous.
- `last_seen` vẫn là measurement timestamp, không phải REST/WS receipt time.
- PoC vẫn xuất `MODES_MLAT_4RX` và `MODEAC_MLAT_4RX`, không inject Beast/readsb.

## Dữ liệu nghiệm thu

Artifacts nằm trong `acceptance/pre10c-t37-caichien-blv-mongcai/`:

- `backend-live.jsonl`: log run 260 giây;
- `performance-api.json`: resource/API samples;
- `browser-api.json`: trạng thái trang production tar1090 qua WebDriver BiDi;
- `df17-truth-snapshots.json`: ADS-B snapshots độc lập;
- `analysis.json`: thống kê log và DF17 hậu kiểm;
- `tar1090-live.png`: ảnh chụp tự động lúc trang còn loading, không được dùng làm bằng chứng visual acceptance.

Browser acceptance dựa trên DOM/runtime diagnostics trong `browser-api.json`, không dựa trên ảnh loading.

## Giới hạn đã phát hiện

Quartet có common reception và clock geometry tốt, nhưng backend hiện solve từng strict event trên altitude grid khá tốn CPU. Traffic strict-4 vượt khả năng solver. Mode-S có stale gate nên bỏ event cũ; Mode A/C chưa có stale gate tương đương nên tồn backlog rất lâu. Vì vậy profile hữu ích để chứng minh reception/clock/geometry, nhưng chưa phù hợp làm pipeline quan sát realtime liên tục ở toàn bộ yield hiện tại.

