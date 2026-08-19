# Pipeline PoC MLAT Mode A/C và Mode-S từ Beast đến vị trí, tracking và API

## 1. Mục đích, phạm vi và quy ước bằng chứng

Tài liệu này mô tả pipeline realtime hiện có trong project:

```text
/home/mlatserver/modeac-poc
```

Phạm vi bắt đầu tại các luồng Beast do hệ thống receiver/readsb chuyển tới bốn cổng TCP của PoC, đi qua parser, hiệu chỉnh timestamp, đồng bộ clock, association, tạo TDOA, solver, tracking và kết thúc tại REST/WebSocket. Tài liệu không mô tả Deployment Planner như một phần của runtime và không coi tar1090/frontend là nguồn quyết định vị trí.

Ba nhãn bằng chứng được dùng xuyên suốt:

- **[IMPLEMENTATION]**: hành vi được xác minh trực tiếp trong source code hiện tại.
- **[MEASURED]**: kết quả đã đo hoặc đóng băng trong test/acceptance report của project; chỉ đại diện dataset hoặc thời gian chạy được nêu.
- **[ENGINEERING INTERPRETATION]**: diễn giải vật lý/kỹ thuật từ implementation và số đo; không phải cam kết accuracy hoặc chuẩn an toàn hàng không.

Các source chính đã đối chiếu:

- [`realtime/beast.py`](../realtime/beast.py), [`receiver.py`](../realtime/receiver.py), [`config.py`](../realtime/config.py);
- [`clock_sync.py`](../realtime/clock_sync.py), [`association.py`](../realtime/association.py);
- [`localization.py`](../realtime/localization.py), [`tracker.py`](../realtime/tracker.py), [`modeac.py`](../realtime/modeac.py);
- [`realtime/modes/`](../realtime/modes/): decoder, association, localization và tracker Mode-S;
- [`main.py`](../realtime/main.py), [`state.py`](../realtime/state.py), [`api.py`](../realtime/api.py);
- solver gốc [`tools/test7c-2d-solver.py`](../tools/test7c-2d-solver.py);
- test contract [`tests/test_realtime.py`](../tests/test_realtime.py);
- các acceptance/frozen report Phase 1, 8A, 8B, 8C, 9 và 10 trong `docs/`.

## 2. Tóm tắt kiến trúc end-to-end

```text
Receiver + readsb/forwarder tại 4 site
              │
              │ Beast binary TCP
              ▼
  29996 T37        29997 QK4
  29998 Cái Chiên  29999 Bạch Long Vĩ
              │
              ▼
     Parser Beast dùng chung
     Type 1 / Type 2 / Type 3
              │
              ├───────────────────────────────────────┐
              │                                       │
              ▼                                       ▼
  Type 3 DF17 clock calibration              Phân luồng theo kind
  + CPR position để bỏ propagation                     │
              │                         ┌───────────────┴───────────────┐
              ▼                         ▼                               ▼
  6 clock-link linear models     Mode A/C Type 1                Mode-S Type 2/3
  normalize về miền T37          exact raw code                 decode DF/ICAO/meta
              │                  strict reciprocal 4RX          exact payload 4RX
              └──────────────┬──────────────┬───────────────────────────┘
                             ▼              ▼
                       6 TDOA/strict event cho mỗi pipeline
                                      │
                                      ▼
                    2D multi-start tại từng altitude hypothesis
                    branch family clustering + weighted residual
                                      │
                         ┌────────────┼────────────┐
                         ▼            ▼            ▼
                   BLIND_UNIQUE  BLIND_MULTIPLE  BLIND_INCONSISTENT
                         │
                         ▼
               Mode A/C anonymous tracker     Mode-S ICAO-keyed tracker
                         │                              │
                         ▼                              ▼
             /api/modeac/*, /ws/modeac      /api/modes/*, /ws/modes
```

**[IMPLEMENTATION]** Clock synchronization, association, solver và tracking đều nằm trong backend. Frontend/tar1090 chỉ tiêu thụ output; chúng không được phép phản hồi vị trí, identity hoặc lựa chọn branch về backend.

## 3. Bốn receiver và biên hệ thống

### 3.1 Mapping cố định

| Tên trong runtime | Cổng Beast | Latitude | Longitude | Antenna altitude |
|---|---:|---:|---:|---:|
| T37 | 29996 | 21,485594 | 107,773191 | 60 m |
| QK4 | 29997 | 18,760032 | 105,659087 | 20 m |
| Dao_Cai_chien | 29998 | 21,320940 | 107,766116 | 28 m |
| BachLongVi | 29999 | 20,132285 | 107,724413 | 28 m |

**[IMPLEMENTATION]** `ReceiverServer` mở bốn listener TCP trên server. Backend không chủ động kết nối tới client và không chạy receiver process tại client. Khi có kết nối mới cho cùng một station, socket cũ được đóng; trạng thái reconnect và địa chỉ peer được ghi lại.

**[IMPLEMENTATION]** Các cổng production 30004/30104 không thuộc pipeline này. Backend không tạo Beast vị trí, không inject vào readsb và không gửi tới mlat-server.

### 3.2 Thứ tự station dùng trong toán

Runtime dùng thứ tự cố định:

```text
T37 → Dao_Cai_chien → QK4 → BachLongVi
```

Thứ tự này xác định canonical pair, reference trong solver và cách tạo sáu cặp TDOA. Nó không phải thứ tự chất lượng RF.

