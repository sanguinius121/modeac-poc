# Khoảng cách và hình bố trí receiver MLAT

Phân tích ngày 2026-08-11 cho `/home/mlatserver/modeac-poc`.

## Trả lời trực tiếp

Với polygon giám sát đã cung cấp (span lớn nhất khoảng 493 km), target từ 2.500 m trở lên, antenna receiver từ 30 m và RF hữu dụng giả định 300–350 km, khuyến nghị thực dụng là:

| Loại baseline | Khoảng cách khuyến nghị cho project này | Vai trò |
|---|---:|---|
| Quá gần đối với geometry chính | `<40–50 km` | Gần redundant khi vùng rộng 300–500 km; vẫn hữu ích cho RF/clock |
| Ngắn nhưng hữu ích | `50–120 km` | Center–perimeter, overlap, clock density, redundancy |
| Baseline chính | `150–250 km` | Các cạnh perimeter và góc cắt chính |
| Baseline dài hữu ích | `250–350 km` | Đường chéo/đường kính để phá mirror và giảm sensitivity |
| Bắt đầu có nguy cơ common-RF | `>300 km` nếu RF thực gần 300 km; `>350 km` nếu đạt 350 km | Phải đo common reception |
| Không nên dùng làm strict-4 mặc định | `>400 km` chưa có RF evidence; đặc biệt `500–600 km` | Geometry vẫn đẹp nhưng giao RF giảm mạnh |

Đây không phải ranh giới vật lý cứng. `scale/span` trong simulation là khoảng cách lớn nhất giữa hai receiver. Layout tốt nhất trên polygon thực có span 300 km và sáu baseline `175, 196, 205, 225, 264, 300 km`. Hình vuông span 300 km có bốn cạnh 212 km và hai đường chéo 300 km. Đây là bằng chứng trực tiếp cho sweet spot `150–250 km` ở các cạnh và `250–350 km` ở một hoặc hai baseline dài.

Hình bố trí nên là **bốn receiver perimeter đa hướng, gần square/diamond hoặc polygon bất quy tắc cân bằng**, không cần vuông đều. Không đặt bốn trạm gần một đường. Với 5RX, cấu hình cân bằng nhất cho strict 4-of-5 là **4 perimeter + 1 center/near-center**. Với 6RX, dùng **5 perimeter bất quy tắc + 1 center**, hoặc 4 perimeter + 2 inner sites tách nhau nếu site biển hạn chế.

Lưu ý: backend realtime hiện tại mới triển khai strict 4RX trên đúng bốn receiver. `4-of-5`, `4-of-6`, weighted subset và full-N consensus dưới đây là **kiến trúc đề xuất**, chưa được implement hoặc acceptance-test trong production pipeline.

## Phạm vi và ba loại bằng chứng

**MEASURED** là số liệu Test 6–10/capture thật. **SIMULATED** là Jacobian/Monte Carlo không dùng ADS-B truth. **ENGINEERING RECOMMENDATION** kết hợp hai nguồn để thiết kế deployment; không phải cam kết RF hay accuracy.

Vùng mục tiêu:

```text
P1 21.774082, 107.742854
P2 21.687485, 110.065637
P3 18.911860, 109.677212
P4 19.220238, 106.142541
```

Tâm phép chiếu khoảng `20.3984N, 108.4071E`; bốn cạnh xấp xỉ 243/311/370/329 km; đường kính lớn nhất 493 km. Grid chính có 232 điểm cách nhau 20 km, target altitude 2.500 m. Candidate ngoài biển chỉ là geometry synthetic; báo cáo không khẳng định có đảo/site Việt Nam khả dụng tại điểm đó.

## 1. Khoảng cách theo kích thước vùng giám sát

### SIMULATED

Các vùng vuông synthetic cho kết quả tốt nhất dưới RF proxy 350 km:

