# Phase 10A — Capture 5RX, clock và common-reception

## Mục tiêu

Phase 10A đo đóng góp reception của MongCai trước khi thay đổi association hoặc solver realtime. Công cụ là diagnostic/offline; không thêm MongCai vào `realtime/config.py`, không tạo vị trí, không tracking và không publish REST/WebSocket.

## Cấu hình receiver

| Receiver | Port | Latitude | Longitude | Altitude |
|---|---:|---:|---:|---:|
| MongCai | 29995 | 21.550206 | 107.938978 | 36 m |
| T37 | 29996 | 21.485594 | 107.773191 | 60 m |
| QK4 | 29997 | 18.760032 | 105.659087 | 20 m |
| Dao_Cai_chien | 29998 | 21.320940 | 107.766116 | 28 m |
| BachLongVi | 29999 | 20.132285 | 107.724413 | 28 m |

Các giá trị này chỉ nằm trong `tools/phase10a_common.py`; production topology bốn trạm không đổi.

## Công cụ

- `tools/phase10a_5rx.py`: listener đồng thời, capture CSV, health/performance metadata và offline analysis;
- `tools/phase10a_common.py`: topology diagnostic, clock calibration, generic exact-transmission clustering, subset enumeration và thống kê;
- `tests/test_phase10a.py`: 15 test tập trung vào Phase 10A.

Ví dụ chạy acceptance tối đa 600 giây:

```bash
cd /home/mlatserver/modeac-poc
python3 tools/phase10a_5rx.py run --duration 300
```

Phân tích lại một capture không cần bind cổng:

```bash
python3 tools/phase10a_5rx.py analyze test10a/<run-id>
```

`run` chờ tối đa 60 giây để đủ năm client, sau đó mới đếm duration yêu cầu. Mọi thống kê reception được cắt về giao của `first_recv_utc_ns` và `last_recv_utc_ns` trên cả năm receiver, tránh baseline bốn trạm có cửa sổ dài hơn MongCai.

## Beast capture

[IMPLEMENTATION] Parser dùng trực tiếp `realtime.beast.BeastParser` và `decode_frame`. Correction giữ nguyên:

- Type 1: trừ 244 tick;
- Type 2: trừ 768 tick;
- Type 3: trừ 768 tick;
- tick rate: 12 MHz.

Mỗi station có CSV tương thích format Test 6. Metadata ghi connection/reconnect, byte/frame, Type 1/2/3, timestamp zero, DF, parse error, queue high-water/final/drop, CPU/RSS và SHA256.

Queue chỉ phục vụ ghi capture, có giới hạn cấu hình; `put_nowait` và drop counter làm overload hiển thị rõ thay vì che giấu.

## Clock synchronization

[IMPLEMENTATION] Clock source duy nhất là common airborne-position DF17. Không dùng DF16 hay DF khác. Việc ghép DF17, CPR/altitude, geometric propagation correction và `Link` rolling regression được tái sử dụng từ code đã validate.

Với pair A→B, mô hình hiện hành có dạng:

```text
tick_B_clock ≈ slope × tick_A + offset
```

Mapping một timestamp B về T37:

```text
tick_T37 ≈ (tick_B - offset_T37,B) / slope_T37,B
```

Quality dùng nguyên threshold runtime:

- dưới 100 mẫu: `UNAVAILABLE`;
- P95 < 1 µs: `STRONG`;
- P95 < 5 µs: `PASS`;
- P95 < 10 µs: `MARGINAL`;
- còn lại: `BAD`.

Mười pair đều được báo cáo. Association 5RX chỉ cần bốn mapping trực tiếp T37→receiver còn lại; một pair phụ thiếu common DF17 không làm mất mapping nếu cả hai vẫn có link trực tiếp tốt với T37.

## Association diagnostic

[IMPLEMENTATION] Công cụ không gọi solver. Nó giữ các semantics sau:

1. payload/raw code phải bằng chính xác;
2. timestamp corrected được normalize về T37;
3. mọi pair được giữ phải nằm trong physical baseline propagation bound cộng margin hiện hành;
4. lựa chọn gần nhất phải reciprocal cho từng pair;
5. nếu hai candidate gần tương đương trong 6 tick thì reject ambiguity;
6. một observation không được dùng lại trong cùng một clustering pass;
7. thứ tự xử lý/tie-break xác định.

Margin giữ nguyên 10 µs cho Mode A/C và 3 µs cho Mode-S. Mode A/C raw-code và Mode-S payload được phân tích tách biệt.

## Ý nghĩa reception funnel

- `observations`: tổng frame hợp lệ ở tất cả receiver trong common window; đây không phải số transmission duy nhất;
- `2RX`, `3RX`, `4RX`, `5RX`: receiver distribution từ clustering đồng thời trên năm trạm;
- `any_4_of_5`: số physical transmission duy nhất có ít nhất một strict subset 4RX hợp lệ, deduplicate bằng observation IDs dùng chung;
- `strict_5RX`: cluster có đủ cả năm;
- `baseline_fixed_4RX`: strict subset T37+CaiChien+QK4+BachLongVi.

Mỗi trong năm subset được chạy với cùng exact/normalized/physical/reciprocal policy. Một event 5RX có thể làm tăng count của cả năm subset nhưng chỉ được tính một lần trong `any_4_of_5`.

## Artifacts

Trong `test10a/<run-id>/`:

- `captures/beast-<station>.csv`: raw capture đã correction timestamp;
- `logs/capture.jsonl`: lifecycle listener/client;
- `reports/capture-metadata.json`: receiver/performance/hash;
- `reports/clock-pairs.csv`: mười clock links;
- `reports/common-reception.csv`: funnel Mode A/C, all Mode-S và từng DF;
- `reports/subset-counts.csv`: năm subset theo family;
- `reports/phase10a-summary.json`: source chính cho machine-readable result;
- `reports/phase10a-report.txt`: tóm tắt text;
- `reports/fixed4-regression.json`: đối chiếu diagnostic với associator Mode-S hiện hành.

## Giới hạn diễn giải

[MEASURED] Count mô tả traffic và reception trong đúng cửa sổ capture, không phải xác suất lâu dài. Zero strict-5 không chứng minh strict-5 luôn bằng zero. Mức tăng any-4-of-5 là tăng common reception eligibility, không phải tăng localization yield/accuracy; Phase 10A chưa chạy solver.

[ENGINEERING INTERPRETATION] Subset có count lớn cho biết overlap reception mạnh trong thời điểm đo, nhưng chưa chứng minh geometry/clock/branch của subset đó tạo vị trí tốt. Các kết luận này thuộc 10C–10D.
