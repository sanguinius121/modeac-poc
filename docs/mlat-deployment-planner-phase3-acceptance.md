# Phase Tool-3 — Acceptance report

## Kết luận

**PASS cho phạm vi deployment-planning/diagnostic.** Best/worst 4-of-N, robustness, N-1, full-N diagnostic, receiver importance, failure simulation, compact grid và on-demand subset table đã hoạt động. Planner mới đang chạy manual tại `http://100.100.24.4:8095/`. Không triển khai realtime 4-of-N.

## File thay đổi

- `deployment_planner/backend/models.py`
- `deployment_planner/backend/geometry_engine.py`
- `deployment_planner/backend/api.py`
- `deployment_planner/frontend/index.html`
- `deployment_planner/frontend/app.js`
- `deployment_planner/frontend/style.css`
- `tests/test_deployment_planner_phase3.py` (mới)
- `tools/benchmark_planner_phase3.py` (mới)
- hai tài liệu Phase Tool-3 trong `docs/` (mới)

Không file nào dưới `realtime/`, `frontend/` unified map, `tar1090-overlay/`, production service/config hay Beast forwarding bị sửa.

## Test và regression

```text
python3 -m unittest discover -s tests -v
69/69 PASS
```

57 test Phase 1/2/realtime/tar1090 cũ và 12 test Phase Tool-3 đều PASS. Test mới bao phủ C(N,4)=1/5/15/35; eligibility-only subset; best/worst; branch-safe; lexical tie; 5RX leave-one-out; 6/7RX; outline+simulated; single failure; N-1; baseline optional ở mode 4-of-N; full-N; API point; high-N guard; strict backward compatibility và frontend contracts.

Request legacy không có `geometry_strategy` và request explicit `strict_4` cho output giống hệt sau khi bỏ riêng trường runtime. `geometry_core` không bị sửa; representative regression hash đã lưu từ Phase 2 vẫn là:

```text
2d08948f1ecf76017912afc92f9727c2a8131519fff1a5ec618a6fc1226f10c7
```

## Synthetic acceptance

Target đại diện `20.0000, 108.0000`, altitude 2.500 m, simulated radius 500 km:

| Layout | Subsets | Best P95 | Median | Worst P95 | GOOD | N-1 |
|---|---:|---:|---:|---:|---:|---:|
| 4 perimeter + center (5RX) | 5 | 121,8 m | 177,9 m | 183,1 m | 5/5 | YES |
| 5 perimeter + center (6RX) | 15 | 135,2 m | 188,8 m | 220,5 m | 15/15 | YES |

5RX leave-one-out P95: bỏ center 121,8 m; bỏ bốn perimeter lần lượt 176,3 / 177,9 / 182,3 / 183,1 m. Vì vậy perimeter strict-4 vẫn mạnh khi mất center; triangle+center vẫn GOOD khi mất một perimeter, nhưng năm subset không có metric giống nhau.

## Current network và candidate SIMULATED — grid 10 km

Candidate assumptions: RX-East `(20.0,109.0)`, RX-West `(20.0,105.5)`, antenna 30 m, simulated radius 350 km. Đây không phải kết luận RF thực địa.

| Metric | Current strict 4RX | + RX-East = best 4-of-5 | + RX-West = best 4-of-6 |
|---|---:|---:|---:|
| Grid points | 928 | 928 | 928 |
| 4+ RX coverage | 48,81% | 100,00% | 100,00% |
| GOOD best-4 | 23,92% | 67,56% | 67,78% |
| GOOD+ACCEPTABLE best-4 | 43,43% | 88,04% | 88,69% |
| N-1 GOOD survivable | 0% / impossible | 9,27% | 37,07% |
| Median best P95 | 518,1 m | 235,8 m | 213,1 m |
| P90 best P95 | 1.602,7 m | 2.060,5 m | 1.883,4 m |
| Median worst P95 | 518,1 m (single subset) | 850,7 m | 1.249,6 m |
| GOOD worst-4 | 23,92% | 28,02% | 15,30% |
| Subset evaluations | 453 | 2.740 | 7.626 |

P90 best của 5RX cao hơn strict baseline không phải regression: strict chỉ có metric trên 48,81% vùng common reception, còn 4-of-5 mở MLAT ra toàn bộ grid và đưa các edge points mới vào population percentile. So sánh coverage và percentile phải đọc cùng nhau.

RX-West sau RX-East làm median best P95 giảm 9,6%, P90 giảm 8,6%, tăng N-1 thêm 27,80 điểm phần trăm và nâng 5+ coverage từ 48,81% lên 61,64%. Worst median tăng vì 6RX tạo thêm các tổ hợp yếu; đây chính là redundancy diagnostic, không phải subset mà BEST sẽ chọn.

