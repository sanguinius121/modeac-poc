# Phase Tool-3.5 — Giao diện tiếng Việt và đánh giá mạng deterministic

## 1. Mục tiêu và phạm vi

Phase Tool-3.5 bổ sung lớp trình bày cho MLAT Deployment Planner:

- tiếng Việt là ngôn ngữ mặc định;
- chế độ Cơ bản dành cho người vận hành;
- chế độ Nâng cao giữ các metric kỹ thuật Phase Tool-3;
- tooltip và bảng giải thích ngắn;
- đánh giá mạng tiếng Việt sau mỗi lần phân tích;
- đánh giá hoàn toàn deterministic và không dùng AI/LLM.

Phase này không bổ sung geometry algorithm, candidate search hoặc realtime 4-of-N.

## 2. Kiến trúc

Luồng dữ liệu:

    AnalyzeRequest
          |
          v
    geometry_engine.py
    (toán Phase Tool-3)
          |
          +--> summary + grid
          |
          v
    assessment.py
    (rule diễn giải UX)
          |
          v
    response: summary + grid + assessment
          |
          v
    app.js: Cơ bản / Nâng cao

Module assessment chỉ đọc result và request. Nó không được gọi từ:

- geometry equation;
- reception provider;
- subset enumeration/ranking;
- branch calculation;
- quality classification.

Response Analyze cũ vẫn giữ nguyên các key. Object assessment và một số aggregate/presentation field được bổ sung.

## 3. Phân biệt lớp lõi và lớp UX

Các lớp sau thuộc geometry core:

| Core code | Nhãn tiếng Việt |
|---|---|
| GOOD | TỐT |
| ACCEPTABLE | CHẤP NHẬN ĐƯỢC |
| POOR | KÉM |
| VERY_POOR | RẤT KÉM |
| NO_MLAT | KHÔNG ĐỦ ĐIỀU KIỆN MLAT |

Core quality vẫn dùng đồng thời P95, condition và branch separation theo threshold Phase Tool-3.

Các mức sau thuộc assessment UX:

- RẤT TỐT;
- TỐT;
- TRUNG BÌNH;
- KÉM;
- RẤT KÉM;
- KHÔNG ÁP DỤNG;
- CHƯA ĐỦ DỮ LIỆU.

UX level diễn giải một metric tổng hợp theo tỷ lệ vùng. Nó không thay đổi và không thay thế core quality.

## 4. Chế độ Cơ bản

Cơ bản là mặc định. Nó ưu tiên thứ tự đọc:

1. Số trạm thu được tín hiệu.
2. Chất lượng bố trí trạm.
3. Độ tách biệt nghiệm.
4. Sai số dự kiến 95%.
5. Số tổ hợp tốt.
6. Khả năng chịu mất một trạm.
7. Mức độ phụ thuộc trạm.

Các lớp bản đồ mặc định có:

- Số trạm thu được tín hiệu;
- Chất lượng tốt nhất;
- Sai số dự kiến 95%;
- Khả năng chịu mất 1 trạm;
- Mức độ phụ thuộc trạm.

Popup Cơ bản chỉ hiện:

- vị trí;
- receiver count;
- best subset;
- quality đã dịch;
- predicted P95;
- mức branch định tính;
- GOOD subset count;
- trạng thái N-1.

Raw condition, raw branch microsecond, hull, full-N và bảng mọi subset được ẩn.

## 5. Chế độ Nâng cao

Nâng cao giữ:

- strict selected 4RX, best 4-of-N, worst 4-of-N và full-N diagnostic;
- giả lập mất receiver;
- toàn bộ heatmap Phase Tool-3;
- P50/P95;
- condition;
- branch separation và branch-safe;
- inside hull;
- best/worst subset;
- GOOD subset count và fraction;
- N-1;
- full-N P50/P95/condition;
- receiver importance median/P90/sample count;
- bảng tất cả subset qua POST /api/analyze-point.

Switch Cơ bản/Nâng cao chỉ render lại DOM/layer từ state.result. Nó không gọi Analyze và không tính lại geometry.

URL có thể dùng tham số mode=advanced để mở trực tiếp chế độ Nâng cao. Không có tham số thì luôn bắt đầu ở Cơ bản.

## 6. Mapping ngôn ngữ chính