## 4. Beast binary ingest

### 4.1 Ba loại frame

| Beast type byte | Tên logic | Body sau type | Payload RF | Dùng chính |
|---:|---|---:|---:|---|
| `0x31` | Type 1 / `modeac` | 9 byte | 2 byte | Mode A/C replies |
| `0x32` | Type 2 / `modes_short` | 14 byte | 7 byte | Mode-S short, 56 bit |
| `0x33` | Type 3 / `modes_long` | 21 byte | 14 byte | Mode-S long, 112 bit; DF17 clock |

Body gồm:

```text
6 byte timestamp + 1 byte signal + payload RF
```

**[IMPLEMENTATION]** Parser tìm marker `0x1A`, xử lý escape Beast `0x1A 0x1A`, chịu được frame bị chia giữa nhiều TCP chunk và có cơ chế resynchronize/count parse error khi gặp byte không hợp lệ.

### 4.2 Timestamp 12 MHz

Timestamp Beast là số nguyên 48 bit big-endian. Runtime dùng:

```text
BEAST_HZ = 12.000.000 tick/s
1 tick   = 1/12.000.000 s ≈ 83,333 ns
12 tick  = 1 µs
```

Timestamp dùng cho TDOA là timestamp hardware đã hiệu chỉnh, không phải thời điểm TCP packet tới server.

### 4.3 Hiệu chỉnh reference point của timestamp

**[IMPLEMENTATION]** Hàm decode áp dụng:

```text
Type 1 Mode A/C: timestamp_corrected = timestamp_raw - 244 tick
Type 2/3 Mode-S: timestamp_corrected = timestamp_raw - 768 tick
```

Tương đương:

| Loại | Correction | Thời gian |
|---|---:|---:|
| Type 1 | −244 tick | −20,333 µs |
| Type 2/3 | −768 tick | −64,000 µs |

Tài liệu Phase 1 gọi correction Type 1 là `T_F2 - 244`. Source hiện chỉ triển khai các hằng số đã được validation; nó không chứa một derivation vật lý chi tiết hơn, vì vậy tài liệu này không suy đoán thêm về firmware-specific timestamp convention.

Nếu raw timestamp bằng 0, corrected timestamp cũng được đặt bằng 0 và frame đó không được clock/association sử dụng.

### 4.4 Hai clock phần mềm đi kèm frame

Mỗi lần socket `read()` trả dữ liệu, backend chụp:

- `arrival_monotonic`: clock đơn điệu của server, dùng timeout, queue latency và pruning;
- `arrival_utc`: wall clock của server, dùng làm thời gian sự kiện/tracking công bố.

**[IMPLEMENTATION]** Mọi frame được parse từ cùng một TCP chunk nhận cùng hai giá trị này. Độ phân giải TDOA vẫn đến từ Beast tick 12 MHz; `arrival_utc` không được dùng để tính TDOA.

## 5. Clock synchronization bằng DF17

### 5.1 Vì sao cần đồng bộ

Với receiver `i`, timestamp có thể biểu diễn khái quát:

```text
t_i = clock_i(t) + range_i/c
```

Nếu trừ trực tiếp timestamp từ hai oscillator chưa đồng bộ, sai số clock bị lẫn với propagation delay. Một micro giây bias tương đương khoảng 299,8 m range-difference trước khi geometry khuếch đại thành sai số vị trí.

### 5.2 Dữ liệu calibration

**[IMPLEMENTATION]** Chỉ Beast Type 3 (`0x33`) có DF=17 mới đi vào clock calibrator. Luồng xử lý là:

1. decode airborne fields;
2. giữ CPR even/odd gần nhau không quá 10 giây theo monotonic time;
3. global-CPR decode latitude/longitude và lấy altitude DF17;
4. kiểm tra vùng hợp lệ `−10…45° lat`, `80…140° lon`, altitude `−500…20.000 m`;
5. gom các bản sao có exact payload trong cửa sổ 0,2 giây, tối đa một copy/station;
6. dùng vị trí DF17 để tính range hình học tới từng receiver;
7. loại propagation difference khỏi timestamp trước khi fit clock.

Với cặp canonical `(a,b)`:

```text
geometric_ticks_ab = (range_b - range_a)/c × 12 MHz

clock_b_without_propagation
    = timestamp_b_corrected - geometric_ticks_ab

clock_b_without_propagation
    ≈ slope_ab × timestamp_a_corrected + offset_ab
```

**[IMPLEMENTATION]** Vị trí DF17 chỉ được dùng trong bước calibration để loại phần propagation. ADS-B latitude/longitude không đi vào association, solver hoặc tracker Mode A/C/Mode-S.

### 5.3 Sáu clock links

Bốn receiver tạo sáu link:

```text
T37–Cái Chiên
T37–QK4
T37–Bạch Long Vĩ
Cái Chiên–QK4
Cái Chiên–Bạch Long Vĩ
QK4–Bạch Long Vĩ
```

Mỗi link giữ tối đa 2.000 samples. Linear fit bắt đầu khi có 20 sample; quality chỉ khả dụng từ 100 sample.

### 5.4 Miền thời gian T37

**[IMPLEMENTATION]** Association chuẩn hóa mọi corrected tick về clock domain T37:

```text
norm_T37 = timestamp_T37_corrected

norm_station =
    (timestamp_station_corrected - offset_T37_station)
    / slope_T37_station
```

Nếu link T37–station chưa có model, frame của station đó chưa thể association strict-4.

**[ENGINEERING INTERPRETATION]** Chọn T37 làm reference là lựa chọn tọa độ thời gian trong implementation, không phải khẳng định oscillator T37 luôn chính xác nhất. TDOA không đổi khi cộng cùng một offset vào mọi timestamp. T37 chỉ là anchor để biểu diễn các clock trong cùng một miền; chất lượng solver vẫn dùng residual P95 của cả sáu pair.

### 5.5 Residual, quality và discontinuity

Residual link được lưu theo micro giây:

```text
residual_us = (observed_clock_b - predicted_clock_b) / 12
```

| Điều kiện sau ít nhất 100 sample | Quality |
|---|---|
| absolute residual P95 `< 1 µs` | STRONG |
| P95 `< 5 µs` | PASS |
| P95 `< 10 µs` | MARGINAL |
| còn lại | BAD |

Trước 100 sample là `UNAVAILABLE`. Solver dùng:

```text
sigma_pair = max(1 µs, absolute residual P95 của link)
```

Một observation lệch hơn 100 µs so với model hiện hành bị xem là discontinuity. Hai lần đầu bị reject; lần thứ ba liên tiếp reset link để có thể reacquire sau clock restart.

## 6. Nhánh pipeline chung và scheduling

**[IMPLEMENTATION]** Tất cả frame đi qua một queue dùng chung tối đa 50.000 phần tử và một `frame_worker` tuần tự:

1. cập nhật receiver statistics;
2. đưa frame phù hợp vào clock synchronizer;
3. nếu `kind=modeac`, gọi Mode A/C associator;
4. nếu Type 2/3, gọi Mode-S associator;
5. strict event được đưa vào solver queue tương ứng.

Mode A/C và Mode-S dùng solver resources tách biệt:

| Pipeline | Event queue | Solver executor | Stale-work policy |
|---|---:|---|---|
| Mode A/C | 200 | 1 thread | không có age-drop riêng |
| Mode-S | 64 | 3 process workers | drop nếu queue age `>3 s` |

Việc tách Mode-S sang process pool là để tránh solver CPU-bound chặn Mode A/C/main event loop.

## 7. Association Mode A/C

### 7.1 Khóa association

**[IMPLEMENTATION]** Type 1 được nhóm theo exact hai-byte payload, biểu diễn bằng `raw_hex`. Đây là pulse word giống nhau, không phải ICAO.

Mỗi station có deque riêng cho từng raw code, tối đa 4.000 observations. Node lưu corrected tick, normalized tick, signal, arrival UTC và monotonic time.

### 7.2 Strict reciprocal-nearest 4RX

Khi một Type 1 mới đến, associator:

1. chuẩn hóa tick về T37;
2. tìm cùng `raw_hex` tại cả ba station còn lại;
3. chỉ giữ candidate trong maximum physical baseline time cộng margin 10 µs;
4. chọn candidate gần nhất theo normalized time;
5. nếu candidate thứ hai chỉ xa hơn candidate thứ nhất dưới 6 tick, trả `AMBIGUOUS_ASSOCIATION`;
6. kiểm tra mọi cặp không vượt `baseline/c + 10 µs`;
7. kiểm tra reciprocal-nearest cho cả sáu pair;
8. đánh dấu bốn node đã dùng, không cho tái sử dụng;
9. chỉ khi đủ cả bốn station mới tạo `STRICT_4RX` event.

Association status khác gồm:

- `INSUFFICIENT_RECEIVERS`;
- `AMBIGUOUS_ASSOCIATION`;
- `INCONSISTENT_ASSOCIATION`;
- `STRICT_4RX`.

**[ENGINEERING INTERPRETATION]** Exact Mode A/C code là signature yếu hơn Mode-S payload vì cùng squawk/code có thể lặp dày và nhiều aircraft có thể dùng cùng code. Vì vậy reciprocal-nearest, physical bounds và ambiguity gap là guard quan trọng; code equality không chứng minh cùng aircraft.

### 7.3 Event Mode A/C

Strict event chứa:

```text
event_id
raw_hex
nodes[4]
norm[4]
tdoa[6]
utc
latest_arrival_mono
```

`utc` là median của bốn `arrival_utc`; không được suy ra từ 48-bit Beast tick.

## 8. Decode và association Mode-S

### 8.1 Decoder

**[IMPLEMENTATION]** Decoder nhận payload 7 hoặc 14 byte, lấy `DF = payload[0] >> 3` và metadata:

- DF11, DF17: ICAO trực tiếp từ byte 1–3, `icao_source=DIRECT`;
- DF4/20: thử decode AC13 altitude khi Q=1;
- DF5/21: decode ID13 squawk;
- DF17: type code, CPR odd/even, CPR lat/lon và altitude-bearing metadata khi airborne fields hợp lệ;
- DF khác vẫn có thể được đếm/cluster nếu payload length hợp lệ, nhưng không nằm trong public solver set mặc định.

Với DF dùng Address Parity, decoder tính 24-bit CRC residual. Runtime chỉ tin recovered ICAO nếu ICAO đó đã xuất hiện trực tiếp trong DF11/17 trong cache 600 giây. Nếu chưa, event giữ `icao=None`, `icao_source=UNTRUSTED_PARITY`.