Trong 5RX diagnostic, QK4 critical nhất: median best-P95 ratio khi loại QK4 là **4,60×**; RX-East kế tiếp **2,99×**. Trong fixed current strict-4, cả bốn site đều structurally critical vì mất bất kỳ site nào cũng còn dưới 4 receiver.

Worst-4 ở 6RX grid 10 km: GOOD/ACCEPTABLE/POOR/VERY_POOR = 142/398/304/84 point. Điểm xấu nhất nằm gần cụm T37–CaiChien–BLV (`~20.128,107.736`, worst P95 ~40,6 km), và nhiều điểm biên nam/đông cũng yếu. Nguyên nhân là WORST cố ý chọn các subset gần-redundant/outside-hull; best-4 tại cùng vùng không bị thay bằng subset đó.

## Performance

Các run dùng cùng polygon, altitude 2.500 m, noise 0,25 µs; RX-East/RX-West/RX-North đều **SIMULATED 350 km**. Runtime wall/engine trên server hiện tại:

| RX | Grid | Grid points | Subset evaluations | Runtime |
|---:|---:|---:|---:|---:|
| 5 | 20 km | 232 | 680 | 0,49 s |
| 5 | 10 km | 928 | 2.740 | 1,53 s |
| 5 | 5 km | 3.709 | 10.953 | 6,37 s |
| 6 | 20 km | 232 | 1.896 | 0,98 s |
| 6 | 10 km | 928 | 7.626 | 3,80 s |
| 6 | 5 km | 3.709 | 30.409 | 16,46 s |
| 7 | 20 km | 232 | 4.754 | 2,18 s |
| 7 | 10 km | 928 | 19.056 | 8,85 s |
| 7 | 5 km | 3.709 | 76.091 | 41,18 s |

Grid 10 km còn interactive cho 5/6RX và chấp nhận được với progress indicator ở 7RX. Grid 5 km + 7RX không nên xem là tức thời. UI cảnh báo theo `grid × C(N,4)`; API yêu cầu confirm khi >70 và hard-stop >1000 subset/point.

## UI/manual/API acceptance

- Firefox headless tải trang Phase Tool-3, Leaflet, polygon, bốn marker strict baseline màu xanh và reception circles bình thường.
- `/api/health` live trả `phase=Tool-3`.
- Live `/api/analyze` với current+RX-East, grid 20 km trả 232 point, max 5 subset/point, 680 evaluations.
- Controls best/worst/count/GOOD count/robustness/N-1/importance, failure selector và planning warning có mặt.
- Popup compact và `/api/analyze-point` subset table được contract/integration test.
- Mixed 4 outline + 1 simulated tạo đúng 5 subset tại point eligible; không truy cập station network.
- High-N không truncate; Continue/Cancel + server confirmation hoạt động.

## Production isolation/status

Sau triển khai:

```text
readsb      active
mlat-server active
tar1090     active
30004       LISTEN
30104       LISTEN
```

`modeac-poc` systemd vẫn inactive như trước; planner 8095 là process manual, không autostart. Không restart hoặc sửa production services.

## Trả lời 10 câu cuối

1. BEST rank theo branch-safe → P95 thấp → condition thấp → inside hull → receiver IDs lexical.
2. 5 receiver cùng eligible: `C(5,4)=5` subset/point.
3. 6 receiver: `C(6,4)=15` subset/point.
4. Fixed strict-4: cả bốn đều structurally critical. Trong phép thử 5RX có redundancy, QK4 critical nhất (median degradation 4,60×).
5. RX-East simulated đưa 4+ coverage 48,81→100%, GOOD 23,92→67,56%, median best P95 518→236 m và tạo 9,27% N-1 area.
6. RX-West chủ yếu tăng redundancy: N-1 9,27→37,07%, median/P90 best giảm thêm và 5+ coverage tăng lên 61,64%.
7. N-1: 0% (4RX, impossible) → 9,27% (5RX) → 37,07% (6RX).
8. Có. Worst-4 chỉ GOOD 15,30% ở 6RX và phơi bày subset yếu gần cụm T37/CaiChien/BLV cùng các biên nam/đông; best-4 vẫn tránh chúng.
9. Có: khoảng 1,53 s / 5RX, 3,80 s / 6RX, 8,85 s / 7RX ở 928 point trên server này.
10. Planner đã sẵn sàng làm nền tảng toán/API cho Tool-4 và thiết kế realtime 4-of-N, nhưng production chưa sẵn sàng chỉ nhờ thay đổi này; realtime còn cần clock-health-aware eligibility, association/scheduling, solver và soak validation riêng.