| Khái niệm kỹ thuật | UI Cơ bản |
|---|---|
| Receiver | Trạm thu |
| Receiver Count | Số trạm thu được tín hiệu |
| Common Reception | Vùng thu chung |
| Geometry Quality | Chất lượng bố trí trạm |
| Best 4-of-N | Tổ hợp 4 trạm tốt nhất |
| Worst 4-of-N | Tổ hợp 4 trạm yếu nhất |
| Branch Separation | Độ tách biệt nghiệm |
| Branch Safe | Nghiệm đủ tách biệt |
| Predicted P50 | Sai số điển hình P50 |
| Predicted P95 | Sai số dự kiến 95% |
| GOOD Subset Count | Số tổ hợp 4 trạm tốt |
| Robustness Fraction | Tỷ lệ tổ hợp tốt |
| N-1 Survivability | Khả năng hoạt động khi mất 1 trạm |
| Receiver Importance | Mức độ phụ thuộc vào từng trạm |
| Full-N Diagnostic | Đánh giá dùng toàn bộ trạm |
| Condition Number | Độ nhạy của bố trí trạm |
| Convex Hull | Vùng được các trạm bao quanh |
| Target altitude | Độ cao mục tiêu |
| Timing noise | Sai số thời gian giả định |
| Grid resolution | Độ phân giải lưới |
| Simulated range | Vùng thu giả định |
| Observed outline | Vùng thu quan sát từ readsb |
| Analyze | Phân tích mạng |
| Network Summary | Tổng quan mạng |

## 7. Tooltip và bảng giải thích

Các metric Cơ bản có nút hỏi trợ giúp ngắn. Nội dung nhấn mạnh:

- reception và geometry là hai câu hỏi khác nhau;
- P95 là prediction theo timing noise, không phải measured error;
- N-1 không phải uptime;
- importance là đóng góp geometry, không phải phần cứng;
- grid/surveillance polygon giới hạn miền kết luận.

Nút “Xem giải thích các chỉ số” mở glossary rút gọn về:

- vùng thu chung;
- chất lượng bố trí;
- branch;
- P50/P95;
- 4-of-N;
- N-1;
- dependency;
- timing noise.

## 8. Assessment response

POST /api/analyze bổ sung:

    assessment:
      version
      ux_interpretation_only
      overall
      reception
      geometry
      branch
      p95
      redundancy
      n_minus_1
      dependency
      baseline
      context
      paragraph_vi
      ux_thresholds
      core_quality_note_vi

Backend chỉ trả dữ liệu và text, không trả raw HTML.

Context gồm:

- target altitude;
- timing noise;
- grid step;
- geometry strategy;
- số receiver enabled sau failure simulation;
- số outline/simulated provider;
- grid point count.

## 9. UX thresholds

### 9.1 Vùng thu chung

Input:

    four_plus_rx_coverage_percent

| 4+ coverage | UX level |
|---:|---|
| >=90% | RẤT TỐT |
| 75–<90% | TỐT |
| 50–<75% | TRUNG BÌNH |
| 25–<50% | KÉM |
| <25% | RẤT KÉM |

Mẫu text luôn nói “theo nguồn vùng thu đã chọn”.

### 9.2 Bố trí trạm

Input:

- best GOOD percent;
- best GOOD+ACCEPTABLE percent;
- median best condition, hoặc median condition trong strict mode.

| Điều kiện | UX level |
|---|---|
| GOOD >=75% và GOOD+ACC >=90% | RẤT TỐT |
| GOOD >=50% và GOOD+ACC >=75% | TỐT |
| GOOD >=25% và GOOD+ACC >=50% | TRUNG BÌNH |
| GOOD >=10% | KÉM |
| còn lại | RẤT KÉM |

Condition chỉ được đổi thành nhãn phụ:

- <=10: Tốt;
- <=30: Trung bình;
- >30: Kém.

Raw condition chỉ hiện ở Nâng cao.

### 9.3 Độ tách biệt nghiệm

Hai aggregate được giữ riêng:

    branch-good fraction =
      100 * số grid point có branch separation
            của best subset >= 1,0 µs
      / tổng grid point

    branch-safe fraction =
      100 * số grid point có best subset branch_safe
      / tổng grid point

Strict mode dùng đúng selected strict subset.

Branch-good fraction được đổi level bằng dải 90/75/50/25%, giống reception. Branch-safe fraction được hiển thị để không che giấu khác biệt giữa ngưỡng 1,0 và 0,5 µs.

### 9.4 Sai số dự kiến 95%

Input:

- median best P95;
- map-level P90 của best P95;
- timing noise.

| Median và P90 | UX level |
|---|---|
| median <=250 m và P90 <=500 m | RẤT TỐT |
| median <=500 m và P90 <=1.500 m | TỐT |
| median <=1.500 m và P90 <=5.000 m | TRUNG BÌNH |
| median <=5.000 m | KÉM |
| còn lại | RẤT KÉM |

Không đánh giá median một mình. Nếu median <=500 m nhưng P90 >1.500 m, text bắt buộc nêu tail còn xấu.

### 9.5 Dự phòng subset

Assessment tổng hợp tỷ lệ grid point có:

