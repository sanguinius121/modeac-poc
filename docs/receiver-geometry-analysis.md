# Phân tích bố trí receiver cho pipeline MLAT/TDOA hiện tại

Ngày phân tích: 2026-08-11. Project: `/home/mlatserver/modeac-poc`.

## Kết luận điều hành

Pipeline realtime hiện tại chỉ công bố vị trí từ **strict 4RX**. Với mạng hiện có, vùng geometry tốt nhất là phần giữa mạng, xấp xỉ `19–21,5°N, 106–108°E`, đặc biệt quanh `20,2°N, 107,3–107,6°E`. Target không bắt buộc nằm trong convex hull, nhưng nghiệm bên ngoài hull là ngoại suy và sai số tăng nhanh khi các hướng nhìn tới receiver trở nên gần song song.

Điểm yếu cấu trúc lớn nhất là T37 và Cái Chiên chỉ cách nhau 18,3 km. Cái Chiên còn nằm bên trong tam giác T37–QK4–Bạch Long Vĩ, nên nó tăng khả năng thu chung và redundancy nhưng gần như không mở rộng hull. QK4 cung cấp baseline Tây Nam dài 360–375 km; Bạch Long Vĩ cung cấp hướng biển và các baseline 132–265 km. Hai trạm này tạo phần lớn diversity cần để phá mirror branch.

Nếu chỉ thêm một receiver vì mục tiêu **geometry**, ưu tiên dải Đông/Đông Nam của Vịnh Bắc Bộ, khoảng `19–20°N, 108,3–108,9°E`, sau khi khảo sát RF/site thực tế. Nếu thêm hai receiver, thêm tiếp một trạm Tây/Tây Bắc khoảng `21–22°N, 104,7–105,4°E`. MongCai đáng bổ sung cho coverage/redundancy Đông Bắc nếu triển khai thuận lợi, nhưng vì chỉ cách T37 18,6 km và Cái Chiên 31,2 km nên không thay thế được một site diversity ở Đông/Đông Nam hoặc Tây/Tây Bắc.

Phân biệt bằng chứng trong báo cáo:

- **Đo thực tế**: Test 6–10 và capture đã đóng băng.
- **Simulation**: Jacobian/Monte Carlo/grid không dùng ADS-B truth.
- **Suy luận triển khai**: có điều kiện; cần khảo sát antenna, địa hình, nhiễu, đường truyền và common reception trước khi chọn site.

## 0. Toàn bộ pipeline đang được phân tích

```text
Beast TCP 29996–29999
        │
        ├─ parser + corrected 12 MHz timestamp
        │
        ├─ DF17 even/odd → vị trí calibration → 6 clock-link models
        │                                  │
        │                                  └─ slope, offset, p95/sigma, quality
        │
        ├─ Mode A/C Type-1 ── exact raw code + normalized time ── strict 4RX
        │                                                        │
        │                                                        └─ altitude-grid 2D solver
        │
        └─ Mode-S Type-2/3 ── exact payload + normalized time ── strict 4RX
                                                                 │
                                                                 └─ altitude-grid 2D solver
                                                                         │
                                          anonymous Mode A/C tracker / ICAO Mode-S tracker
                                                                         │
                                                        REST + WebSocket → diagnostic maps
```

- Inputs cố định: T37/29996, QK4/29997, Cái Chiên/29998, Bạch Long Vĩ/29999.
- Clock calibrator chỉ dùng DF17 airborne có CPR even/odd giải được. Nó trừ propagation geometry theo vị trí DF17, ghép cùng payload trong khoảng 0,2 s và fit slope/offset cho cả sáu cặp. Mỗi link giữ tối đa 2.000 mẫu; dưới 100 mẫu là `UNAVAILABLE`; p95 `<1/<5/<10/>=10 µs` tương ứng `STRONG/PASS/MARGINAL/BAD`.
- T37 là miền timestamp quy ước: ba trạm khác được biến đổi trực tiếp về T37 để tránh chain nhiều clock fit. Cả sáu link vẫn được dùng làm sigma/chẩn đoán. Đây không phải clock tuyệt đối và không làm T37 tốt hơn về vật lý.
- Mode A/C ghép cùng raw Type-1, yêu cầu đủ bốn trạm, candidate duy nhất theo thời gian, reciprocal-nearest và mọi TDOA nằm trong physical baseline cộng margin runtime 10 µs. Cùng squawk không được coi là cùng aircraft; tracker vẫn anonymous.
- Mode-S ghép cùng raw payload, physical/reciprocal gate tương tự với margin 3 µs. DF11/17 có ICAO trực tiếp; identity khôi phục từ parity chỉ được tin sau khi ICAO đó từng xuất hiện trực tiếp. Realtime mặc định chỉ publish DF4/5/11/20/21; DF17 public MLAT vẫn tắt.
- Mode A/C dùng một solver thread; Mode-S dùng ba process và queue 64 event, bỏ work Mode-S cũ hơn 3 s. Hai pipeline có tracker, queue, REST và WebSocket riêng.
- Test 9 và overlay tar1090 Test 10 chỉ tiêu thụ output. Chúng không tác động clock, association, solver, branch selection hoặc production readsb/mlat-server.