| Kích thước vùng | Span receiver tốt | Tỷ lệ span/vùng | Cạnh square tương ứng | Ghi chú |
|---:|---:|---:|---:|---|
| 100 km | khoảng 100 km | 1,00 | khoảng 71 km | RF chưa là nút thắt |
| 200 km | khoảng 200 km | 1,00 | khoảng 141 km | 4 perimeter phù hợp |
| 300 km | khoảng 250–300 km | 0,83–1,00 | khoảng 177–212 km | sweet spot rộng |
| 400 km | khoảng 300 km | 0,75 | khoảng 212 km | RF 350 km đã giới hạn; score chỉ còn 0,67 |

Rule-of-thumb từ simulation:

```text
Nếu vùng ≤300 km:
    maximum baseline ≈ 0,8–1,0 × kích thước vùng
    cạnh/perimeter chính ≈ 0,55–0,75 × kích thước vùng

Nếu vùng khoảng 400 km hoặc lớn hơn:
    không tiếp tục scale bốn receiver theo tỷ lệ 1:1
    giữ baseline chính khoảng 150–250 km
    giữ baseline dài khoảng 250–350 km
    tăng số receiver và dùng 4-of-N
```

Với vùng 400 km, kéo span lên 400–500 km cải thiện condition nhưng làm common-RF giảm; thêm receiver tốt hơn kéo bốn trạm ra xa vô hạn.

### ENGINEERING RECOMMENDATION

- Vùng 100 km: baseline cạnh khoảng 60–100 km, maximum baseline khoảng 100–150 km; center không bắt buộc nếu 4 perimeter thu tốt.
- Vùng 200 km: cạnh khoảng 120–180 km, đường chéo khoảng 180–250 km; một center trở nên hữu ích khi có 5RX.
- Vùng 300 km: cạnh khoảng 170–230 km, baseline dài khoảng 250–320 km.
- Vùng 400 km: giữ các baseline khoảng 180–250 km và đường kính 300–350 km; dùng 5–6 receiver để phủ vùng thay vì bốn baseline 500 km.

## 2. So sánh năm hình 4RX

Các hình đều được xoay mỗi 15° và chọn orientation có deployment score tốt nhất. Score diagnostic là:

```text
geometry-good fraction
× all-four-within-350-km fraction
× branch-safe fraction
```

`geometry-good` ở đây nghĩa là Monte Carlo P95 @0,25 µs không quá 1 km và condition không quá 30. Đây không phải xác suất detection đo được.

### A. Square/near-square

```text
RX1 -------- RX2
 |            |
 |   TARGET   |
 |            |
RX3 -------- RX4
```

Span 300 km: cạnh 212 km, P90 của Monte Carlo P95 409 m, condition P90 3,59, RF350 fraction 98,7%, hull fraction 48,3%. Đây là layout canonical tốt nhất: hai trục cân bằng và hai đường chéo dài.

### B. Rectangle dài 2:1

Span 300 km: P90 630 m, condition P90 5,36, RF350 100%, hull 38,8%. Nó tốt nếu surveillance corridor dài rõ rệt và trục dài đặt đúng hướng, nhưng yếu hơn theo trục ngắn.

### C. Triangle lớn + center

Span tối ưu 250 km: P90 459 m, condition P90 3,44, RF350 97,8%, hull 31,0%. Ba perimeter vẫn tạo triangle tốt; center cung cấp phương trình thừa và common reception. Tuy nhiên hull nhỏ hơn bốn perimeter.

### D. Linear

```text
RX1 --- RX2 -------- RX3 -------- RX4
```

Không chấp nhận. Dù local Jacobian đôi lúc hữu hạn ở một phía của đường, phản xạ target qua đường receiver cho cùng khoảng cách và tạo exact mirror. Simulation gán branch-safe bằng 0; span 300 km vẫn có P90 khoảng 1,16 km trước khi phạt mirror.

### E. Irregular polygon đa hướng