### 8.2 Exact-payload strict 4RX

Mode-S association dùng exact toàn bộ payload 7/14 byte làm khóa, không chỉ ICAO. Một buffer payload có deque tối đa tám observation mỗi station; toàn bộ cache tối đa 20.000 payload và được prune mặc định sau một giây.

Khi đủ bốn station:

1. chọn observation gần incoming normalized time nhất tại từng station;
2. ambiguity gap vẫn là 6 tick;
3. kiểm tra từng pair với `baseline/c + 3 µs`;
4. kiểm tra reciprocal-nearest hai chiều cho cả sáu pair;
5. xóa buffer của exact payload sau khi tạo event;
6. tạo sáu TDOA và metadata DF/ICAO.

So với Mode A/C, Mode-S dùng margin 3 µs thay vì 10 µs và exact full payload thường đặc trưng hơn exact 16-bit Type 1 word.

### 8.3 Những DF nào đi vào solver/publication

**[IMPLEMENTATION]** Mọi cluster hoàn chỉnh được đếm. Chỉ các event sau được đưa vào Mode-S solver mặc định:

```text
DF4, DF5, DF11, DF20, DF21
```

DF17 strict cluster vẫn phục vụ calibration/diagnostic. DF17 chỉ được đưa vào public MLAT solver khi khởi động với `--publish-df17-mlat`; default `PUBLISH_DF17_MLAT=False`.

Nếu AP identity chưa trusted, event vẫn có thể được solve, nhưng Mode-S tracker không tạo public track khi `icao=None`.

### 8.4 Event Mode-S

Mode-S strict event chứa:

```text
event_id, raw_hex, df
icao, icao_source, metadata
nodes[4], receiver_count=4
tdoa[6]
utc, latest_arrival_mono
association latency và queued monotonic time
```

`utc` hiện lấy phần tử thứ ba trong bốn `arrival_utc` đã sort, tức upper median; nó không được khôi phục từ Beast tick thành absolute UTC.

## 9. Tạo TDOA

Sau clock normalization, với pair ordered `(a,b)`:

```text
TDOA_ab [µs] = (norm_b - norm_a) / 12
```

Bốn station tạo sáu pair:

```text
C(4,2) = 6
```

Chỉ ba range differences là đại số độc lập nếu chọn một receiver reference, nhưng implementation giữ đủ sáu pair để:

- kiểm tra physical consistency trong association;
- tính residual của mọi baseline;
- weight theo quality riêng của từng clock link;
- phân biệt branch bằng phương trình dư.

Mô hình dự đoán tại vị trí ECEF `x`:

```text
r_i(x) = ||x - x_i||

TDOA_ab,predicted(x)
    = [r_b(x) - r_a(x)] / c
```

Residual theo micro giây:

```text
e_ab = TDOA_ab,measured - TDOA_ab,predicted
```

## 10. Solver 2D có altitude hỗ trợ

### 10.1 Không phải unconstrained 3D

**[IMPLEMENTATION]** Realtime tái sử dụng solver Test 7C. Mỗi lần solve giữ altitude cố định và tối ưu hai biến horizontal East/North quanh tâm mạng. Vị trí receiver và target được chuyển WGS84 geodetic → ECEF để tính slant range.

Altitude grid mặc định:

```text
0, 5.000, 10.000, …, 45.000 ft
```

Mỗi band altitude tạo một bài toán 2D độc lập. Backend sau đó so sánh các horizontal solution family trên toàn altitude grid.

**[ENGINEERING INTERPRETATION]** Đây là “2D + altitude hypothesis”, không phải 3D MLAT. Altitude giúp xác định slant-range model và branch horizontal, nhưng grid band thắng không được coi là altitude quan sát đáng tin.

### 10.2 Multi-start nonlinear least squares

Solver dùng nhiều start points:

- tâm mạng;
- các vòng 50/100/250/500/900 km theo tám hướng;
- vị trí các receiver.

Tại mỗi altitude, `scipy.optimize.least_squares(method="lm")` tối thiểu hóa ba independent range-difference residual dùng station đầu tiên, T37, làm reference. Các nghiệm hội tụ cách nhau dưới 100 m được deduplicate.

Sau đó solver tính lại:

- predicted TDOA cho cả sáu pair;
- six-pair RMS và maximum residual;
- numeric Jacobian horizontal;
- Jacobian condition number;
- khoảng cách nghiệm tới tâm mạng.

### 10.3 Clock-weighted residual

Với candidate `k`:

```text
weighted_rms_k
    = sqrt(mean_pair[(e_pair,k / sigma_pair)^2])
```

`sigma_pair` là clock-link P95 với floor 1 µs. Vì vậy một link đang MARGINAL/BAD có trọng số thấp hơn link STRONG, nhưng không tự động bị loại khỏi strict-4 event.

### 10.4 Altitude metadata hiện không điều khiển solver strict-4

**[IMPLEMENTATION]** Đây là ranh giới quan trọng:

- Mode A/C Gillham/Mode-C candidate chỉ là metadata, không tham gia localization;
- altitude decoded từ DF4/20 hoặc DF17 cũng không được truyền vào hàm strict-4 realtime solver;
- strict-4 Mode-S và Mode A/C đều quét cùng altitude grid;
- đường 3RX + message altitude đã được thử offline nhưng bị tắt trong realtime.

