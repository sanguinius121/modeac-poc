# Phase 10B — Generic N-RX Association

## Phạm vi

Phase 10B tạo representation và association core cho một transmission được 2..N receiver quan sát. Core không localization, không enumerate `C(N,4)`, không chọn subset và không publish vào tracker/API. Realtime fixed-4 hiện hữu được giữ như compatibility path; việc đưa N-RX cluster vào solver thuộc Phase 10C trở đi.

## Fixed-4 assumptions tìm thấy trước refactor

[IMPLEMENTATION]

| Vị trí | Giả định |
|---|---|
| `realtime/config.py` | `STATIONS`/`ORDER` chỉ có bốn receiver production |
| `realtime/association.py` | Mode A/C yêu cầu mọi station trong global `ORDER`, event tên `STRICT_4RX` và sáu TDOA |
| `realtime/modes/realtime.py` | Mode-S chỉ hoàn tất khi đủ global `ORDER`, `receiver_count=4`, rồi xóa payload row |
| `realtime/modes/association.py` cũ | Batch association dùng global `ORDER`/`STATIONS` |
| `realtime/clock_sync.py` cũ | `ready()` trả một boolean toàn mạng; reference `T37` hard-code |
| hai localizer | global `ORDER`/`PAIRS` và solver input đúng bốn trạm |
| `main.py`, state/API/tracker | counter, event queue và position source fixed-4 |

Phase 10B loại bỏ các giả định receiver count/order/station geometry khỏi generic association core và batch Mode-S wrapper. Các giả định trong compatibility realtime adapter, solver, tracker và public API được cố ý giữ để output không đổi.

## Data model mới

`realtime/nrx_association.py` định nghĩa `TransmissionCluster` bất biến về cấu trúc:

```text
cluster_id
transmission_key
observations_by_receiver
receiver_ids
normalized_timestamps
metadata
measurement_utc_ns
association_latency_ms
receiver_count (derived)
```

`receiver_ids` là tuple theo receiver order được truyền vào core. `observations_by_receiver` và `normalized_timestamps` keyed bằng receiver ID. `receiver_count` luôn lấy từ độ dài tuple, không gán cứng bằng 4.

Ví dụ 5RX:

```text
receiver_ids = (
  T37,
  Dao_Cai_chien,
  QK4,
  BachLongVi,
  MongCai
)
receiver_count = 5
```

Đó là **một cluster**, không phải năm quartet. Phase 10C có thể gọi `combinations(cluster.receiver_ids, 4)` bên ngoài association core.

## Generic batch association

`associate_observations(observations, transforms, receiver_ids, stations, margin_us, ambiguity_ticks)` nhận topology và mapping clock qua tham số. Flow dùng chung cho Mode A/C và Mode-S:

1. bỏ receiver không thuộc topology hoặc chưa có clock transform;
2. nhóm bằng exact `transmission_key`/`raw_hex`;
3. normalize timestamp về common domain;
4. sắp xếp deterministic theo normalized time, receiver rank và observation ID;
5. chọn candidate gần seed cho từng receiver;
6. reject nếu hai candidate gần tương đương trong 6 tick;
7. loại node vi phạm physical baseline bound + margin;
8. kiểm tra reciprocal-nearest cho mọi pair còn lại;
9. đánh dấu observation ID đã dùng;
10. tạo đúng một `TransmissionCluster` chứa toàn bộ receiver compatible.

Không có vòng lặp `combinations(receiver_ids, 4)` trong core. Validation pairwise là `O(R²)` cho cluster R receiver; đây là kiểm tra vật lý hiện hữu, không phải solver-subset enumeration.

## Mode-S association

`realtime/modes/association.py` nay là compatibility wrapper gọi generic core. Default vẫn dùng production `ORDER`/`STATIONS`, nên các tool Test 8 và fixed-4 fixture giữ schema dict cũ qua `cluster.as_dict()`.

Semantics không đổi:

- exact full payload;
- normalized time;
- physical limit + 3 µs;
- ambiguity 6 tick;
- reciprocal nearest;
- observation ownership disjoint.

`RealtimeModeSAssociator` đang publish vào solver không được chuyển sang 5RX trong phase này. Đây là compatibility boundary cần thay có kiểm soát trong shadow phase sau 10C.

