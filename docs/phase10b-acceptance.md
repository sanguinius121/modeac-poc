# Phase 10B — Acceptance report Generic N-RX Association

## Kết luận

**PASS** cho phạm vi association/interface. Generic core biểu diễn đúng 4RX/5RX, không enumerate quartet, fixed-4 regression giữ nguyên, clock readiness được đánh giá theo mapping về T37 và toàn bộ test PASS. Không triển khai Phase 10C.

## Source và phương pháp

- Replay source: `test10a/20260818T011249Z`
- Common window: 299,878801516 s
- Receiver: T37, Dao_Cai_chien, QK4, BachLongVi, MongCai
- Không live capture; không bind/restart service/cổng.
- Replay chia 64 bucket theo exact payload; không chia cùng payload qua nhiều bucket.

## Replay cluster counts

| Family | Observations | 2RX | 3RX | 4RX | 5RX |
|---|---:|---:|---:|---:|---:|
| Mode A/C | 955.386 | 125.588 | 21.054 | 740 | 0 |
| All Mode-S | 365.971 | 60.226 | 23.728 | 3.766 | 0 |
| DF0 | — | 9.117 | 3.155 | 330 | 0 |
| DF4 | — | 3.171 | 1.399 | 197 | 0 |
| DF5 | — | 676 | 232 | 31 | 0 |
| DF11 | — | 18.967 | 8.587 | 1.943 | 0 |
| DF16 | — | 749 | 158 | 6 | 0 |
| DF17 | — | 18.342 | 7.518 | 1.032 | 0 |
| DF20 | — | 7.989 | 2.410 | 202 | 0 |
| DF21 | — | 1.215 | 269 | 25 | 0 |

[MEASURED] Không có 5RX cluster trong capture. [IMPLEMENTATION] Test synthetic chứng minh một transmission đủ năm receiver tạo đúng một cluster `receiver_count=5`, không tạo năm cluster 4RX.

## Receiver membership 4RX

Mode A/C:

| Membership | Count |
|---|---:|
| T37+Dao_Cai_chien+BachLongVi+MongCai | 740 |

Mode-S:

| Membership | Count |
|---|---:|
| T37+Dao_Cai_chien+BachLongVi+MongCai | 3.730 |
| T37+Dao_Cai_chien+QK4+BachLongVi | 35 |
| T37+Dao_Cai_chien+QK4+MongCai | 1 |

## Fixed-4 regression

Baseline membership: T37+Dao_Cai_chien+QK4+BachLongVi.

| Family | Frozen expected | Generic actual |
|---|---:|---:|
| Mode A/C | 0 | 0 |
| All Mode-S | 35 | 35 |
| DF0 | 2 | 2 |
| DF4 | 1 | 1 |
| DF5 | 0 | 0 |
| DF11 | 16 | 16 |
| DF16 | 0 | 0 |
| DF17 | 13 | 13 |
| DF20 | 2 | 2 |
| DF21 | 1 | 1 |

Result: **exact match**. Synthetic Mode A/C quartet cũng khớp receiver membership của `StrictAssociator` production; generic output có ordering deterministic riêng.

## Khác biệt với any-4-of-5 Phase 10A

- Mode-S: 10A any-4 = 3.766; 10B maximal generic 4RX = 3.766 — giống nhau.
- Mode A/C: 10A any-4 = 748; 10B maximal generic 4RX = 740 — giảm 8.

[ENGINEERING INTERPRETATION] 10A chạy năm subset độc lập rồi union bằng shared observation IDs. 10B giải ambiguity và observation ownership một lần trên toàn receiver set. Tám Mode A/C candidate chỉ tồn tại trong subset-isolated pass không tồn tại như maximal globally consistent cluster. Không có gate nào được nới; baseline fixed-4 vẫn bằng 0 và không đổi.

## Duplicate, ownership và cleanup validation

- 5RX synthetic: một cluster duy nhất.
- Duplicate observation ID: reject.
- Repeated exact payload ở hai thời điểm: hai disjoint clusters, không reuse ID.
- Ambiguous duplicate raw-code: ambiguity counter tăng.
- Physical-invalid receiver: không được giữ trong cluster.
- Delayed fifth receiver trước settle: join cluster 5RX.
- Settled 4RX: emit một lần.
- Expired partial row: xóa.
- Payload buffer: bounded.
- Consumed-ID cache: bounded 100.000.
- Receiver order và cluster ID: deterministic.

## Clock readiness

Test xác minh tất cả direct T37 mappings có thể usable trong khi QK4–MongCai vẫn unavailable. Missing non-reference pair không block toàn association. Default production readiness behavior vẫn tương thích.

## Performance

| Metric | Result |
|---|---:|
| Replay wall time | 27,61 s |
| Process CPU time | 28,27 s |
| CPU equivalent | 102,4% (~một core) |
| Peak RSS | 114.996 KiB (~112,3 MiB) |
| Throughput | ~8.517 associated clusters/s |
| Association latency Mode A/C P50/P95 | 0,0154 / 0,0211 ms |
| Association latency Mode-S P50/P95 | 0,0154 / 0,0249 ms |
| Partition buckets | 64 |
| Replay queue | Không áp dụng; offline bounded partition |
| Source capture queue | high-water 25.799/100.000, final 0, drop 0 |
| Source parser errors | 0 |

Không có combinatorial object growth. Temporary bucket files tự xóa. Generic streaming buffer có `max_payloads`, heap-based settle/expiry và bounded consumed cache; chưa có live soak nên không claim realtime CPU/latency production.

## Tests

- Test Phase 10B mới: **18**.
- Toàn project: **125/125 PASS**.
- Solver/localizer/tracker/API tests giữ nguyên.

## File thay đổi

- thêm `realtime/nrx_association.py`;
- sửa `realtime/clock_sync.py`;
- sửa `realtime/modes/association.py` thành compatibility wrapper;
- sửa `tools/phase10a_common.py` dùng generic core;
- thêm `tools/phase10b_replay.py`;
- thêm `tests/test_phase10b.py`;
- thêm hai tài liệu Phase 10B;
- tạo artifacts trong `test10b/`.

Không sửa `realtime/config.py`, realtime Mode A/C/Mode-S publish adapters, solver, tracker, API, production services hoặc forwarding.

## Acceptance criteria

| Tiêu chí | Kết quả |
|---|---|
| Generic receiver set | PASS |
| 4RX/5RX representation | PASS |
| One transmission không duplicate quartet | PASS |
| Fixed-4 regression | PASS |
| Mode-S semantics không nới | PASS |
| Mode A/C semantics không nới | PASS |
| Per-receiver T37 clock readiness | PASS |
| Buffer bounded/cleanup | PASS |
| Không combinatorial explosion | PASS |
| Existing + new tests | PASS |
| Solver/tracker/API không đổi | PASS |

## Phase 10C boundary

Phase 10C sẽ dùng `receiver_ids`, `observations_by_receiver`, `receiver_count` và `normalized_timestamps` từ `TransmissionCluster`. Không tự động bắt đầu Phase 10C trong task này.