Mode A/C tracker công bố altitude `null`, source `unknown`. Mode-S tracker dùng message altitude nếu event tạo track có altitude; nếu không, giá trị altitude vẫn `null`. Altitude hypothesis nội bộ của grid không được công bố như một nghiệm 3D.

## 11. Branch clustering và phân loại blind

### 11.1 Tạo family

Candidate hợp lệ cần:

```text
condition hữu hạn và ≤ 1e8
center distance trong radius đang xét
```

Candidate được sort theo weighted RMS rồi gom thành cùng family nếu horizontal separation không quá 25 km. Mỗi family giữ đại diện tốt nhất theo weighted RMS, unweighted RMS và center distance.

Hai vùng tìm kiếm được dùng:

- **primary**: trong 1.500 km từ tâm mạng;
- **expanded sensitivity**: trong 3.000 km.

Expanded set giúp phát hiện nghiệm cạnh tranh ở xa mà primary set có thể bỏ qua.

### 11.2 Classification

Gọi `best` là primary family tốt nhất và `second` là family thứ hai:

```text
không có primary candidate
    → BLIND_INCONSISTENT

best.weighted_rms > 1,5
    → BLIND_INCONSISTENT

second tồn tại,
margin = second - best < 0,5,
và second/best < 1,5
    → BLIND_MULTIPLE

hoặc expanded có competitor cách best >25 km
nhưng weighted RMS chỉ kém <0,5
    → BLIND_MULTIPLE

còn lại
    → BLIND_UNIQUE
```

`branch_margin` công bố khi có second primary family:

```text
branch_margin = second_weighted_rms - best_weighted_rms
```

Chỉ `BLIND_UNIQUE` được đưa vào tracker. Multiple và inconsistent chỉ tăng counter/log; chúng không tạo marker vị trí.

**[ENGINEERING INTERPRETATION]** `BLIND_UNIQUE` nghĩa là duy nhất theo search, grid altitude, thresholds và clock weights hiện tại. Nó không có nghĩa vị trí đã được ground-truth xác nhận hoặc không thể tồn tại branch ngoài search region.

## 12. Tracking Mode A/C: anonymous by design

### 12.1 Metadata code

Type 1 raw word được decode thành:

- `display_code` Mode A;
- Gillham decodable flag;
- plausible Mode-C candidate và decoded altitude candidate;
- `mode_interpretation=UNKNOWN`.

**[IMPLEMENTATION]** Những trường này chỉ phục vụ hiển thị/diagnostic. Backend không khẳng định reply là Mode A hay Mode C và không gán ICAO.

### 12.2 Association fix vào track

Track ID có dạng:

```text
MAC-000001, MAC-000002, …
```

Candidate track phải:

1. có cùng display code;
2. chưa expired;
3. time gap `0 < Δt ≤ 120 s`;
4. thỏa hard jump `≤450 m/s × Δt + 2 km`;
5. thỏa miss distance so với constant-velocity prediction `≤450 m/s × Δt + 5 km`.

Nếu nhiều track đạt gate, chọn predicted miss nhỏ nhất. Nếu không có, tạo anonymous track mới. Code equality một mình không merge hai target ở xa.

### 12.3 State, quality và motion

| Quy tắc | Kết quả |
|---|---|
| fix 1–2 | TENTATIVE |
| từ fix 3 | CONFIRMED |
| không có fix 30 s | STALE |
| không có fix 120 s | track_removed/EXPIRED |

Quality:

```text
HIGH:
  fix_count ≥5, weighted_rms ≤1,0,
  clock quality là STRONG hoặc PASS

MEDIUM:
  fix_count ≥3, weighted_rms ≤1,5

LOW:
  các trường hợp còn lại
```

Speed/heading được suy ra từ hai fix MLAT liên tiếp; chúng không phải tốc độ ADS-B. Backend giữ tối đa 20 history points nội bộ cho Mode A/C, nhưng REST/WebSocket công bố current track chứ không công bố history array này.

Mọi track mang:

```text
position_source = MODEAC_MLAT_4RX
receiver_count  = 4
```

## 13. Tracking Mode-S: identity-aware nhưng vẫn là vị trí MLAT

Track ID:

```text
MS-<ICAO uppercase>
```

**[IMPLEMENTATION]** Mode-S tracker chỉ tạo/update track khi event có ICAO trusted. Identity đến từ message, còn latitude/longitude vẫn đến từ TDOA solver. Hai semantics này không được trộn:

```text
identity source = Mode-S payload/parity trust rule
position source = MODES_MLAT_4RX
```

Update cùng ICAO bị reject nếu:

```text
Δt ≤ 0

hoặc, khi Δt ≤120 s:
horizontal jump > 450 m/s × Δt + 2 km
```

State và quality thresholds giống Mode A/C. Speed/heading là chênh lệch giữa các fix MLAT liên tiếp.

Khi tạo track:

- nếu message có altitude decoded, `altitude_source=MODE_S_MESSAGE`;
- nếu không có, `altitude_ft=null`; source hiện được đặt `MLAT_HYPOTHESIS`, nhưng grid altitude value không được gán vào public `altitude_ft`;
- update path hiện không refresh altitude field từ event sau.

Điểm cuối là một giới hạn implementation cần lưu ý khi dùng dữ liệu cho nghiên cứu altitude.

## 14. Measurement timestamp và publication timestamp

