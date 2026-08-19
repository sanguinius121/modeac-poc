# Phase Tool-3.5 — Báo cáo acceptance

## 1. Kết quả

**PASS.**

Planner đã có giao diện tiếng Việt mặc định, chế độ Cơ bản/Nâng cao, popup hai mức chi tiết, tooltip, glossary và Network Assessment deterministic.

Không triển khai Tool-4. Không thay đổi realtime MLAT, production service, readsb, tar1090, mlat-server, receiver forwarding hoặc port.

## 2. File thay đổi

| File | Thay đổi |
|---|---|
| deployment_planner/backend/assessment.py | Module assessment UX deterministic mới |
| deployment_planner/backend/api.py | Gắn assessment vào Analyze response; health phase 3.5 |
| deployment_planner/backend/geometry_engine.py | Bổ sung P50 và aggregate presentation; không đổi toán/ranking |
| deployment_planner/frontend/index.html | UI tiếng Việt, mode toggle, assessment/help panel |
| deployment_planner/frontend/app.js | Rendering Basic/Advanced, popup, tooltip, assessment |
| deployment_planner/frontend/style.css | Layout và style cho hai mode/panel |
| tests/test_deployment_planner_phase35.py | Test UX, threshold, determinism, dependency và trade-off |
| docs/mlat-deployment-planner-phase35.md | Tài liệu kỹ thuật |
| docs/mlat-deployment-planner-phase35-acceptance.md | Báo cáo này |
| deployment_planner/acceptance/planner-phase35-basic.png | Screenshot Cơ bản |
| deployment_planner/acceptance/planner-phase35-advanced.png | Screenshot Nâng cao |
| deployment_planner/acceptance/planner-phase35-assessment.png | Screenshot assessment |

geometry_core không bị sửa.

## 3. Test

Lệnh:

    python3 -m unittest discover -s tests -p 'test_deployment_planner*.py' -v

Kết quả:

    Ran 58 tests
    OK

Trong đó 45 test Phase Tool-1/2/3 cũ tiếp tục PASS và 13 test Phase Tool-3.5 mới PASS.

Toàn bộ repository test suite cũng đã chạy:

    python3 -m unittest discover -s tests -v
    Ran 82 tests
    OK

Các test realtime, standalone frontend và tar1090 overlay ngoài planner vẫn PASS.

Test mới bao phủ:

- tiếng Việt và Basic default;
- Advanced giữ technical values;
- translation lớp quality;
- mode switch không gọi Analyze;
- byte-deterministic assessment;
- boundary reception/P95/branch/N-1/overall;
- critical receiver;
- deterministic equal-importance tie;
- insufficient sample;
- receiver không tham gia best subset;
- median tốt nhưng P90 xấu;
- best tốt nhưng worst yếu;
- N-1 thấp.

## 4. Regression khoa học

Hash geometry_core trước và sau:

| File | SHA256 |
|---|---|
| coordinates.py | f1caf8349e1130715592eed3003fa8c01e9d34208b3b92d63fb75d4698fa0d6a |
| distance.py | e81dc8a4f7b9f4725ac16d8482cf0e355f0d83f57f867add7f495d24eb74e1ca |
| geometry.py | 053a12cf7d14de67d611708d5b1e32801a0de3038673e0373aca81f2431bda1b |
| hull.py | 410db18eabcf8862f7cc5a7105ee0c556c5bc0e99fafa85ffb9bf73f3f750224 |
| monte_carlo.py | 7c84bf2f9950a082f8381b5970dd7dbd7c25b48e5f9c04ccc2ae8f412f551531 |
| quality.py | dc2d71220511febd4b4e9b33ff0ff63a92886b82481d39f59100bdb7685b4f7c |

Không đổi:

- WGS-84/ECEF;
- Jacobian/projector;
- timing noise;
- 256 deterministic draws và seed;
- P50/P95 math;
- condition;
- branch signature/search;
- branch-safe;
- core quality threshold;
- best/worst ranking;
- N-1;
- receiver importance formula;
- full-N math;
- simulated/outline reception gate.

Scenario regression bên dưới tái tạo đúng số Phase Tool-3 acceptance đã công bố.

## 5. Scenario A — current strict 4RX

Input:

- T37, QK4, Cái Chiên, Bạch Long Vĩ;
- strict selected 4RX;
- polygon mặc định;
- altitude 2.500 m;
- timing noise 0,25 µs;
- grid 10 km;
- simulated radius 350 km.

| Metric | Kết quả |
|---|---:|
| Grid points | 928 |
| Maximum subset | 1 |
| 4+ RX coverage | 48,81% |
| Best/core GOOD | 23,92% |
| GOOD+ACCEPTABLE | 43,43% |
| Branch separation GOOD area | 48,60% |
| Median P95 | 518,08 m |
| P90 P95 | 1.602,66 m |
| >=2 GOOD subset | 0% |
| N-1 | Không áp dụng / 0% |
| Overall UX | TRUNG BÌNH |
| Dependency | Chưa đủ alternative để xếp hạng |

Assessment nói rõ vùng thu chung/bố trí/branch còn hạn chế, P95 ở mức trung bình và strict-4 không có N-1.

## 6. Scenario B — current + RX-East, best 4-of-5

Candidate:

    RX-East = 20,0 N, 109,0 E, altitude 30 m,
    simulated radius 350 km