Layout tốt nhất span 300 km có baseline 175–300 km, P90 493 m, condition P90 4,07, RF350 99,1%, hull 42,2%. Nó đạt deployment score cao nhất 0,991, nhỉnh hơn square 0,987 vì orientation phù hợp polygon thực.

### Xếp hạng

Pure horizontal geometry: **near-square/diamond ≈ irregular cân bằng > triangle+center ≈ rectangle hợp hướng >>> linear**.

Kết hợp geometry và RF trên polygon này: **irregular cân bằng ≈ square/diamond ≈ rectangle hợp hướng > triangle+center >>> linear**. Chênh lệch bốn cấu hình đầu nhỏ hơn nhiều so với tác hại của layout thẳng hàng hoặc scale sai.

## 3. Có cần hình vuông đều không?

Không. Điều solver cần là:

- các vector nhìn tới receiver trải trên nhiều azimuth;
- hai singular value của Jacobian không chênh quá lớn;
- có ít nhất một phương trình TDOA thừa để loại nhánh;
- target nằm trong hoặc gần hull của subset thực sự thu được;
- baseline dài nhưng vẫn còn common RF.

Square và diamond chỉ khác nhau bởi rotation khi surveillance region đối xứng. Trên polygon bất quy tắc, orientation làm kết quả hơi khác. Một polygon có baseline `120/180/240/320 km` có thể tốt hơn square cạnh 150 km nếu các baseline đó mở đúng các hướng thiếu và vẫn thu chung. Nó cũng có thể xấu hơn nếu ba receiver gần thẳng hàng; danh sách khoảng cách không đủ, phải xem cả azimuth/Jacobian.

## 4. Perimeter hay center?

### Với 4 receiver

**ENGINEERING RECOMMENDATION:** ưu tiên 4 perimeter nếu geometry và RF cho phép. Nó mở hull lớn và vẫn còn ba TDOA độc lập. Triangle+center là phương án thực dụng khi perimeter thứ tư khó thu chung, nhưng không bao vùng tốt bằng bốn perimeter.

Do pipeline hiện tại là strict 4RX, center không tạo redundancy chống mất trạm: mất bất kỳ receiver nào vẫn không có output realtime. Center chỉ giúp clock/common reception và geometry residual.

### Với 5 receiver

`4 perimeter + 1 center` là layout cân bằng nhất cho strict 4-of-5:

- mất center: còn square/irregular 4-perimeter mạnh;
- mất một perimeter: còn triangle lớn + center, vẫn có phương trình thừa;
- center thường nhận nhiều frame hơn, giúp clock calibration density;
- không bắt mọi event phải có 5/5, tránh giảm yield.

Năm perimeter có hull lớn hơn nhưng common intersection nhỏ hơn. Nó phù hợp nếu mọi site có RF rất tốt; chưa phù hợp với evidence hiện tại về QK4/common reception.

Việc đưa layout này vào vận hành đòi hỏi mở rộng associator từ danh sách bốn trạm cố định sang 4-of-N và tạo test mới; chỉ lắp receiver thứ năm không làm code hiện tại tự động sử dụng nó.

## 5. Vì sao T37–Cái Chiên 18 km quá gần?

18 km không luôn quá gần. Nó phải được so với kích thước vùng:

- Vùng 30 km: tỷ lệ `18/30 = 0,60`; đây có thể là baseline chính hữu ích.
- Vùng 100 km: tỷ lệ 0,18; vẫn đóng góp nhưng không nên là một trong các baseline duy nhất.
- Vùng 300 km: tỷ lệ 0,06; hai receiver nhìn gần như cùng hướng đối với phần lớn target và gần redundant về geometry.
- Polygon hiện tại 493 km: tỷ lệ 0,037.

**MEASURED:** T37–Cái Chiên có common DF17/clock rất mạnh: Test 6 có 4.596 geometry samples, holdout p95 0,203 µs và 114.827 Mode A/C pair associations. Nhưng Test 7C cho combination T37+Cái Chiên+Bạch Long Vĩ condition 22,2 và hai competitive branches; các combination có QK4+Bạch Long Vĩ chỉ khoảng 5,2–5,6.