- ít nhất một subset GOOD;
- ít nhất hai subset GOOD;
- ít nhất ba subset GOOD.

Level dùng tỷ lệ có ít nhất hai subset, theo dải 80/60/30/10%.

Trong strict-4 chỉ có một subset; tỷ lệ >=2 và >=3 là 0.

### 9.6 N-1

Giữ nguyên định nghĩa core:

> Với mọi kịch bản bỏ một receiver eligible, vẫn tồn tại ít nhất một subset bốn receiver quality GOOD.

| N-1 area | UX level |
|---:|---|
| >=80% | RẤT TỐT |
| 60–<80% | TỐT |
| 30–<60% | TRUNG BÌNH |
| 10–<30% | KÉM |
| <10% | RẤT KÉM |

Strict mode hoặc dưới năm receiver được gắn KHÔNG ÁP DỤNG, không gọi là uptime.

### 9.7 Receiver dependency

Mỗi receiver đã có:

- median importance ratio;
- P90 importance ratio;
- số sample;
- fraction grid có valid sample.

Receiver có dưới ba sample không được xếp hạng. Sort deterministic:

1. median ratio giảm dần;
2. P90 ratio giảm dần;
3. sample fraction giảm dần;
4. receiver ID tăng dần.

Nếu median <=1,05 và P90 <=1,10, assessment nói chưa có dependency nổi trội. Equal median/P90 dùng ID tie-break và công bố đồng hạng.

## 10. Baseline summary

Chỉ dùng receiver enabled và không bị failure simulation. Khoảng cách pair dùng cùng Haversine helper của planner.

Response có:

- minimum/median/maximum baseline;
- danh sách pair dưới 50 km;
- count 150–<250 km;
- count 250–350 km;
- count trên 350 km.

Các dải này chỉ là diễn giải planning nội bộ. Baseline không tham gia subset ranking.

## 11. Overall rating

Overall không dùng score 0–100.

Policy:

1. đổi reception, geometry, branch và P95 thành ordinal 0–4;
2. lấy mức thấp nhất trong bốn dimension;
3. nếu N-1 không áp dụng, RẤT KÉM hoặc KÉM thì overall không vượt KHÁ;
4. nếu N-1 TRUNG BÌNH thì overall không vượt TỐT;
5. nếu tỷ lệ vùng có >=2 subset GOOD ở mức RẤT KÉM/KÉM thì overall không vượt KHÁ.

Mapping overall:

| Ordinal | Overall |
|---:|---|
| 4 | RẤT TỐT |
| 3 | TỐT |
| 2 | KHÁ |
| 1 | TRUNG BÌNH |
| 0 | KÉM |

Đây là conservative rule. Một dimension yếu có thể giới hạn toàn mạng; strength ở dimension khác vẫn được hiển thị trong từng card.

## 12. Đoạn đánh giá tự động

paragraph_vi ghép template cố định cho:

- reception;
- geometry;
- branch;
- P95;
- median/tail trade-off;
- best/worst trade-off;
- redundancy/N-1;
- dependency.

Đoạn có tối đa tám câu. Nếu có nhiều cảnh báo, logic giữ câu N-1 và dependency ở cuối. Không có random choice, timestamp hoặc runtime trong assessment.

## 13. Presentation field bổ sung

Các field sau chỉ làm lộ dữ liệu đã được geometry core tính hoặc aggregate grid:

- predicted_p50_error_m;
- best/worst P50;
- full-N P50;
- selected/best branch separation;
- best branch-safe và inside-hull;
- median P50;
- branch-safe/branch-good/hull percent;
- >=1/2/3 GOOD percent;
- median good subset fraction;
- importance sample fraction.

Không công thức nào trong geometry_core bị đổi.

## 14. Hạn chế

- Assessment chỉ đúng trong surveillance polygon, grid, altitude, timing noise và reception provider đã chọn.
- UX threshold là rule nội bộ, không phải aviation certification.
- Simulated radius không mô hình terrain, antenna hoặc interference.
- Outline là observed footprint, không phải RF guarantee.
- Branch aggregate phụ thuộc grid và miền branch search hiện tại.
- P95 vẫn là local linear deterministic Monte Carlo prediction.
- Dependency chỉ tồn tại ở point có alternative subset; sample ít được gắn thiếu dữ liệu.
- Không tạo azimuth score hoặc hướng không được data support.
- Overall là conservative wording, không phải safety decision.
- Realtime backend vẫn fixed-4 và không dùng assessment.

## 15. Không thuộc Phase Tool-3.5

Không triển khai:

- Tool-4 optimizer;
- automatic site placement;
- weighted optimization;
- realtime 4-of-N;
- automatic outline fetch;
- LLM/API AI;
- thay đổi readsb, tar1090, mlat-server hoặc forwarding.