### 14.1 Bốn miền thời gian khác nhau

| Khái niệm | Nguồn | Công dụng |
|---|---|---|
| raw/corrected Beast tick | oscillator receiver, 12 MHz | clock fit và TDOA |
| normalized tick | transform về T37 | association và TDOA |
| event UTC / `last_seen` | wall-clock arrival của server | lifecycle và measurement-age proxy |
| publication/receipt time | lúc tracker/WebSocket/REST/browser nhận kết quả | latency và UI receipt age |

### 14.2 `last_seen` không phải lúc publication

**[IMPLEMENTATION]** Tracker lấy `event.utc_iso` làm `last_seen` và không đổi nó khi solver hoàn thành. Nếu event chờ lâu trong queue:

```text
RF/receive event:        16:00:00
solver hoàn thành:       16:00:42
browser nhận REST/WS:    16:00:43

Last seen ≈ 43 s
Received  ≈ 0–1 s
```

REST trả thêm `age_s = server_now - last_seen_epoch`; tar1090/frontend có thể tự tính age từ `last_seen`. Backend không công bố một `published_at` riêng trong track payload. Mode-S stats đo monotonic association/queue/solver/track/total latency; Mode A/C stats giữ arrival-to-publication latency.

### 14.3 Giới hạn của chữ “measurement timestamp”

**[IMPLEMENTATION]** `last_seen` hiện không phải absolute UTC được discipline từ 48-bit Beast timestamp. Nó là median/upper-median của server `arrival_utc` gắn vào các receiver copies. Vì vậy nên diễn giải là **event-associated receive time / measurement-time proxy**, đủ để không reset freshness lúc publication nhưng không phải timestamp UTC hardware-grade của transmission.

**[MEASURED]** Phase 10 ghi nhận các event khi browser nhận đã cũ 50,9; 61,1; 71,2 và 87,8 giây. UI vẫn hiển thị tuổi từ `last_seen`, không biến thành 0 giây do REST receipt mới.

## 15. REST API

Backend mặc định nghe trên `0.0.0.0:8090`.

### 15.1 Endpoint chung

| Endpoint | Nội dung |
|---|---|
| `GET /health` | uptime, số receiver connected, strict flags |
| `GET /api/receivers` | mapping, connection/reconnect, Type1/2/3 rates, parser errors |
| `GET /api/clocks` | sáu link, slope/offset, sample count, residual percentiles, quality, age/reset |

### 15.2 Mode A/C

| Endpoint | Nội dung |
|---|---|
| `GET /api/modeac/tracks` | current anonymous tracks; filter `?min_quality=LOW|MEDIUM|HIGH` |
| `GET /api/modeac/stats` | rates/classifications, latency, queue/buffer depth, drops |

Track public chứa code, anonymous ID, lat/lon, state, quality, fix count, speed/heading, `last_seen`, `age_s`, clock/branch diagnostics và exact `MODEAC_MLAT_4RX` source.

### 15.3 Mode-S

| Endpoint | Nội dung |
|---|---|
| `GET /api/modes/tracks` | current ICAO-keyed PoC tracks; quality filter tương tự |
| `GET /api/modes/stats` | DF distribution, cluster/fix rates, stage latency, queue/cache/drop metrics |

Track public chứa ICAO, DF gần nhất, lat/lon, altitude metadata, lifecycle, quality, motion, clock/branch fields và `MODES_MLAT_4RX` source.

## 16. WebSocket

Hai namespace độc lập:

```text
ws://HOST:8090/ws/modeac
ws://HOST:8090/ws/modes
```

Ngay sau handshake, server gửi:

```json
{"type":"snapshot","tracks":[...]}
```

Các event tiếp theo:

```text
track_created
track_updated
track_state_changed
track_stale
track_removed
```

Mỗi namespace có subscriber set và queue riêng, tối đa 1.000 event/subscriber. Failure của một stream không làm đổi state hoặc stream còn lại. WebSocket là output-only trong implementation hiện tại; frontend không gửi lệnh điều khiển solver.

## 17. Bounded state, pruning và failure behavior

| Thành phần | Giới hạn/cửa sổ |
|---|---:|
| Shared frame queue | 50.000 |
| Mode A/C event queue | 200 |
| Mode-S event queue | 64 |
| Mode A/C observations/code/station | 4.000 |
| Mode-S exact payload keys | 20.000 |
| Mode-S observations/station/payload | 8 |
| Mode-S buffer age | 1 s |
| Clock samples/link | 2.000 |
| Latency samples | 5.000 |
| WebSocket queue/subscriber | 1.000 |

Queue full làm drop new work và tăng counter. Mode-S work chờ hơn ba giây bị stale-drop trước solver. Housekeeping mỗi giây:

- expire/stale tracks;
- prune Mode A/C/Mode-S association cache;
- prune DF17 clock CPR/pending groups;
- cập nhật queue depth, oldest queued age và bounded-entry counters.

Backend state và track IDs là memory-only; restart làm mất track continuity và bắt đầu lại anonymous counter.

## 18. So sánh hai pipeline