| Metric | Kết quả |
|---|---:|
| Grid points | 928 |
| Maximum subset | 5 |
| 4+ RX coverage | 100% |
| Best GOOD | 67,56% |
| GOOD+ACCEPTABLE | 88,04% |
| Branch separation GOOD area | 100% |
| Median best P95 | 235,83 m |
| P90 best P95 | 2.060,48 m |
| >=2 GOOD subset | 48,81% |
| N-1 | 9,27% |
| Receiver phụ thuộc nhất | QK4 |
| Median ratio without QK4 | 4,60x |
| Overall UX | KHÁ |

Assessment công bố trade-off:

- reception và branch rất mạnh;
- median P95 thấp;
- P90 vẫn cao;
- best subset mạnh nhưng worst/redundancy chưa đồng đều;
- N-1 còn rất thấp;
- QK4 là dependency lớn nhất trong các point có valid alternative.

## 7. Scenario C — current + RX-East + RX-West, best 4-of-6

Candidate bổ sung:

    RX-West = 20,0 N, 105,5 E, altitude 30 m,
    simulated radius 350 km

| Metric | Kết quả |
|---|---:|
| Grid points | 928 |
| Maximum subset | 15 |
| 4+ RX coverage | 100% |
| Best GOOD | 67,78% |
| GOOD+ACCEPTABLE | 88,69% |
| Branch separation GOOD area | 100% |
| Median best P95 | 213,10 m |
| P90 best P95 | 1.883,41 m |
| >=2 GOOD subset | 59,91% |
| >=3 GOOD subset | 58,94% |
| N-1 | 37,07% |
| Receiver đứng đầu ranking dependency | RX-East |
| Median ratio without RX-East | 2,45x |
| Overall UX | KHÁ |

Assessment thay đổi deterministic theo metric: 15 subset, redundancy/N-1 cao hơn scenario B, P95 tail vẫn được cảnh báo.

## 8. Ví dụ assessment sinh tự động

Current 4RX:

> Vùng thu chung còn hạn chế; nhiều khu vực chưa đủ bốn trạm cùng thu. Bố trí trạm còn yếu ở nhiều điểm trong vùng giám sát. Nhiều vùng còn nguy cơ có nghiệm cạnh tranh khó phân biệt. Trung vị là 518 m; P90 theo bản đồ là 1.603 m, với sai số thời gian giả định 0,25 µs. 23,9% vùng có ít nhất một, 0,0% có ít nhất hai và 0,0% có ít nhất ba tổ hợp 4 trạm GOOD. Mạng hiện không có ít nhất năm trạm eligible để đánh giá mất bất kỳ một trạm mà vẫn còn tổ hợp 4 trạm GOOD. Chưa đủ dữ liệu để xác định trạm quan trọng nhất.

Text được tạo từ template/rule. Không có API AI, random wording hoặc timestamp.

## 9. UX threshold

| Dimension | Threshold |
|---|---|
| 4+ reception | 90 / 75 / 50 / 25% |
| Best GOOD geometry | 75 / 50 / 25 / 10%, kết hợp GOOD+ACC |
| Branch GOOD area | 90 / 75 / 50 / 25% |
| >=2 GOOD subset area | 80 / 60 / 30 / 10% |
| N-1 | 80 / 60 / 30 / 10% |
| P95 | kết hợp median/P90 tại 250/500, 500/1.500, 1.500/5.000 m |
| Dependency validity | ít nhất 3 sample |

Các threshold này nằm trong assessment.py và được trả trong assessment.ux_thresholds. Chúng không làm thay đổi core GOOD.

## 10. Manual acceptance

| Yêu cầu | Kết quả |
|---|---|
| Planner tải bằng tiếng Việt | PASS |
| Basic mặc định | PASS |
| Advanced hoạt động | PASS |
| Major controls dễ hiểu | PASS |
| Analyze giữ nguyên | PASS |
| Network Assessment xuất hiện | PASS |
| Assessment khớp summary | PASS |
| Paragraph deterministic | PASS |
| Basic popup rút gọn | PASS |
| Advanced popup đủ metric | PASS |
| Tooltip/help hiển thị | PASS |
| Switch mode không recompute | PASS |
| Không thay production | PASS |

## 11. Screenshot

- [Cơ bản](../deployment_planner/acceptance/planner-phase35-basic.png)
- [Nâng cao](../deployment_planner/acceptance/planner-phase35-advanced.png)
- [Network Assessment](../deployment_planner/acceptance/planner-phase35-assessment.png)

Ảnh được chụp bằng Firefox headless trên frontend thật tại local standalone planner.

## 12. Known limitations

- UI tiếng Việt nhưng Advanced cố ý giữ thuật ngữ/ký hiệu tiếng Anh trong ngoặc.
- Error message kỹ thuật do backend có thể vẫn giữ wording tiếng Anh.
- Dependency cần alternative subset và tối thiểu ba sample.
- Strict-4 không có receiver importance alternative và N-1 được gắn không áp dụng.
- Assessment không suy đoán hướng địa lý nếu không có spatial clustering đáng tin.
- Baseline wording là interpretation, không tham gia ranking.
- P95 là model prediction, không phải truth error.
- Overall không phải safety/availability certification.

## 13. Production status

Không file hoặc service production nào được sửa hay restart. Planner vẫn standalone. Không đụng:

- realtime Mode A/C hoặc Mode-S MLAT;
- readsb;
- mlat-server;
- tar1090;
- socat/forwarding;
- production port.

Read-only verification cuối task:

- readsb.service: active;
- mlat-server.service: active;
- tar1090.service: active;
- TCP 30004: listening;
- TCP 30104: listening;
- PoC backend 8090: listening.

Planner tạm trên 8096 chỉ được dùng để chụp acceptance và đã dừng sau khi chụp. Process planner vốn có trên 8095 không bị restart trong task.