## 1. Pipeline và điều kiện tối thiểu

### Pipeline thực tế

Mỗi frame đi qua `clock.process()` trước, sau đó vào association Mode A/C hoặc Mode-S. Timestamp các trạm được đưa về miền T37. Association hiện tại yêu cầu cùng transmission tại đủ bốn trạm, reciprocal-nearest và nằm trong giới hạn truyền sóng vật lý. Event strict 4RX mới được đưa vào solver.

Solver được chấp nhận không cố solve 3D tự do. Nó chạy bài toán ngang 2D trên lưới độ cao `0–45.000 ft`, dùng toàn bộ sáu hiệu TDOA, residual có trọng số theo p95 clock, gom các nghiệm cách nhau dưới 25 km thành family, rồi phân loại `BLIND_UNIQUE`, `BLIND_MULTIPLE` hoặc `BLIND_INCONSISTENT`.

### Bao nhiêu receiver là đủ?

- Với **2D và độ cao đã biết**, ba receiver tạo hai TDOA độc lập cho hai ẩn ngang. Đây chỉ là nghiệm vừa đủ, không có phương trình thừa để kiểm tra nhánh sai hoặc lỗi timing.
- Receiver thứ tư tạo ba TDOA độc lập cho hai ẩn ngang. Phương trình thừa là residual kiểm chứng: một nhánh mirror có thể khớp hai phương trình của 3RX nhưng thường không khớp receiver thứ tư.
- Với **3D tự do**, bốn receiver chỉ tạo ba phương trình độc lập cho ba tọa độ và vẫn không có redundancy. Geometry gần đồng phẳng làm thành phần đứng cực yếu. Test 7A cho thấy điều này không vận hành được một cách tin cậy.
- Vì vậy, tối thiểu toán học là 3RX cho 2D có altitude; nhưng tối thiểu của **pipeline hiện hành và mức tin cậy đã kiểm chứng là 4RX**.

Ba receiver thường có mirror branch vì hai hyperbola có thể giao nhau ở nhiều vị trí. Khi chỉ có đúng hai phương trình cho hai ẩn, cả nghiệm thật và nghiệm phản chiếu có thể có residual gần bằng 0. Receiver thứ tư nhìn target từ một hướng khác và biến câu hỏi thành “nhánh nào đồng thời giải thích được cả ba hiệu độc lập?”.

Test 8B là bằng chứng mạnh: 3RX cộng altitude thử 3.029 event, có 3.019 `ALT_3RX_MULTIPLE`; sai số post-hoc P50/P95 là 41/411 km. Nhánh này vì thế bị tắt trong realtime. Ngược lại, strict 4RX Mode-S có 646/649 unique, và nhánh đóng băng gần truth nhất trong 643/643 trường hợp được đánh giá.

### Có bắt buộc target nằm trong polygon?

Không. Solver vẫn chạy ngoài polygon nếu TDOA hợp lệ. Nhưng bên trong hull, thay đổi vị trí target thường làm các khoảng cách tới receiver thay đổi theo nhiều hướng khác nhau. Bên ngoài và càng xa mạng, các tia từ target tới receiver gần song song; di chuyển target một đoạn lớn chỉ làm vector TDOA thay đổi rất ít. Khi đó cùng một lỗi timing gây sai số ngang lớn hơn, condition tăng và các nhánh xa khó phân biệt.