Rule thực dụng: geometry-critical baseline không nên thấp hơn khoảng `0,15–0,20 ×` kích thước vùng; baseline `0,4–0,8 ×` thường hữu ích hơn. Receiver gần hơn vẫn có thể giữ làm center/clock/coverage node.

## 6. Baseline 300–400 km

### Vì sao tốt

QK4–T37 375 km và QK4–Cái Chiên 360 km tạo cánh Tây Nam rất khác hướng so với cụm Đông Bắc. Chúng làm TDOA thay đổi mạnh hơn theo dịch chuyển target và tăng branch discrimination. Chúng tốt nhất khi target nằm giữa hoặc gần vùng nối QK4 với cụm T37/Cái Chiên/Bạch Long Vĩ.

Chúng xấu dần khi target đi xa về một phía của tất cả receiver, hoặc khi QK4 không cùng thu được transmission. Geometry của một baseline không có dữ liệu là bằng không.

### MEASURED common reception

Test 6 cho thấy pair association Mode A/C:

- T37–Cái Chiên 18 km: 114.827;
- T37–QK4 374 km: 3.448;
- QK4–Bạch Long Vĩ 265 km: 722.

Khác biệt còn chứa antenna, receiver sensitivity, traffic và site—not distance alone. Nhưng 5 phút Test 6 có 133.403 cluster 2RX, 4.273 cluster 3RX và chỉ 8 cluster 4RX. Test 7H/H2 sau cải thiện có 68/81 strict 4RX trong 10 phút. Mode-S Test 8 có 540 strict DF17 4RX so với 9.685 3RX và 48.879 2RX; non-position Mode-S có 649 4RX so với 13.150 3RX và 74.087 2RX. Common reception rõ ràng là nút thắt thực.

### SIMULATED RF trade-off trên polygon mới

| Layout gần square/irregular | Geometry-good | All-4 ≤300 km | All-4 ≤350 km | Deployment score 350 |
|---:|---:|---:|---:|---:|
| span 250 km | 95,7–97,4% | 93–94% | 99,6–100% | 0,96–0,97 |
| span 300 km | 100% | 81–85% | 98,7–99,1% | 0,99 |
| span 400 km | 100% | 36–47% | 85–89% | 0,85–0,89 |
| span 500 km | 100% | 10–15% | 40–50% | 0,40–0,50 |

Vì vậy 300 km là sweet spot theo giả định RF 350 km. Nếu RF thực chỉ đạt gần 300 km, 250 km an toàn hơn. Không có evidence cho thấy 500–600 km sẽ vận hành tốt hơn; muốn dùng baseline đó cần receiver bổ sung và 4-of-N, không phải strict 4RX.

## 7. Mạng hiện tại trên polygon mục tiêu mới

### SIMULATED

Mạng hiện tại có maximum span 375 km nhưng lệch về phía Tây polygon:

- target trong hull: 15,1%;
- condition median/P90: 7,39/23,0;
- Monte Carlo P95 @0,25 µs median/P90: 1,03/4,29 km;
- all-four within 300/350 km: 32,3%/48,3%;
- geometry-good fraction: 48,3%;
- diagnostic deployment score 350: 0,233.

Điều này không phủ định các kết quả tốt đã đo quanh vùng bay hiện tại. Nó cho thấy polygon mới kéo xa tới 110°E nên bốn receiver hiện hữu không phải layout tối ưu cho toàn polygon.

### Layout 4RX lý tưởng nếu được di chuyển tự do

```text
                         NORTH
                           ● RX-N
                         /       \
                        / TARGET  \
        WEST  RX-W ●---/   AREA    \---● RX-E  EAST/ISLAND
                       \           /
                        \         /
                           ● RX-S
                         SOUTH

Adjacent/perimeter baselines: khoảng 170–230 km
One or two long diagonals:     khoảng 250–320 km
Maximum span mục tiêu:         khoảng 300 km
```