## Mode A/C association

Generic core xử lý Mode A/C bằng exact raw code làm transmission candidate, không coi raw code là aircraft identity. Margin vẫn 10 µs; các gate normalized/physical/ambiguity/reciprocal giống implementation đã validate.

`StrictAssociator` production vẫn là fixed-4 adapter và không đổi public event. Replay 10B chạy Mode A/C qua generic core; test regression cũng so generic quartet với `StrictAssociator` hiện hữu.

## Duplicate prevention và observation ownership

- Mỗi input observation phải có ID; core tạo ID deterministic theo sequence nếu thiếu.
- Duplicate ID trong cùng pass bị reject.
- `used` set chỉ cho một observation thuộc một associated cluster trong pass.
- Cluster identity là SHA256 rút gọn của exact key và ordered observation IDs.
- Một 5RX transmission được chọn một lần và tạo một cluster 5RX; core không materialize năm subset.
- Batch output được sort theo measurement UTC và transmission key.

## Streaming buffer và delayed fifth receiver

`NrxAssociationBuffer` là interface bounded chuẩn bị cho integration sau này:

- buffer keyed bằng exact transmission key;
- candidate chưa đủ mọi configured receiver chờ `settle_s` (default 50 ms);
- nếu receiver thứ năm đến trước emission, cluster được tạo với `receiver_count=5`;
- row đủ toàn bộ configured receivers có thể association ngay;
- emitted row bị xóa;
- observation IDs đã consume được giữ trong bounded cache (default 100.000) để reject reuse;
- `max_age_s` mặc định 1 s;
- `max_payloads` mặc định 20.000;
- settle/expiry dùng heap, không scan toàn buffer trên mỗi observation;
- capacity overflow trước hết prune expired, sau đó evict oldest và tăng diagnostic counter.

Streaming buffer chưa nối vào public solver path trong 10B. Network receipt time không được dùng để thay measurement timestamp trong cluster.

## Clock readiness mới

`ClockSynchronizer` nay nhận tùy chọn `stations`, `order`, `reference`, mặc định giữ topology production và T37. API nội bộ mới:

```text
receiver_ready(receiver_id)
usable_receivers(receiver_ids=None)
ready(receiver_ids=None, minimum_receivers=None)
```

Một non-reference receiver usable khi direct model giữa T37 và receiver đó có slope. Missing link giữa hai non-reference receiver, ví dụ QK4–MongCai, không block MongCai nếu T37–MongCai usable. `ready()` không tham số vẫn yêu cầu toàn bộ receiver của compatibility topology, giữ hành vi cũ. Fitting algorithm và quality thresholds không đổi.

## Counters

Core/result và streaming buffer cung cấp:

- total observations;
- 2RX/3RX/4RX/5RX;
- receiver membership đầy đủ;
- Mode-S per DF 0/4/5/11/16/17/20/21.

Counters là diagnostic nội bộ/artifact, chưa thêm REST/WS field.

## Replay partition và cleanup

Replay 10A dùng 64 temporary exact-payload hash buckets. Tất cả observation của cùng payload luôn vào cùng bucket, vì vậy không cắt một transmission theo time window và không đổi association result. Bucket được xóa tự động sau mỗi family. Cách này giảm RSS từ thử nghiệm batch ban đầu khoảng 2,48 GiB xuống khoảng 107 MiB mà giữ fixed-4/count tuyệt đối.

## Interface cho Phase 10C

Phase 10C chỉ nên nhận `TransmissionCluster` và đọc:

```python
cluster.receiver_ids
cluster.observations_by_receiver
cluster.receiver_count
cluster.normalized_timestamps
```

Sau đó Phase 10C mới enumerate quartet, tạo TDOA theo quartet, chạy solver/ranking và xử lý cross-subset consistency. Không đưa logic đó ngược vào association core.

## Limitations

- Capture replay không có cluster 5RX thật; representation 5RX được xác minh synthetic bằng test.
- Generic streaming buffer chưa chạy live/soak và chưa nối solver.
- Full N-RX Mode A/C ownership có thể chặt hơn union của năm subset chạy độc lập; đây là thay đổi diagnostic có chủ ý, không đổi baseline compatibility path.
- Localizers, trackers, public API và realtime publication vẫn fixed-4.