Đây là khác biệt giữa nội suy và ngoại suy, không phải một ranh giới cứng. Có vùng ngoài hull vẫn tốt nhờ baseline dài và góc cắt thuận lợi; cũng có điểm gần receiver nhưng xấu nếu receiver gần thẳng hàng.

## 2. Geometry của bốn receiver hiện tại

| Cặp receiver | Khoảng cách simulation |
|---|---:|
| T37 – Cái Chiên | 18,3 km |
| Cái Chiên – Bạch Long Vĩ | 132,2 km |
| T37 – Bạch Long Vĩ | 150,6 km |
| QK4 – Bạch Long Vĩ | 264,9 km |
| QK4 – Cái Chiên | 359,9 km |
| QK4 – T37 | 374,9 km |

Các con số Test 6 dùng phép tính ECEF là 18,2; 131,7; 149,9; 264,8; 359,1 và 374,0 km, sai khác nhỏ do cách tính khoảng cách.

Convex hull thực tế chỉ có ba đỉnh `T37 – QK4 – Bạch Long Vĩ`, diện tích xấp xỉ 15.814 km² theo phép chiếu địa phương. Cái Chiên nằm bên trong tam giác đó. Vì vậy:

- **T37 + Cái Chiên**: baseline rất ngắn, hướng gần Bắc–Nam; TDOA giữa chúng nhỏ và hai hàng Jacobian nhìn từ xa gần trùng thông tin. Cặp này rất tốt cho số lượng common messages và clock: Test 6 có 4.596 geometry sample, holdout p95 0,203 µs và 114.827 Mode A/C pair association. Nhưng nó không thay thế được một baseline chéo dài.
- **QK4**: tạo cánh Tây Nam và hai baseline dài nhất. Nó cải thiện rank/branch rất mạnh, nhưng lượng thu thấp và clock từng suy giảm. Test 6 chỉ có 825/340 geometry sample trên liên kết T37–QK4/Cái Chiên–QK4; Test 7H có p95 clock 6,89/5,50/8,81 µs trên các link liên quan QK4.
- **Bạch Long Vĩ**: tạo hướng ngoài biển, tách khỏi đường T37–Cái Chiên và làm baseline QK4–Bạch Long Vĩ dài 265 km. Nó đặc biệt quan trọng cho góc cắt Đông–Tây.

Test 7C tại một event truth độc lập xếp condition 3RX:

| Combination | Condition 2D | Competitive branch |
|---|---:|---:|
| T37 + QK4 + Bạch Long Vĩ | 5,18 | 1 |
| Cái Chiên + QK4 + Bạch Long Vĩ | 5,58 | 1 |
| T37 + Cái Chiên + QK4 | 19,6 | 1 |
| T37 + Cái Chiên + Bạch Long Vĩ | 22,2 | 2 |

Test 7F đo được cùng xu hướng: T37+QK4+Bạch Long Vĩ usable 50/52, P90 156 m; T37+Cái Chiên+QK4 usable 53/66 sau track assist, P90 890 m; T37+Cái Chiên+Bạch Long Vĩ có 716 candidate nhưng chỉ 5 track-usable trong chính sách độc lập, P90 397 m trên tập rất nhỏ. Combination Cái Chiên+QK4+Bạch Long Vĩ có P90 110 m nhưng chỉ ba event, không đủ để khẳng định tổng quát.

Kết luận: QK4 và Bạch Long Vĩ cùng xuất hiện trong hai combination có condition tốt nhất. T37/Cái Chiên chủ yếu tạo redundancy và density; dùng cả hai mà thiếu QK4 hoặc thiếu góc biển dễ tạo geometry hẹp.

## 3. Vùng hoạt động của mạng hiện tại

Simulation quét 2.346 điểm từ `17,5–22,5°N`, `104,5–109°E`, altitude 10 km. Phân loại dùng Monte Carlo P95 với 0,25 µs/receiver, condition và khoảng cách TDOA tới một điểm xa hơn 25 km. Đây là bản đồ geometry, không phải bản đồ RF.