Không buộc bốn điểm tạo diamond đều. Nên dịch các đỉnh theo site/đảo Việt Nam khả dụng, miễn polygon vẫn đa hướng và không tạo góc rất nhọn hoặc ba điểm gần thẳng hàng.

## 8. Cấu hình 5 receiver lý tưởng

```text
                         RX-N
                       /      \
              RX-W --- RX-C --- RX-E/island
                       \      /
                         RX-S
```

- Bốn perimeter tạo maximum span khoảng 280–350 km.
- Baseline perimeter kề nhau khoảng 150–250 km.
- Center–perimeter khoảng 80–180 km.
- Target ưu tiên nằm trong hoặc gần perimeter polygon; center nằm gần vùng có traffic/common messages cao, không cần đúng tâm hình học.
- Association: 4-of-5; chấm condition và clock sigma cho từng subset, không strict-5 mặc định.

Subset khi mất site:

- mất center → 4 perimeter mạnh nhất;
- mất Bắc/Nam/Đông/Tây → triangle perimeter còn lại + center;
- nếu mất site phía East, accuracy phía Đông giảm và phải phản ánh bằng condition/uncertainty;
- nếu mất site clock xấu, weighted best-4 có thể tốt hơn full-5.

MongCai có thể làm perimeter/near-perimeter Đông Bắc cho coverage, nhưng vì gần T37/Cái Chiên, nó không thay thế RX-E ngoài biển hoặc RX-W diversity.

## 9. Cấu hình 6 receiver lý tưởng

```text
                           RX-N
                       /           \
              RX-NW/W ●             ● RX-E/NE
                       \    RX-C   /
                        \    ●    /
              RX-SW/W ●             ● RX-SE/island
                       \           /
                           RX-S
```

Thực dụng nhất là năm perimeter bất quy tắc + một center. Perimeter adjacent khoảng 120–220 km, các đường chéo 250–350 km, center–perimeter khoảng 80–180 km. Với site đảo hạn chế, có thể dùng bốn perimeter + hai inner nodes lệch nhau theo Đông–Tây; không đặt hai inner cùng vị trí hoặc cùng đường với perimeter.

Pipeline nên dùng best 4-of-6/weighted subset, full-5/6 consensus khi có dữ liệu, và leave-one-out consistency để phát hiện receiver lỗi. Không yêu cầu strict-6.

## 10. Altitude và timing

### SIMULATED

Với irregular span 300 km tốt nhất, P90 Monte Carlo P95 @0,25 µs gần như không đổi: 493/491/492/491 m ở altitude 2,5/5/10/12 km. Horizontal geometry ổn định trong dải target yêu cầu; kết luận spacing chủ yếu do horizontal layout và RF.

Tại altitude 2.500 m, median/P90 P95 theo timing noise là:

| Noise mỗi receiver | Median P95 | P90 P95 |
|---:|---:|---:|
| 0,1 µs | 77 m | 197 m |
| 0,25 µs | 192 m | 493 m |
| 0,5 µs | 384 m | 986 m |
| 1,0 µs | 768 m | 1.971 m |

`c×1 µs≈300 m` chỉ là path difference; geometry nhân hoặc giảm sensitivity. Clock quality vẫn phải gate độc lập.

## 11. Cân bằng geometry và strict yield

Một metric vận hành nên có dạng:

```text
deployment_score = geometry_quality
                 × measured_common_reception_probability
                 × clock_availability
                 × receiver_uptime
```

Simulation hiện chỉ thay `measured_common_reception_probability` bằng fraction khoảng cách 300/350 km. Trước deployment cần capture thử tại candidate site và tính:

- tỷ lệ transmission xuất hiện ở từng 4-of-N subset;
- strict event/phút theo Mode A/C và từng DF Mode-S;
- clock common samples/phút và p95 từng link;
- geometry condition/P95 prediction của chính các target/subset thu được;
- uptime, packet loss, terrain/antenna pattern.