| Thuộc tính | Mode A/C | Mode-S |
|---|---|---|
| Beast input | Type 1 | Type 2/3 |
| Association key | exact 2-byte raw word | exact 7/14-byte payload |
| Margin vật lý | 10 µs | 3 µs |
| Identity | không có ICAO; anonymous | direct/trusted ICAO nếu đủ điều kiện |
| Public formats | mọi strict Type 1 unique fix | DF4/5/11/20/21; DF17 off mặc định |
| Solver | same altitude-grid 2D | same altitude-grid 2D |
| Track key | code + motion gate, `MAC-*` | ICAO, `MS-*` |
| Position source | `MODEAC_MLAT_4RX` | `MODES_MLAT_4RX` |
| Solver resource | 1 thread | 3 process workers |
| Queue stale drop | không | >3 s |

## 19. Anti-leakage và scientific semantics

**[IMPLEMENTATION]** Những dữ liệu được phép ảnh hưởng vị trí:

- corrected/normalized timestamps;
- receiver coordinates;
- speed of light;
- altitude hypothesis grid;
- six-link clock residual weights;
- nonlinear residual/geometry/branch rules.

DF17 latitude/longitude chỉ ảnh hưởng clock calibration. Mode-S ICAO ảnh hưởng track identity, không ảnh hưởng solver lat/lon. Mode A/C Gillham candidate không ảnh hưởng solver.

**[IMPLEMENTATION]** Những dữ liệu không đi vào solver:

- production ADS-B trajectory;
- tar1090/readsb current aircraft position;
- mutability/production MLAT output;
- frontend map selection;
- co-track hint;
- browser comparison vector;
- callsign hoặc operator interpretation.

**[ENGINEERING INTERPRETATION]** Điều này cho phép dùng ADS-B post-hoc làm reference diagnostic mà không biến reference thành input. Tuy nhiên ADS-B cũng không phải absolute ground truth; các báo cáo đúng khi gọi nó là external truth/reference trong ngữ cảnh PoC.

## 20. Bằng chứng đo đã có

### 20.1 Mode A/C realtime

**[MEASURED] Phase 1, 310 giây:**

- 4/4 receiver connected, zero parse/reconnect/queue drops;
- cả sáu clock links STRONG, worst P95 0,509 µs;
- 5 strict events → 5 BLIND_UNIQUE;
- latency arrival-to-publication P50/P90/P95 = 1,022/1,658/1,850 s;
- ba anonymous tracks được quan sát, source `MODEAC_MLAT_4RX`.

**[MEASURED] Phase 2, 600 giây:**

- 194 strict events;
- 180 unique, 14 inconsistent, zero multiple;
- latency cuối run P50/P90/P95 = 4,41/14,12/15,65 s;
- 57 track IDs, 15 confirmed, 8 high.

**[MEASURED] Phase 9, 1.800 giây:** late burst tạo queue 44 events và nâng aggregate Mode A/C P95 lên 58,7 s trước khi queue drain. Đây là bằng chứng giới hạn throughput của single Mode A/C solver, không phải sai số timestamp TDOA.

### 20.2 Blind DF17 offline, Phase 8A

**[MEASURED]** Capture Test 7H:

- 540 strict 4RX DF17;
- 535 BLIND_UNIQUE, 5 BLIND_MULTIPLE;
- 529 post-hoc truth matches;
- horizontal P50/P90/P95 = 146/601/992 m;
- không event nào vượt 5 km trong tập evaluated;
- frozen branch gần reference nhất 529/529.

DF17 publication vẫn off mặc định trong realtime; kết quả này là validation của association/solver, không phải lý do để trộn PoC với production ADS-B.

### 20.3 Non-position Mode-S offline, Phase 8B

**[MEASURED]** DF4/5/11/20/21:

- 649 strict 4RX;
- 646 BLIND_UNIQUE, 3 BLIND_MULTIPLE;
- 643 truth-evaluated;
- horizontal P50/P90/P95 = 150/982/1.324 m;
- không event evaluated nào vượt 5 km;
- DF11 đóng góp 542/649 strict events.

Ba receiver cộng message altitude thất bại trong dataset này:

- 3.029 attempts;
- 3.019 `ALT_3RX_MULTIPLE`;
- post-hoc horizontal P50/P95 khoảng 41/411 km.

Vì vậy 3RX+altitude không được publish trong realtime.

### 20.4 Unified live Mode-S

**[MEASURED] Phase 8C, 657,7 giây:**

- 1.203 exact 4RX clusters gồm diagnostic DF17;
- 500 non-position events vào solver, 499 unique fixes;
- Mode-S total arrival-to-publication P50/P90/P95 = 0,884/2,016/2,526 s;
- event queue high-water 10/64; một stale drop; zero queue-full drop;
- parent + 3 workers peak khoảng 321% CPU trên bốn core, RSS gần 209 MiB.

**[MEASURED] Phase 9:** 737 Mode-S solver events → 733 unique; P50/P90/P95 = 0,888/1,786/2,274 s, zero stale/full drop trong run đó.

### 20.5 Cách đọc các số accuracy

**[ENGINEERING INTERPRETATION]** Các percentile trên chứng minh feasibility trong capture đã đóng băng, không chứng minh:

- accuracy ở mọi target altitude/vùng địa lý;
- performance khi clock quality khác;
- RF yield trong traffic window khác;
- mức an toàn dùng cho separation;
- production equivalence với mlat-server/mutability.

Yield strict-4 còn phụ thuộc giao vùng thu của cả bốn receiver. Geometry tốt không tạo event nếu một receiver không thu được transmission.

## 21. Các giới hạn khoa học và implementation hiện tại