| Vùng simulation | GOOD | GOOD+ACCEPTABLE | Median P95 | P90 P95 |
|---|---:|---:|---:|---:|
| Lõi Vịnh `19–21,5N, 106–108E` | 77,1% | 92,9% | 340 m | 1.040 m |
| Trung tâm rộng `18,8–21,6N, 105,5–108E` | 67,4% | 92,7% | 409 m | 1.070 m |
| Bắc `>=21,5N` | 4,5% | 64,0% | 1.236 m | 8.593 m |
| Nam `<=19,2N` | 1,9% | 29,2% | 2.538 m | 17.939 m |
| Đông `>=107,8E` | 5,1% | 41,9% | 1.917 m | 8.478 m |
| Tây `<=106E` | 12,5% | 72,7% | 968 m | 7.046 m |

Điểm tuyến tính tốt nhất nằm quanh `20,2N, 107,5E`, gần trung tâm Vịnh và giữa các hướng nhìn, với condition khoảng 1,45 và Monte Carlo P95 khoảng 149 m ở 0,25 µs. Không nên đọc một grid point như cam kết accuracy thực địa.

- **Phía Đông ngoài biển**: tốt quanh phần giữa mạng, sau đó xấu nhanh khi target đi quá phía Đông Bạch Long Vĩ; tất cả receiver dần nằm cùng phía Tây của target.
- **Phía Tây đất liền**: geometry trung bình còn khá rộng nhờ QK4 đối với cụm Đông Bắc, nhưng địa hình núi và RF có thể làm coverage thực tế kém hơn mô phỏng.
- **Phía Bắc gần T37/Cái Chiên**: hai receiver rất gần nhau nên target nhìn chúng như một điểm; thiếu baseline phía Bắc/Tây Bắc để tạo góc cắt.
- **Phía Nam gần QK4**: QK4 giúp baseline rất mạnh cho target ở giữa mạng; nhưng khi đi xuống phía Nam QK4, bốn receiver lại dần nằm cùng một phía và geometry giảm.

## 4. Tool và bản đồ simulation

Artifacts:

- [`current-network.csv`](../geometry/current-network.csv): từng grid point, condition, hull, branch-separation và Monte Carlo 0,1/0,25/0,5/1,0 µs.
- [`current-network-heatmap.png`](../geometry/current-network-heatmap.png): heatmap bốn mức.
- [`current-network-map.html`](../geometry/current-network-map.html): Leaflet diagnostic.
- [`current-network-summary.json`](../geometry/current-network-summary.json): khoảng cách, thống kê vùng và altitude.
- [`receiver5-candidates.csv`](../geometry/receiver5-candidates.csv) và [`receiver5-optimization-map.html`](../geometry/receiver5-optimization-map.html): grid search receiver thứ 5.

Chạy lại:

```bash
cd /home/mlatserver/modeac-poc
python3 tools/receiver_geometry_analysis.py --output-dir geometry
python3 tools/receiver_geometry_optimizer.py --output-dir geometry --candidate-step 0.3
```

Metric sử dụng ma trận đạo hàm khoảng cách theo East/North của từng receiver. Thành phần thời gian phát chung được chiếu bỏ trước khi tính singular values/covariance. Monte Carlo thêm nhiễu timestamp độc lập lên receiver rồi tuyến tính hóa nghiệm ngang. `remote_branch_separation` tìm grid point cách ít nhất 25 km có vector sáu TDOA gần nhất.

Ngưỡng `GOOD/ACCEPTABLE/POOR/VERY POOR` là ngưỡng diagnostic được công bố trong JSON, không phải chuẩn an toàn hàng không. Branch search trên grid 0,1° không thay thế multi-start nonlinear solver và có thể bỏ sót nhánh nằm giữa các điểm grid.

## 5. Vì sao nên bao quanh target

Receiver bao quanh target làm gradient của range-difference chỉ theo nhiều hướng. Một dịch chuyển Đông–Tây và một dịch chuyển Bắc–Nam tạo các dấu/mức thay đổi TDOA khác nhau, nên Jacobian có hai singular value tương đối cân bằng.

Khi target ở ngoài hull, các receiver nằm về cùng một phía. Các hyperbola/hyperboloid gần song song tại target; giao điểm kéo dài thành một dải. Sai số TDOA nhỏ dịch giao điểm rất xa dọc theo dải đó. Receiver thứ tư vẫn có thể phá mirror, nhưng branch margin thường giảm.

Mạng hiện tại minh họa rõ điều này: vùng lõi Vịnh có condition median 3,52, trong khi phía Nam có 13,0 và phía Đông có 12,0. Target không bắt buộc ở giữa bốn receiver, nhưng nên nằm trong hoặc gần hull của **các receiver thực sự cùng thu được transmission**.