Mục tiêu “yield không thấp hơn strict 4RX hiện tại” phải được kiểm bằng event/phút trong cùng traffic window. Không thể suy ra probability thật chỉ từ khoảng cách.

## Quy tắc thiết kế mạng receiver MLAT cho project này

1. Không dùng receiver cách nhau `<40–50 km` làm hai đỉnh geometry chính cho vùng rộng 300–500 km.
2. Baseline cạnh chính nên `150–250 km`; giữ một hoặc hai đường chéo `250–350 km`.
3. Với RF 300–350 km, maximum span khoảng `250–300 km` là sweet spot 4RX; trên `350–400 km` phải đo common reception và ưu tiên 4-of-N.
4. Đặt target trong hoặc gần polygon đa hướng; tránh ba receiver gần thẳng hàng.
5. 4RX: bốn perimeter near-square/diamond hoặc irregular cân bằng.
6. 5RX: bốn perimeter + một center, association 4-of-5.
7. 6RX: năm perimeter + một center, hoặc bốn perimeter + hai inner sites tách hướng.
8. Vùng 100/200/300 km: maximum span xấp xỉ 100/200/250–300 km.
9. Vùng 400 km: không kéo 4RX tới 500 km; dùng span khoảng 300–350 km và thêm receiver.
10. Receiver gần vẫn đáng giữ cho clock/RF redundancy, nhưng không được tính như một đỉnh hull độc lập.

## Trả lời 10 câu bắt buộc

1. **Receiver nên cách nhau bao nhiêu?** Cạnh chính 150–250 km; baseline dài 250–350 km; maximum span mục tiêu khoảng 300 km cho polygon/RF đã cho.
2. **Khoảng cách tối thiểu cần tránh?** Tránh `<40–50 km` giữa các geometry-critical receivers; theo tỷ lệ, tránh dưới khoảng 0,15–0,20 kích thước vùng.
3. **Khoảng cách tối đa thực dụng?** Khoảng 300–350 km với RF giả định hiện tại. Trên 400 km chưa phù hợp strict-4 nếu chưa đo chứng minh.
4. **4 receiver bố trí gì?** Bốn perimeter tạo near-square/diamond hoặc polygon bất quy tắc đa hướng cân bằng.
5. **Có cần vuông đều?** Không; azimuth diversity, hull, condition và common reception quan trọng hơn độ đều tuyệt đối.
6. **3 perimeter + center hay 4 perimeter?** Với 4RX, 4 perimeter tốt hơn cho coverage geometry; triangle+center là phương án RF/clock thực dụng nhưng hull nhỏ hơn.
7. **5 receiver?** 4 perimeter + 1 center, dùng strict 4-of-5/best subset.
8. **6 receiver?** 5 perimeter bất quy tắc + 1 center; nếu site hạn chế, 4 perimeter + 2 inner tách hướng.
9. **Khi vùng tăng 100→400 km?** Span tăng gần tỷ lệ 1:1 tới khoảng 300 km, sau đó bị giới hạn bởi RF; tăng số receiver thay vì tiếp tục kéo baseline.
10. **Ba nguyên tắc cần nhớ?** Bao vùng bằng nhiều hướng; dùng cạnh 150–250 km và đường chéo 250–350 km; tối ưu `geometry × common reception`, không tối ưu geometry riêng.

## Artifacts và tái lập

- `tools/receiver_layout_simulation.py`
- `geometry/layout-comparison.csv`
- `geometry/layout-scale-comparison.csv`
- `geometry/layout-comparison.png`
- `geometry/layout-comparison-map.html`
- `geometry/layout-comparison-summary.json`

Chạy lại:

```bash
cd /home/mlatserver/modeac-poc
OPENBLAS_NUM_THREADS=1 python3 tools/receiver_layout_simulation.py --output-dir geometry
```

Không có production service, solver realtime, association, forwarding hoặc tar1090 nào bị sửa trong công việc này.