1. **Strict 4RX cố định:** mất một receiver là không có fix; chưa có realtime best 4-of-N.
2. **Mode A/C anonymous:** cùng display code có thể thuộc nhiều aircraft; motion gate giảm nhưng không loại bỏ mọi ambiguity.
3. **Altitude không quan sát độc lập:** grid altitude chỉ hỗ trợ horizontal branch search; public Mode A/C altitude là unknown.
4. **3RX+altitude tắt:** validation hiện tại cho thấy branch ambiguity và error rất lớn.
5. **Clock phụ thuộc DF17:** thiếu common DF17 làm model unavailable/degraded.
6. **T37 là hard-coded time anchor:** đổi reference cần sửa implementation và regression riêng, dù về toán common-time origin là tùy ý.
7. **Event UTC là receive-time proxy:** chưa map corrected 48-bit Beast ticks vào absolute synchronized UTC.
8. **Mode A/C solver serialized:** burst có thể làm publication trễ hàng chục giây; `last_seen` giữ event time nên freshness vẫn lộ ra.
9. **Mode-S identity cache:** AP identity chỉ trusted sau direct observation và hết hạn sau 600 giây; untrusted fix không thành public track.
10. **Mode-S altitude lifecycle:** altitude được thiết lập lúc tạo track nhưng update path hiện không refresh nó.
11. **State không persistent:** backend restart mất track history/ID continuity và clock phải reacquire.
12. **Không phải security-hardened service:** HTTP/WebSocket server nhỏ, dependency-free và phù hợp PoC; không có authentication/TLS nội tại.
13. **Search hữu hạn:** BLIND_UNIQUE là duy nhất trong altitude/search/threshold hiện hành, không phải chứng minh nghiệm toàn cục.
14. **Reference không phải absolute truth:** post-hoc ADS-B giúp validation nhưng có sai số và timestamp riêng.

## 22. Trình tự một event điển hình

### 22.1 Mode A/C

```text
1. Bốn readsb/forwarder gửi cùng reply Type 1.
2. Parser bỏ Beast escaping, đọc timestamp/signal/raw word.
3. Mỗi timestamp trừ 244 tick.
4. Link T37–station biến đổi tick về clock domain T37.
5. Exact raw word + normalized proximity tạo candidate.
6. Physical bounds + ambiguity + reciprocal checks pass ở 4/4 RX.
7. Sáu TDOA được tính bằng tick difference / 12.
8. Solver quét 10 altitude hypotheses, multi-start mỗi altitude.
9. Candidate được weight bằng six-link clock P95 và cluster 25 km.
10. Chỉ BLIND_UNIQUE đi vào anonymous motion-gated tracker.
11. Track mang MODEAC_MLAT_4RX, last_seen từ event receive time.
12. REST snapshot hoặc WebSocket lifecycle event công bố current track.
```

### 22.2 Mode-S DF11 ví dụ

```text
1. Bốn receiver gửi cùng exact 56-bit DF11 payload.
2. Parser Type 2 trừ 768 tick.
3. Decoder lấy DF=11 và ICAO direct.
4. Tick được normalize về T37.
5. Exact payload + reciprocal nearest + baseline/c + 3 µs pass.
6. Strict 4RX event có ICAO và sáu TDOA.
7. Event vào bounded Mode-S process-pool queue.
8. Altitude-grid 2D solver trả BLIND_UNIQUE.
9. ICAO-keyed tracker tạo/update MS-<ICAO>.
10. Track mang MODES_MLAT_4RX và được phát qua /ws/modes.
```

## 23. Công thức cốt lõi

### 23.1 Tick sang thời gian

```text
t_us = ticks / 12
```

### 23.2 Propagation correction cho clock sample

```text
Δticks_geometry_ab = (r_b - r_a)/c × 12.000.000
```

### 23.3 Clock normalization về T37

```text
t_norm,s = (t_corrected,s - offset_T37,s)/slope_T37,s
```

### 23.4 Measured TDOA

```text
Δt_ab = (t_norm,b - t_norm,a)/12   [µs]
```

### 23.5 Predicted TDOA

```text
Δt_ab(x) = (||x-x_b|| - ||x-x_a||)/c
```

### 23.6 Weighted residual score

```text
WRMS = sqrt(mean_ab[(e_ab/σ_ab)^2])
```

## 24. Kết luận

**[IMPLEMENTATION]** Pipeline hiện tại là hai MLAT branches dùng chung Beast ingest và DF17 clock synchronization nhưng giữ association, identity namespace, tracker, API và WebSocket riêng. Cả hai chỉ publish strict four-receiver horizontal positions được phân loại `BLIND_UNIQUE`.

**[MEASURED]** Dataset frozen và các live soak đã chứng minh pipeline có thể tạo các fix sub-kilometre đến low-kilometre percentile trong những capture thuận lợi, đồng thời phơi bày rõ hai nút thắt: strict common reception và clock/solver burst latency.

**[ENGINEERING INTERPRETATION]** Kiến trúc phù hợp làm PoC khoa học vì source position, identity, timing quality, branch class và lifecycle được tách rõ. Để tiến tới hệ thống vận hành cần tối thiểu realtime 4-of-N có validation riêng, absolute event-time treatment tốt hơn, throughput Mode A/C, persistent observability, security/service supervision và kiểm chứng rộng hơn theo geometry, altitude, RF và traffic.