## 6. Khoảng cách receiver và common coverage

“Càng xa càng tốt” là sai vì strict 4RX cần giao của bốn vùng phủ RF.

- Baseline quá ngắn như T37–Cái Chiên 18 km cho TDOA diversity nhỏ đối với vùng rộng hàng trăm km.
- Baseline dài 130–375 km tạo leverage hình học, nhưng receiver xa/yếu có thể không thu cùng transmission.
- Test 6 trong 5 phút có 133.403 cluster 2RX, 4.273 cluster 3RX nhưng chỉ 8 cluster 4RX. Hai capture Test 7H mười phút tăng lên 68 và 81 strict 4RX, vẫn cho thấy giao coverage là nút thắt.
- Với Mode-S trên capture Test 7H: DF17 có 48.879/9.685/540 cluster 2RX/3RX/4RX; non-position Mode-S có 74.087/13.150/649. Geometry 4RX rất tốt khi có event, nhưng phần lớn transmission không hiện diện ở đủ bốn trạm.

Cho vùng giám sát rộng 200–400 km, nên có nhiều thang baseline: một số khoảng 100–200 km để giữ common reception, ít nhất hai baseline chéo khoảng 200–400 km để tạo diversity, và có thể một cặp gần/trung tâm để tăng density/clock/redundancy. Các con số này là tỷ lệ định hướng dựa trên mạng hiện tại, không phải giới hạn RF đã chứng minh.

Không nên đặt tất cả receiver ở giữa: hull nhỏ. Cũng không nên chỉ đặt perimeter rất xa: strict yield thấp và không có receiver “đệm”. Mạng tốt có perimeter đa hướng cộng một hoặc hai site trung tâm/near-core.

## 7. Receiver MongCai

Khoảng cách MongCai: T37 18,6 km; Cái Chiên 31,2 km; Bạch Long Vĩ 159,2 km; QK4 391,0 km. Nó mở hull một ít về Đông Bắc nhưng tạo thêm một receiver trong cụm rất gần T37/Cái Chiên.

Trong grid optimizer, so với mạng 4RX hiện tại trên vùng `18–22N, 105–108,6E`:

- current P90 HRMSE @0,25 µs: 1.938 m;
- MongCai best-4 P90: 1.451 m; full-5 P90: 1.429 m;
- fraction best-4 dưới 1 km: 81,0% → 84,7%;
- fraction target trong hull: 8,3% → 9,3%;
- worst-4 P90: 34 km, cho thấy nếu subset còn lại chủ yếu là cụm Bắc gần nhau thì redundancy geometry vẫn yếu.

MongCai vì thế **có ích nhưng không tạo diversity lớn**. Nó có thể tăng common reception ở Đông Bắc, cho phép thay thế T37 hoặc Cái Chiên trong một số event, cung cấp thêm clock links và leave-one-out checks. Nó ít giúp khi receiver bị mất là QK4 hoặc Bạch Long Vĩ.

Chiến lược 5RX đề xuất:

1. Không yêu cầu strict 5RX cho mọi fix; strict-5 sẽ làm yield phụ thuộc giao RF của cả năm trạm.
2. Thu nhận transmission có ít nhất 4/5 receiver.
3. Chấm điểm từng subset theo clock sigma, condition, predicted covariance và physical consistency.
4. Solve best-4 nhưng đồng thời solve các subset 4RX còn đủ chất lượng.
5. Dùng leave-one-out để phát hiện receiver/timestamp gây residual; không dùng subset chỉ vì residual bằng 0.
6. Nếu có 5/5, ưu tiên weighted full-5 hoặc consensus robust, giữ best-4 làm diagnostic.
7. Công bố receiver set, condition, clock quality và leave-one-out consistency cùng fix.

## 8–9. Nên đặt receiver mới ở đâu và kết quả grid search

Optimizer giữ cố định bốn receiver, quét candidate `17,4–22,8N, 104,4–109,4E` bước 0,3°, đánh giá vùng giám sát `18–22N, 105–108,6E` bước 0,2°, altitude 10 km, noise 0,25 µs. Score gồm best-4 P90, worst-4 P90, fraction dưới 1 km, hull và proxy có ít nhất bốn receiver trong bán kính ngang 350 km. Proxy này không phải propagation model.

### Vùng xếp hạng cao

- **Đông/Đông Nam** khoảng `18–19,2N, 108,3–109,2E`: top grid có best-4 P90 khoảng 377–430 m, full-5 P90 366–411 m, hull coverage 23–36%. Nó mở cạnh biển và bổ sung hướng gần vuông góc với cụm T37/Cái Chiên–QK4.
- **Tây/Tây Bắc** khoảng `21–22,2N, 104,7–105,4E`: best-4 P90 khoảng 477–541 m, hull 27–39%. Nó mở Bắc Bộ đất liền và phá cụm ba receiver phía Đông Bắc.
- **Trung tâm mạng**: tốt cho RF redundancy nhưng cải thiện hull/condition ít hơn; phù hợp làm receiver thứ sáu hơn là site geometry thứ năm duy nhất.
- **Phía Bắc gần MongCai/T37**: giúp coverage địa phương nhưng không đủ góc mới.

Top score tuyệt đối rơi gần `18,0–18,3N, 108,9E`. Không nên hiểu đây là tọa độ phải triển khai: grid chưa biết có đảo/site, antenna horizon, nhiễu, pháp lý hay đường truyền. Khuyến nghị thực địa là chọn một site khả thi trong **dải Đông/Đông Nam**, rồi chạy lại optimizer với visibility mask và dữ liệu RF đo thật.

Nếu chỉ thêm một receiver: ưu tiên Đông/Đông Nam. Nếu site ngoài biển không khả thi hoặc common reception đo được thấp, phương án kế tiếp là Tây/Tây Bắc. Nếu thêm hai: dùng cả hai hướng này; MongCai có thể là receiver redundancy bổ sung, không phải một trong hai site diversity chính.

## 10. Ảnh hưởng altitude

Simulation toàn grid cho linear HRMSE median @0,25 µs gần như không đổi: 530 m ở 1.000 m, 528 m ở 3.000 m, 525 m ở 10.000 m và 526 m ở 12.000 m. P90 thay đổi 3,67/3,63/3,61/3,43 km. Như vậy horizontal differential geometry không biến đổi lớn trong dải altitude này; vị trí ngoài hull vẫn chi phối hơn.

Test 7C thực tế phù hợp: tại cluster 104422, sai altitude ±1 km chỉ dịch nghiệm ngang 14–16 m; ±3 km dịch 38–54 m; condition 2D khoảng 5,06. Nhưng synthetic nhiều vị trí cho thấy sai altitude ±5 km có thể tạo sai số ngang tới vài km. Không được suy rộng một case thuận lợi thành khả năng solve altitude.

Kết luận giữ nguyên: altitude độc lập đáng tin giúp 2D, nhưng 4RX hiện tại không chứng minh được 3D. Test 7A có condition 3D `4,94×10^9` so với 2D 5,06 tại case mạnh, cải thiện gần `9,77×10^8` lần khi khóa altitude.

## 11. Timing phải đi cùng geometry

`c × 1 µs ≈ 300 m` chỉ là sai số range-difference; vị trí ngang còn bị nhân bởi geometry. Monte Carlo ở vùng lõi `19–21,5N, 106–108E` cho median/P90 của P95 horizontal:

| Noise mỗi receiver | Median P95 | P90 của P95 |
|---:|---:|---:|
| 0,1 µs | 136 m | 416 m |
| 0,25 µs | 340 m | 1.040 m |
| 0,5 µs | 681 m | 2.080 m |
| 1,0 µs | 1.361 m | 4.159 m |

Trên toàn grid rộng, các median tương ứng là 415 m, 1.037 m, 2.073 m và 4.146 m; P90 tăng tới 2,75/6,87/13,75/27,49 km. Quan hệ gần tuyến tính vì đây là local sensitivity.

Số đo thực tế cũng cho thấy geometry tốt không cứu được clock xấu. Test 7H có các link QK4 p95 5,5–8,8 µs nên kết quả bị gắn diagnostic clock gate, dù các fix đủ điều kiện vẫn đạt P90 282 m. Test 7H_2 có QK4–Bạch Long Vĩ p95 12,7 µs và chỉ được PARTIAL PASS. Trong live Phase 1, cả sáu link STRONG với max p95 0,509 µs và pipeline tạo 5/5 unique fixes. Không thể so accuracy trực tiếp giữa các traffic window, nhưng phải gate đồng thời clock và geometry.

## 12. Kiến trúc deployment lý tưởng

### Minimum viable

- 4 receiver, strict 4RX.
- Ít nhất ba đỉnh hull thực sự khác hướng; tránh để hai trong bốn site geometry chính cách nhau chỉ vài chục km.
- Altitude-grid/altitude độc lập và clock quality được công bố.
- Phù hợp PoC, nhưng yield và khả năng chịu mất trạm thấp.

### Recommended

- 5 receiver với association 4-of-5.
- Một site Bắc/Đông Bắc, một Tây/Tây Nam, một Nam, một Đông/offshore và một near-core.
- Best-subset có trọng số + full-5 consensus + leave-one-out.
- Với mạng hiện tại, receiver thứ năm nên là East/Southeast diversity; MongCai có thể bổ sung sau cho Northeast availability.

### Ideal redundant

- 6 receiver trở lên: giữ T37, Cái Chiên, QK4, Bạch Long Vĩ; thêm East/Southeast offshore và West/Northwest.
- Nếu MongCai được thêm, cấu hình thành 7RX sẽ tốt hơn về redundancy, nhưng MongCai không loại bỏ nhu cầu hai hướng diversity.
- Association chọn best 4-of-N theo common reception, condition và clock; full-N không bắt buộc.
- Có receiver perimeter để mở hull và receiver trung tâm để tăng yield/clock density.

Trước khi triển khai site mới, cần capture thử đồng thời, đo DF17 common pairs, Type-1/2/3 rates, clock p95, strict 4-of-N yield và heatmap theo **tập receiver thật sự nhìn thấy target**, rồi mới quyết định.

## 13. Trả lời trực tiếp

1. **Bốn receiver hiện tại tốt nhất ở đâu?** Phần giữa Vịnh, khoảng `19–21,5N, 106–108E`, tốt nhất quanh `20,2N, 107,3–107,6E` trong simulation.
2. **Target có bắt buộc nằm giữa bốn receiver không?** Không; ngoài hull vẫn solve được nhưng độ nhạy và ambiguity tăng khi đi xa.
3. **Có nên đặt gần hình vuông/chữ nhật?** Nên tạo polygon rộng, đa hướng và có các góc cắt gần vuông; không cần hình vuông đều theo tọa độ.
4. **Hai receiver quá gần gây gì?** Tạo dữ liệu gần trùng về geometry, TDOA nhỏ, ít mở hull; vẫn hữu ích cho RF/clock/redundancy.
5. **Baseline dài có lợi gì?** Tăng thay đổi TDOA theo vị trí, cải thiện rank, branch margin và giảm horizontal sensitivity.
6. **Khi nào baseline dài bất lợi?** Khi vùng phủ RF chung giảm, clock sample chung ít, target thấp/che khuất hoặc strict-N yield sụt.
7. **MongCai có đáng bổ sung?** Có nếu mục tiêu là coverage/redundancy Đông Bắc và chi phí hợp lý; không phải lựa chọn tối ưu duy nhất cho geometry.
8. **Chỉ thêm một receiver?** Ưu tiên Đông/Đông Nam ngoài biển/rìa Đông Vịnh, khoảng `19–20N, 108,3–108,9E`, sau RF survey.
9. **Thêm hai receiver?** Một Đông/Đông Nam và một Tây/Tây Bắc khoảng `21–22N, 104,7–105,4E`.
10. **Bao nhiêu receiver hợp lý?** 4 là minimum PoC; 5 với 4-of-5 là recommended; 6+ đa hướng là cấu hình hợp lý để tiến tới vận hành có redundancy.

## Giới hạn của kết luận

Simulation không dùng ADS-B truth, đúng yêu cầu chống leakage. Nó cũng không mô hình hóa antenna pattern, terrain, Fresnel, receiver sensitivity, interference, packet loss, network latency hoặc clock oscillator cụ thể. Optimizer dùng altitude 10 km và proxy bán kính 350 km; target thấp sẽ có common coverage nhỏ hơn. Kết quả đo Test 6–10 chỉ đại diện các traffic/capture window đã ghi, không chứng minh performance mọi thời điểm hoặc mọi vùng.

Không có solver, association, service production, receiver forwarding hay frontend production nào bị thay đổi trong phân tích này.
