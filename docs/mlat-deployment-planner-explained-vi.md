# Giải thích nguyên lý, thuật toán và cách đọc kết quả MLAT Deployment Planner

## 1. Mục đích, phạm vi và cách đọc tài liệu

Tài liệu này giải thích từ nền tảng vật lý đến implementation hiện tại của công cụ MLAT Deployment Planner trong project. Đối tượng đọc là kỹ sư RF hoặc phần mềm có kiến thức kỹ thuật cơ bản nhưng chưa quen với định vị đa trạm.

Phạm vi được chia rõ thành bốn loại bằng các nhãn sau:

- **[MEASURED]**: kết quả đã đo từ capture hoặc test thực trong project.
- **[SIMULATED]**: kết quả do mô hình planner hoặc script mô phỏng tạo ra.
- **[IMPLEMENTATION]**: hành vi được xác nhận trực tiếp từ source code hiện tại.
- **[ENGINEERING INTERPRETATION]**: cách diễn giải kỹ thuật từ các bằng chứng trên; không phải số đo hoặc bảo đảm vận hành.

Planner là công cụ quy hoạch và chẩn đoán. Nó không phải solver realtime, không điều khiển clock, không association message và không làm thay đổi production service.

Một kết luận rất quan trọng cần giữ xuyên suốt tài liệu là:

> Có thu được tín hiệu hay không và hình học định vị tốt hay không là hai câu hỏi khác nhau.

Planner vì vậy tách hai bước:

1. **Điều kiện thu nhận (reception eligibility)**: receiver nào được coi là có thể thu mục tiêu tại điểm đang xét.
2. **Chất lượng hình học (geometry quality)**: từ những receiver đủ điều kiện, tổ hợp nào cho phép định vị tốt.

## 2. Sóng vô tuyến và thước đo thời gian

### 2.1 Tốc độ truyền

Trong chân không, tốc độ ánh sáng là:

    c = 299 792 458 m/s

Đối với trực giác kỹ thuật có thể dùng:

    c xấp xỉ 300 000 km/s

Sóng vô tuyến trong bài toán này truyền gần với tốc độ đó. Vì vậy, sai khác thời gian tương ứng với sai khác quãng đường truyền lý tưởng như sau:

| Sai khác thời gian | Sai khác quãng đường xấp xỉ |
|---:|---:|
| 0,10 micro giây | 30 m |
| 0,25 micro giây | 75 m |
| 0,50 micro giây | 150 m |
| 1,00 micro giây | 300 m |

Đây **không phải** bảng quy đổi trực tiếp từ timing noise sang lỗi vị trí ngang. Nó mới chỉ cho biết sai khác đường truyền. Receiver geometry có thể làm lỗi vị trí nhỏ hơn hoặc, thường đáng quan tâm hơn, khuếch đại mạnh sai số đó theo một hướng yếu.

### 2.2 Một message đến nhiều receiver

Giả sử một máy bay phát một message tại thời điểm không biết trước. Bốn receiver ghi nhận:

    RX1 nhận tại t1
    RX2 nhận tại t2
    RX3 nhận tại t3
    RX4 nhận tại t4

Không cần biết chính xác thời điểm phát. Ta có thể lấy sai khác:

    Delta t21 = t2 - t1
    Delta t31 = t3 - t1
    Delta t41 = t4 - t1

Sai khác đường đi tương ứng:

    Delta d = c nhân Delta t

Mỗi phương trình sai khác thời gian đến — Time Difference of Arrival (TDOA) — mô tả một họ điểm có hiệu khoảng cách tới hai receiver cố định. Trong mặt phẳng, đường này có dạng hyperbola; trong không gian là hyperboloid. Giao của nhiều ràng buộc như vậy tạo ra vị trí ứng viên.

[IMPLEMENTATION] Hàm chữ ký TDOA trong geometry core hiện dùng **mọi cặp receiver**, không chỉ một receiver tham chiếu. Với mỗi cặp a, b:

    Delta t_ab = (r_b - r_a) / c

trong đó r_i là khoảng cách xiên từ target tới receiver i. Cách giải thích bằng một RX tham chiếu ở trên giúp hiểu nguyên lý; metric branch trong planner thực tế dùng vector all-pairs.

## 3. Vì sao MLAT cần nhiều receiver

### 3.1 Ba receiver

Nếu độ cao target đã cố định hoặc được tin cậy, vị trí ngang chỉ còn hai ẩn số East và North. Ba receiver cho hai TDOA độc lập nên về số phương trình có thể tạo nghiệm 2D.

Nhưng 3RX có các hạn chế:

- không còn phương trình dư để kiểm tra consistency;
- dễ xuất hiện hai nhánh đối xứng hoặc gần đối xứng;
- nhạy với receiver gần thẳng hàng;
- khó phát hiện association nhầm;
- đặc biệt rủi ro đối với Mode A/C ẩn danh.

[MEASURED] Test 8B của project ghi nhận 3.029 event 3RX có altitude hỗ trợ; 3.019 event bị phân loại nhiều nghiệm. P50/P95 khoảng cách giữa các nhánh lần lượt khoảng 41 km và 411 km. Đây là bằng chứng thực nghiệm trong pipeline hiện tại rằng “đủ phương trình” không đồng nghĩa với “nghiệm duy nhất an toàn”.

### 3.2 Bốn receiver

Với altitude đã biết, receiver thứ tư bổ sung một TDOA dư. Dữ liệu dư giúp:

- phân biệt nhánh nghiệm;
- kiểm tra residual hoặc consistency;
- giảm khả năng một association sai vẫn tạo nghiệm có vẻ hợp lý;
- phù hợp hơn với Mode A/C không có ICAO;
- tạo điều kiện đánh giá geometry và branch safety.

[MEASURED] Trong cùng chuỗi thử nghiệm Mode-S, 646/649 strict-4RX event tạo nghiệm duy nhất, và 643/643 trường hợp có frozen reference chọn được nhánh gần nhất. Số liệu này không phải bảo đảm cho mọi layout, nhưng giải thích vì sao kiến trúc realtime hiện vẫn thận trọng với strict 4RX.

### 3.3 Planner và realtime không giống nhau

[IMPLEMENTATION] Planner Phase Tool-3 có thể phân tích strict selected 4RX và best/worst 4-of-N. Pipeline realtime hiện tại vẫn association theo bộ bốn cố định:

    T37, Dao_Cai_chien, QK4, BachLongVi

Do đó, một heatmap best 4-of-N tốt không có nghĩa backend realtime đang tự chọn subset đó. Planner trả lời câu hỏi quy hoạch; production solver chỉ tạo output theo logic đã triển khai trong realtime.

## 4. Đồng bộ clock

Timestamps của các receiver phải nằm trong cùng một miền thời gian. Nếu một receiver có bias +1 micro giây thì nó đưa vào TDOA một sai khác đường đi cỡ 300 m trước khi geometry khuếch đại.

Clock lỗi có thể tạo ra vị trí nhìn bề ngoài hợp lệ nhưng bị dịch chuyển hệ thống. Vì vậy, nhiều receiver và geometry tốt không thay thế được clock tốt.

### 4.1 Clock trong realtime backend

[IMPLEMENTATION] Đây là metric vận hành realtime, không phải metric đầu vào trực tiếp của planner:

- mỗi clock link giữ tối đa 2.000 sample;
- có thể bắt đầu fit từ 20 sample, nhưng quality còn UNAVAILABLE cho tới 100 sample;
- P95 absolute residual nhỏ hơn 1 micro giây: STRONG;
- nhỏ hơn 5 micro giây: PASS;
- nhỏ hơn 10 micro giây: MARGINAL;
- còn lại: BAD.

Realtime dùng T37 làm miền timestamp quy ước và ánh xạ ba receiver còn lại trực tiếp về miền T37; toàn bộ sáu pair link vẫn được theo dõi. T37 là **tham chiếu quy ước**, không phải tuyên bố rằng clock T37 là thời gian tuyệt đối hoặc phần cứng tốt nhất.

Trong realtime localization, hàm sigma clock có floor 1 micro giây và fallback 10 micro giây khi thiếu P95. Đây không phải tham số Timing noise của planner.

### 4.2 Timing noise trong planner

Giao diện cho phép:

| Timing noise | Sai khác đường đi một receiver xấp xỉ |
|---:|---:|
| 0,10 micro giây | 30 m |
| 0,25 micro giây | 75 m |
| 0,50 micro giây | 150 m |
| 1,00 micro giây | 300 m |

[IMPLEMENTATION] Planner coi timing perturbation của từng receiver là mẫu chuẩn độc lập, sau đó khử thành phần thời gian phát chung bằng ma trận chiếu. Tham số là sigma theo receiver, không phải một P95 clock quality đo được từ backend.

[IMPLEMENTATION] Số mẫu hiện tại là 256. Seed gốc là 20260811. Trong 4-of-N, chuỗi giả ngẫu nhiên của mỗi receiver được sinh xác định từ seed và receiver ID bằng SHA-256. Nhờ vậy, cùng ID và cấu hình tạo cùng perturbation:

- scenario A và B có thể so sánh ổn định;
- thêm receiver mới không làm thay đổi chuỗi noise của receiver cũ;
- Analyze lặp lại không tạo heatmap hơi khác chỉ vì random seed.

Điều này không có nghĩa RF noise ngoài đời là deterministic.

[SIMULATED] Với layout irregular 300 km ở altitude 2.500 m, tài liệu mô phỏng hiện có ghi nhận:

| Timing noise | Median predicted P95 | P90 predicted P95 theo bản đồ |
|---:|---:|---:|
| 0,10 micro giây | 77 m | 197 m |
| 0,25 micro giây | 192 m | 493 m |
| 0,50 micro giây | 384 m | 986 m |
| 1,00 micro giây | 768 m | 1.971 m |

Quan hệ gần tuyến tính là hệ quả của estimator tuyến tính hiện tại. Hệ số khuếch đại tại từng grid point vẫn do geometry quyết định.

## 5. Vị trí receiver, baseline và đa dạng phương vị

### 5.1 Baseline

Baseline là khoảng cách giữa hai receiver. Không tồn tại quy tắc “càng xa càng tốt”.

**Baseline quá ngắn:** hai receiver nhìn target xa gần cùng một hướng. Khi target dịch chuyển, hiệu khoảng cách giữa hai receiver thay đổi ít, nên hai receiver cung cấp thông tin gần trùng nhau.

**Baseline dài:** thường tạo góc nhìn khác biệt tốt hơn, nhưng common RF reception có thể giảm. Target có thể nằm ngoài vùng giao coverage; antenna, terrain, sensitivity và interference trở thành yếu tố chi phối.

[MEASURED] Baseline đã ghi trong tài liệu project:

| Cặp | Khoảng cách xấp xỉ |
|---|---:|
| T37 – Cái Chiên | 18,3 km |
| Cái Chiên – Bạch Long Vĩ | 132,2 km |
| T37 – Bạch Long Vĩ | 150,6 km |
| QK4 – Bạch Long Vĩ | 264,9 km |
| QK4 – Cái Chiên | 359,9 km |
| QK4 – T37 | 374,9 km |

T37–Cái Chiên rất hữu ích cho common reception, clock link và redundancy, nhưng ở vùng giám sát 300–500 km chúng không nên được hiểu như hai đỉnh geometry độc lập mạnh.

[ENGINEERING INTERPRETATION] Các dải định hướng trong tài liệu spacing hiện tại là:

- dưới khoảng 40–50 km: thường quá gần nếu cả hai được kỳ vọng là đỉnh geometry chủ lực cho vùng 300–500 km;
- 50–120 km: phù hợp vai trò inner/center, overlap và clock;
- 150–250 km: baseline chủ lực thường hữu ích;
- 250–350 km: diagonal có thể tạo diversity tốt nếu common reception còn đủ;
- trên 350 km: rủi ro common reception tăng;
- trên 400 km: không nên mặc nhiên đưa vào strict-4 nếu chưa có bằng chứng RF.

Đây là hướng dẫn engineering gắn với vùng và giả định của project, không phải định luật MLAT toàn cầu.

### 5.2 Đa dạng phương vị

Đa dạng phương vị (azimuth diversity) nghĩa là target được nhìn từ nhiều hướng:

                 RX-Bắc

    RX-Tây       TARGET       RX-Đông

                 RX-Nam

Một mạng gần thẳng hàng ở cùng phía target:

    RX1 --- RX2 --- RX3 --- RX4 ---------------- TARGET

có thể có nhiều receiver nhưng một hướng quan sát rất yếu. Target dịch vuông góc với hướng nhìn có thể làm TDOA thay đổi rất ít.

### 5.3 Convex hull

Bao lồi (convex hull) là đa giác nhỏ nhất bao quanh các receiver:

    RX1 ---------------- RX2
     |                    |
     |       TARGET       |
     |                    |
    RX3 ---------------- RX4

Target bên trong hull thường nhận được đa dạng góc nhìn tốt hơn. Khi target ở xa ngoài hull, tất cả receiver dễ cùng nằm về một phía.

[IMPLEMENTATION] Planner dùng Delaunay trên longitude/latitude để trả về boolean inside hull. Nó **không** tự loại target ngoài hull. Trong ranking, inside hull chỉ là tie-break sau branch safety, P95 và condition.

Vì vậy:

- inside hull không bảo đảm accurate;
- outside hull không đồng nghĩa impossible;
- đây là diagnostic, không phải reception gate.

[MEASURED] Hull của bốn site hiện tại chủ yếu là tam giác T37–QK4–Bạch Long Vĩ, diện tích khoảng 15.814 km²; Cái Chiên nằm bên trong do gần T37.

## 6. Mô hình toán geometry

### 6.1 Tọa độ và khoảng cách

[IMPLEMENTATION] Planner chuyển latitude, longitude, altitude theo WGS-84 sang ECEF. Với target x và receiver x_i:

    r_i = chuẩn Euclid của (x - x_i)

Vector đơn vị từ receiver tới target:

    u_i = (x - x_i) / r_i

Sau đó vector được chiếu lên hai trục East và North tại target vì planner đánh giá lỗi ngang 2D.

### 6.2 Jacobian

Jacobian trả lời:

> Nếu target dịch một lượng nhỏ theo East hoặc North, các range/TDOA thay đổi bao nhiêu?

Mỗi hàng ban đầu chứa sensitivity East/North của một receiver. Vì thời gian phát không biết, code khử thành phần chung:

    P = I - (1 1 chuyển vị) / N
    G = P H

G là design matrix TDOA đã loại thành phần common-mode.

Trực giác:

- target dịch theo cả hai hướng và TDOA thay đổi rõ: geometry cung cấp thông tin tốt;
- target dịch theo một hướng nhưng TDOA gần như không đổi: hướng đó yếu;
- receiver thẳng hàng hoặc gần đồng hướng: các hàng của G gần phụ thuộc nhau.

### 6.3 Singular values và condition number

Code tính hai singular value của G:

    sigma_max >= sigma_min

Condition number:

    condition = sigma_max / sigma_min

Nếu sigma_min nhỏ hơn 1e-10, condition là vô hạn.

Hai singular value đại diện độ nhạy theo hai phương chính:

- sigma_max lớn: có một hướng quan sát mạnh;
- sigma_min rất nhỏ: có một hướng gần không quan sát được;
- tỷ số lớn: sai số timing dễ bị kéo dài thành ellipse lỗi lớn theo hướng yếu.

Condition thấp nghĩa là geometry cân bằng hơn. Condition cao nghĩa là nhạy với perturbation. Nhưng:

> Condition là độ nhạy hình học không thứ nguyên; nó không phải sai số theo mét.

Hai layout có condition giống nhau vẫn có error scale khác nếu singular values có độ lớn khác hoặc timing noise khác. Vì vậy phải đọc condition cùng predicted P95.

### 6.4 Covariance tuyến tính

Khi G đủ hạng, code dùng:

    covariance_unit = nghịch đảo của (G chuyển vị nhân G)

Với timing noise sigma_t:

    sigma_m = c nhân sigma_t

Linear HRMSE:

    HRMSE = sigma_m nhân căn của trace(covariance_unit)

Đây là local linear model quanh vị trí target đang xét.

## 7. Predicted P95 và Monte Carlo

### 7.1 P95 nghĩa là gì

Predicted P95 = 500 m nghĩa là:

> Trong mô hình local và tập 256 timing perturbation hiện tại tại grid point đó, percentile 95 của độ lớn lỗi ngang dự đoán là 500 m.

Nó không có nghĩa:

- target thật chắc chắn sai 500 m;
- 95% mọi chuyến bay ngoài đời sẽ đạt ngưỡng này;
- đây là measured truth error;
- planner đã mô hình terrain, multipath, association hoặc clock drift.

P95 phụ thuộc timing noise giả định, geometry, altitude, grid point, branch behavior và mô hình tuyến tính hóa.

### 7.2 Monte Carlo được implementation thế nào

[IMPLEMENTATION] Với ma trận G:

    estimator = pseudo-inverse(G) nhân P

Mỗi vector perturbation theo receiver được đổi sang mét, rồi:

    horizontal_error = estimator nhân timing_error_vector

Code lấy norm East/North của 256 error vector và tính P50/P95.

Điểm cần nói chính xác: planner **không** cộng perturbation rồi chạy full nonlinear position solver 256 lần. Đây là Monte Carlo qua local linear estimator/Jacobian. Một số tài liệu cũ dùng từ “solve” theo nghĩa rộng; source hiện tại cụ thể hơn như mô tả trên.

Nếu không truyền draws, geometry core có analytic approximation kiểu Rayleigh từ HRMSE. Planner hiện truyền deterministic draws.

### 7.3 Percentile tại điểm và percentile theo bản đồ

Đây là hai tầng thống kê rất dễ nhầm:

    Tại mỗi grid point
        256 mẫu timing
        -> một P95 lỗi vị trí của điểm

    Trên toàn bản đồ
        thu P95 của từng grid point
        -> median hoặc P90 của các giá trị P95

Ví dụ “P90 best P95 = 1 km” nghĩa là khoảng 90% grid point có point-level best predicted P95 không quá 1 km. Nó không phải “P90 của 256 sample tại một điểm”, cũng không phải P95 toàn mạng.

Median là giá trị ở giữa. P90 theo bản đồ là ngưỡng mà khoảng 90% grid point nằm dưới hoặc bằng. P95 tại một điểm là ngưỡng cho 95% sample lỗi của mô hình ở riêng điểm đó.

## 8. Nhánh nghiệm và branch safety

### 8.1 Vì sao có nhánh cạnh tranh

Một tập TDOA có thể gần tương thích với nhiều vị trí cách xa nhau:

              nghiệm A

    RX1 -------- RX2 -------- RX3

              nghiệm B

Tình huống này thường gặp hơn với 3RX, receiver gần thẳng hàng, hoặc target ngoài hull.

### 8.2 Branch separation hiện tại

[IMPLEMENTATION] Với mỗi grid point, planner tạo chữ ký TDOA all-pairs. Nó tìm một điểm khác cách ít nhất 25 km và lấy RMS difference nhỏ nhất giữa hai chữ ký. Đơn vị là micro giây.

Để tăng tốc, planner dùng cKDTree, xem tối đa 96 láng giềng gần nhất trong không gian chữ ký; nếu không có SciPy thì dùng brute force. Subset receiver thẳng hàng được gán separation 0. Nếu surveillance grid chỉ có một điểm thì separation là vô hạn vì không có nhánh cạnh tranh trong miền khảo sát.

Do đó branch separation là:

- một diagnostic trên grid và surveillance polygon đã khai báo;
- phụ thuộc grid step và miền tìm kiếm;
- không phải chứng minh toán học toàn cục rằng ngoài miền không còn nghiệm khác.

### 8.3 Định nghĩa branch-safe

[IMPLEMENTATION] Một subset là branch-safe khi:

1. condition, predicted P95 và branch separation đều hữu hạn;
2. branch separation ít nhất 0,5 micro giây;
3. receiver subset không collinear.

Branch-safe không đồng nghĩa GOOD. GOOD còn đòi separation ít nhất 1,0 micro giây, condition không quá 10 và P95 không quá 500 m.

Trong best 4-of-N, branch-safe được ưu tiên trước P95. Lý do là một subset có local P95 đẹp nhưng có nhánh xa gần cùng chữ ký không đáng tin bằng subset hơi lớn P95 nhưng không có ambiguity tương tự trong miền phân tích.

## 9. Reception model

### 9.1 Reception không phải geometry

Một điểm có thể nằm giữa bốn receiver và geometry lý thuyết rất đẹp, nhưng nếu chỉ ba site thu được message thì planner phải trả NO_MLAT. Ngược lại, sáu receiver cùng thu không bảo đảm geometry tốt nếu tất cả nằm cùng phía.

### 9.2 Simulated max range

[IMPLEMENTATION] Simulated provider dùng Haversine **ngang** từ receiver đến grid point:

    eligible khi horizontal distance <= max_range_km

Target altitude và receiver altitude không tham gia reception gate này. Max range mặc định 350 km chỉ là bán kính giả định.

Nó không mô hình:

- terrain hoặc radio horizon;
- antenna pattern và feeder loss;
- shadowing, multipath, interference;
- receiver sensitivity;
- traffic distribution;
- xác suất detection.

Nó vẫn hữu ích khi so sánh candidate chưa có dữ liệu thực vì cung cấp một giả định nhất quán.

### 9.3 readsb outline.json

[IMPLEMENTATION] Schema đã hỗ trợ:

    actualRange.last24h.points

Mỗi point:

    [latitude, longitude, third_value]

Planner dùng latitude/longitude làm footprint ngang. Giá trị thứ ba chỉ được ghi nhận min/max trong metadata, không dùng làm altitude gate hoặc quality.

Normalization hiện tại:

- file không quá 2 MiB;
- tối đa 10.000 point;
- kiểm tra số hữu hạn và miền lat/lon;
- loại adjacent duplicate;
- loại point đóng polygon trùng point đầu;
- cần ít nhất ba point phân biệt;
- từ chối antimeridian wrap;
- kiểm tra self-intersection;
- point trên biên được coi là nằm trong polygon.

Point-in-polygon được dùng như gate:

    grid point bên trong outline -> receiver eligible
    grid point bên ngoài outline -> receiver unavailable

Target altitude và max range không thay đổi gate của outline provider.

Quan trọng:

> outline.json là observed reception outline trong cửa sổ last24h, không phải guaranteed RF propagation footprint.

Nó phụ thuộc nơi aircraft đã bay, altitude của traffic, lượng traffic, antenna, site, terrain và receiver. Vùng không có trong outline có thể chỉ là chưa có aircraft đi qua; không đủ cơ sở kết luận receiver chắc chắn không thu được ở đó.

## 10. Strict selected 4RX và 4-of-N

### 10.1 Receiver Count

Receiver Count tại một grid point là số receiver enabled, không failed, và được reception provider đánh dấu eligible.

Nó trả lời “có bao nhiêu receiver có khả năng thu”, không trả lời “geometry tốt đến đâu”. Sáu RX cùng phía vẫn có thể POOR.

### 10.2 Strict selected 4RX

[IMPLEMENTATION] User chọn đúng bốn receiver. Một điểm có solve khi cả bốn đều eligible. Receiver enabled khác vẫn được đếm trong Receiver Count nhưng không thay thế receiver selected bị thiếu. Failed receiver bị loại.

Strict mode hữu ích cho:

- regression với pipeline bốn trạm hiện tại;
- mô phỏng realtime fixed-4;
- so sánh với mạng 4-of-N.

### 10.3 4-of-N

Nếu N receiver eligible, planner liệt kê mọi tổ hợp bốn:

    C(N,4) = N! / [4! (N-4)!]

| N | Số subset bốn receiver |
|---:|---:|
| 4 | 1 |
| 5 | 5 |
| 6 | 15 |
| 7 | 35 |

[IMPLEMENTATION] Nếu C(N,4) lớn hơn 70, API yêu cầu cờ xác nhận explicit; lớn hơn 1.000 thì từ chối. Giao diện còn cảnh báo khi ước lượng grid points nhân số subset vượt 12.000.

## 11. Best subset, worst subset và ranking chính xác

### 11.1 Best 4-of-N

Best là subset bốn receiver tốt nhất trong số subset eligible tại điểm đó. Nó không phải bốn receiver gần nhất, baseline dài nhất hoặc condition thấp nhất đơn thuần.

[IMPLEMENTATION] Sort key chính xác, theo thứ tự ưu tiên:

1. branch-safe trước branch-unsafe;
2. predicted P95 nhỏ hơn;
3. condition nhỏ hơn;
4. inside hull trước outside hull;
5. tuple receiver ID theo thứ tự từ điển để tie-break xác định.

Vì branch safety đứng đầu, một subset branch-safe P95 hơi cao có thể thắng subset branch-unsafe có local P95 thấp.

### 11.2 Worst 4-of-N

Worst là diagnostic redundancy. Code chọn theo hướng ngược:

1. branch-unsafe tệ hơn branch-safe;
2. predicted P95 lớn hơn;
3. condition lớn hơn;
4. outside hull tệ hơn inside hull;
5. khi còn hòa, tuple ID lớn hơn theo thứ tự từ điển do dùng max key.

Ví dụ best P95 250 m nhưng worst P95 4 km nghĩa là mạng có ít nhất một tổ hợp mạnh và cũng có tổ hợp rất yếu. Planner không nói operational backend sẽ cố ý chọn worst subset.

### 11.3 Strategy hiển thị

- best_4_of_n: primary quality/P95/condition lấy từ best subset.
- worst_4_of_n: primary quality/P95/condition lấy từ worst subset.
- full_n_diagnostic: primary vẫn là best subset; full-N chỉ là số diagnostic.

[IMPLEMENTATION] Thực tế full-N metrics được tính khi có ít nhất năm receiver trong **mọi** non-strict strategy, không chỉ khi chọn nhãn full_n_diagnostic. Nhãn strategy không làm full-N trở thành solver chính.

## 12. Bộ phân loại GOOD, ACCEPTABLE, POOR, VERY_POOR

[IMPLEMENTATION] Chất lượng subset được phân loại bằng phép AND giữa ba điều kiện:

| Quality | Predicted P95 | Condition | Branch separation |
|---|---:|---:|---:|
| GOOD | <= 500 m | <= 10 | >= 1,0 micro giây |
| ACCEPTABLE | <= 1.500 m | <= 30 | >= 0,5 micro giây |
| POOR | <= 5.000 m | <= 100 | >= 0,2 micro giây |
| VERY_POOR | không đạt đầy đủ một hàng trên | không đạt | không đạt |

GOOD nghĩa là thuận lợi theo model và threshold nội bộ của project. Không có definition trong implementation rằng các lớp này tương ứng một chuẩn chứng nhận hàng không hoặc xác suất vận hành cụ thể.

### 12.1 NO_MLAT khác VERY_POOR

- **NO_MLAT**: không có đủ subset bốn receiver hợp lệ theo strategy/reception.
- **VERY_POOR**: có đủ bốn receiver và đã đánh giá geometry, nhưng metric không đạt POOR.

Trong strict mode, thiếu bất kỳ selected receiver nào tạo NO_MLAT. Trong 4-of-N, có dưới bốn receiver eligible hoặc không có valid subset tạo NO_MLAT.

Một discrepancy cần lưu ý: một số constant/help text cũ mô tả NO_MLAT là “selected receiver outside simulated range”. Source hiện tại hỗ trợ cả outline và 4-of-N, nên ý nghĩa thực tế rộng hơn wording legacy đó.

## 13. GOOD subset count và robustness

### 13.1 GOOD subset count

Đây là số subset bốn receiver có quality đúng bằng GOOD.

Ví dụ sáu receiver tạo 15 subset:

    GOOD = 9
    ACCEPTABLE = 4
    POOR = 2

Một điểm chỉ có một subset GOOD mong manh hơn điểm có 12 subset GOOD, dù best quality của cả hai đều là GOOD.

### 13.2 Robustness fraction tại một điểm

[IMPLEMENTATION]

    good_subset_fraction = GOOD subset count / tổng valid 4RX subsets

Ví dụ 9/15 = 60%.

Nó không phải xác suất uptime, xác suất detection hoặc xác suất backend chọn đúng subset. Nó là mật độ tổ hợp GOOD trong model tại điểm đó.

### 13.3 Một tên summary dễ gây nhầm

[IMPLEMENTATION] Trường summary hiện tên là robust_good_fraction_percent, nhưng code tính:

    phần trăm grid point có GOOD subset count >= 2

Nó **không** phải trung bình good_subset_fraction trên bản đồ. Giao diện diễn đạt đúng hơn là “>=2 GOOD subsets”. Khi dùng JSON API cần nhớ khác biệt giữa tên trường và phép tính.

## 14. N-1 survivability và leave-one-out

### 14.1 N-1 survivability

Một mạng có N receiver có N kịch bản mất một receiver. Với 5RX:

    mất RX1
    mất RX2
    mất RX3
    mất RX4
    mất RX5

[IMPLEMENTATION] Một grid point được đánh dấu N-1 survivable chính xác khi:

1. hiện có ít nhất năm receiver eligible;
2. với **mọi** receiver eligible bị loại lần lượt;
3. vẫn tồn tại ít nhất một subset 4RX quality **GOOD** không chứa receiver vừa loại.

ACCEPTABLE không đủ. Vì GOOD đã đòi branch separation >=1,0 micro giây nên yêu cầu GOOD cũng bao hàm branch safety.

N-1 là resilience geometry/reception theo snapshot mô hình. Nó không dự đoán phần trăm uptime phần cứng hoặc RF.

### 14.2 Leave-one-out

Leave-one-out giữ thông tin chi tiết:

    bỏ T37 -> best P95 ...
    bỏ QK4 -> best P95 ...

N-1 gom mọi kịch bản thành pass/fail tại điểm. Leave-one-out cho biết mất receiver nào làm mạng suy giảm, nên phù hợp tìm site geometry-critical.

## 15. Receiver Importance

[IMPLEMENTATION] Tại mỗi grid point:

1. lấy overall best subset theo ranking bình thường;
2. với receiver r, loại mọi subset chứa r;
3. lấy best alternative còn lại bằng cùng ranking;
4. tính:

    importance_ratio(r) =
        P95 của best alternative không dùng r
        chia cho
        P95 của overall best

Nếu không còn alternative hoặc P95 không hữu hạn, value là null.

Ví dụ overall best 300 m, best without RX-East 900 m:

    ratio = 900 / 300 = 3,0
    degradation = +200%

Một sắc thái quan trọng: nếu overall best vốn không dùng receiver r, alternative tốt nhất có thể chính là overall best và ratio bằng 1. Receiver đó không đóng góp vào **best available geometry tại điểm**, dù có thể vẫn quan trọng cho reception hoặc redundancy.

Receiver Importance đo đóng góp hình học tương đối tại vị trí đó. Nó không đo signal strength, sensitivity, hardware quality hoặc clock quality. Summary báo median/P90 ratio chỉ trên những point có ratio hữu hạn.

[SIMULATED] Acceptance Phase Tool-3 ghi nhận QK4 có importance ratio khoảng 4,60x trong một scenario 5RX. Đây là kết quả của scenario cụ thể, không phải hằng số toàn mạng.

### 15.1 So sánh các metric

| Metric | Câu hỏi nó trả lời |
|---|---|
| Best 4-of-N | Nếu chọn subset tốt nhất thì tiềm năng định vị tốt đến đâu? |
| Worst 4-of-N | Một combination yếu có thể tệ đến đâu? |
| GOOD subset count | Có bao nhiêu đường dự phòng đạt GOOD? |
| Robustness fraction | Tỷ lệ các subset valid đạt GOOD là bao nhiêu? |
| N-1 | Mất bất kỳ một receiver có còn ít nhất một subset GOOD không? |
| Receiver Importance | Bỏ riêng receiver này làm best P95 suy giảm bao nhiêu lần? |

## 16. Full-N diagnostic

[IMPLEMENTATION] Khi có ít nhất năm receiver eligible, planner có thể xây generalized G với toàn bộ N receiver và tính condition/P50/P95 tương tự. Kết quả được gắn nhãn diagnostic và không thay đổi:

- quality chính;
- best/worst ranking;
- selected subset;
- N-1.

Không nên hiểu full-N là production solver vì:

- realtime engine hiện fixed-4;
- association và clock quality của thêm receiver vẫn rất quan trọng;
- planner mới phân tích local geometry, không triển khai operational full-N solve;
- thêm receiver không tự động bảo đảm dữ liệu của receiver đó đúng hoặc đồng bộ.

Nhãn phù hợp là **DIAGNOSTIC ONLY**.

## 17. Cách đọc từng heatmap

### 17.1 Receiver Count

Đọc heatmap này đầu tiên:

- 0–3 RX: không thể strict 4RX/4-of-N tại điểm;
- 4 RX: đúng một subset;
- 5 RX: năm subset;
- 6 RX: 15 subset.

Đây là coverage count, không phải quality.

### 17.2 Predicted P95

[IMPLEMENTATION] Màu hiện tại:

| P95 | Màu/ý nghĩa trực quan |
|---:|---|
| <250 m | xanh đậm |
| 250–<500 m | xanh |
| 500–<1.000 m | vàng |
| 1.000–<2.000 m | cam |
| 2.000–<5.000 m | đỏ cam |
| >=5.000 m | đỏ sẫm |
| NO_MLAT | xám |

Các màu là visualization threshold, không phải service-level guarantee. Nếu strategy worst được chọn, primary P95 là worst; nếu không, primary thường là best.

### 17.3 Best Quality

Mỗi cell hiển thị lớp quality của best 4RX subset:

- GOOD: xanh;
- ACCEPTABLE: vàng;
- POOR: cam;
- VERY_POOR: đỏ;
- NO_MLAT: xám.

Nó có xu hướng optimistic và trả lời: “nếu có subset selection thông minh, vùng này có tiềm năng tốt không?”

### 17.4 Worst Quality

Hiển thị quality của worst valid subset. Đây là conservative diagnostic: “nếu chỉ còn hoặc vô tình dùng một combination yếu thì tệ đến đâu?”

Không dùng worst một mình để kết luận performance bình thường; cũng không giả định backend sẽ chọn worst.

### 17.5 GOOD Subset Count

Màu thay đổi động theo maximum count trong result. Count 1 là đường tốt duy nhất, count cao là redundancy density lớn. Cần đọc cùng tổng số subset: 5 GOOD trên 5 khác 5 GOOD trên 35.

### 17.6 Robustness Fraction

Heatmap liên tục 0–100%, với mốc legend 0, 25, 50, 75, 100. Đây là GOOD count chia valid subset count tại mỗi point.

### 17.7 N-1

- xám: ít hơn 5 receiver, không áp dụng;
- xanh: sau mọi kịch bản mất một receiver vẫn còn subset GOOD;
- đỏ: ít nhất một kịch bản mất trạm không còn subset GOOD.

Use case chính: chọn receiver thứ 5/6 và đánh giá bảo trì/mất site.

### 17.8 Receiver Importance

Sau khi chọn receiver:

- ratio <=1,1: xanh;
- <=1,5: vàng;
- <=2,0: cam;
- >2,0: đỏ;
- null: xám.

Importance thay đổi theo không gian. QK4 có thể critical ở một vùng nhưng không nằm trong best subset ở vùng khác.

### 17.9 Click inspection

[IMPLEMENTATION] Endpoint analyze-point rerun toàn bộ grid với detail rồi trả cell có latitude/longitude gần click nhất theo khoảng cách bình phương trong lat/lon. Nó không giải chính xác tại một tọa độ tùy ý ngoài grid. Subset table được sort theo best ranking.

## 18. Bốn ví dụ reception và geometry

### Ví dụ A — bốn receiver bao quanh

    RX1 -------- RX2
     |   target   |
    RX3 -------- RX4

Cả bốn eligible, azimuth diversity tốt, branch tách rõ, P95 thấp. Kết quả có thể GOOD.

### Ví dụ B — sáu receiver nhưng cùng phía

    RX1 RX2 RX3 RX4 RX5 RX6 ---------------- target

Receiver Count = 6 nhưng một direction weak, condition/P95 có thể POOR. Count cao không cứu được layout gần tuyến tính.

### Ví dụ C — ba receiver geometry đẹp

Ba receiver có thể tạo nghiệm 2D khi altitude fixed, nhưng planner strict-4/4-of-N trả NO_MLAT vì không có subset bốn. Đây là policy có chủ ý, không phải VERY_POOR.

### Ví dụ D — năm receiver, best GOOD, worst POOR

Mạng operationally có thể chọn subset GOOD, nhưng redundancy không đồng đều. Nếu receiver critical mất đi, chỉ còn subset POOR. Cần xem N-1, GOOD count và importance thay vì chỉ Best Quality.

## 19. Ảnh hưởng địa lý và độ cao

### 19.1 Coastline, island và terrain

Coastline, đảo, núi, đô thị, antenna height, đường truyền trên biển và vật cản có thể làm reception bất đối xứng. Planner geometry biết tọa độ 3D receiver/target, nhưng simulated reception không biết terrain hoặc antenna.

Vì vậy phải phân biệt:

- **planner geometry model**: sensitivity TDOA của tọa độ đã cho;
- **real RF propagation**: việc cùng transmission có thực sự tới receiver hay không.

Outline quan sát có thể phản ánh một phần hệ RF thực, nhưng cũng bị traffic distribution chi phối.

### 19.2 Receiver altitude

Receiver altitude tham gia ECEF, slant vector và Jacobian geometry. Tuy nhiên simulated max-range gate chỉ dùng horizontal Haversine distance. Code không tính radio horizon từ receiver altitude.

Không thể dùng planner hiện tại để kết luận terrain clearance hay vùng phủ very-low-altitude.

### 19.3 Target altitude

Target altitude tham gia tọa độ 3D và các vector unit trong Jacobian. Nó có thể thay đổi sensitivity ngang, đặc biệt khi target gần mạng hoặc altitude tương đối lớn.

[SIMULATED] Tài liệu hiện tại cho layout irregular 300 km ghi P90 point-level P95 khoảng 493, 491, 492 và 491 m tại altitude lần lượt 2,5, 5, 10 và 12 km với timing noise 0,25 micro giây. Điều này cho thấy horizontal geometry của **scenario đó** khá ổn trong dải trên; không được suy rộng thành RF coverage thấp hoặc mọi layout.

### 19.4 Vì sao altitude yếu trong 3D TDOA

Các receiver mặt đất có vertical baseline chỉ vài chục mét trong khi horizontal baseline hàng trăm km. Tất cả gần cùng một mặt phẳng, nên target dịch theo vertical có thể tạo thay đổi TDOA khó phân biệt.

[MEASURED] Test 7A ghi condition 3D khoảng 4,94 x 10^9 so với condition 2D khoảng 5,06 trong trường hợp đã kiểm tra. Project vì vậy ưu tiên 2D horizontal MLAT cộng altitude trusted/assumed, thay vì coi altitude là ẩn quan sát mạnh.

## 20. Common reception: trade-off quan trọng nhất

Geometry chỉ có giá trị khi cùng transmission được nhiều receiver thu và association đúng.

[MEASURED] Test 6 trong 5 phút ghi:

| Cluster reception | Số lượng |
|---|---:|
| 2RX | 133.403 |
| 3RX | 4.273 |
| 4RX | 8 |

[MEASURED] Test 7H và 7H_2 trong các capture 10 phút ghi lần lượt 68 và 81 strict-4 event.

[MEASURED] Mode-S Test 8 ghi DF17 cluster 2/3/4RX là 48.879 / 9.685 / 540; non-position Mode-S là 74.087 / 13.150 / 649.

Các số này cho thấy 2RX common reception nhiều hơn rất mạnh so với 4RX trong capture cụ thể. Baseline dài giúp geometry nhưng có thể làm vùng giao reception giảm. Đây là trade-off trung tâm khi thiết kế network.

[MEASURED] T37–Cái Chiên có common reception/clock mạnh: Test 6 có 4.596 geometry sample, clock holdout P95 0,203 micro giây và 114.827 Mode A/C pair association. Hai site gần nhau yếu về độc lập geometry xa nhưng mạnh về overlap và clock evidence.

## 21. Vì sao 4-of-N, 5RX và 6RX hữu ích

### 21.1 Strict 4 so với 4-of-5

Strict 4:

    RX1 RX2 RX3 RX4
    mất một receiver -> không solve

4-of-5:

    RX1 RX2 RX3 RX4 RX5
    có năm combination bốn receiver

Lợi ích tiềm năng:

- receiver failure tolerance;
- chọn geometry tốt hơn theo không gian;
- RF diversity;
- nhiều đường dự phòng GOOD.

Nhưng lợi ích chỉ có nếu receiver thứ năm tạo overlap và directional diversity, không chỉ tăng count.

### 21.2 Bốn perimeter cộng một center

Perimeter mở rộng hull và azimuth diversity. Center tăng reception overlap, clock-link density và fallback subset. Center không thay thế perimeter vì nó thường không tạo baseline/góc nhìn mới mạnh như một site ở biên.

### 21.3 Sáu receiver

Layout “năm perimeter + một center” hoặc “bốn perimeter + hai inner” có thể tăng:

- số GOOD subset;
- N-1 survivability;
- coverage overlap;
- geometry diversity.

Mục tiêu không phải chỉ đạt Receiver Count = 6, mà là làm nhiều trong 15 subset trở nên hữu ích.

## 22. Ví dụ project-specific về bốn site

[IMPLEMENTATION] Tọa độ cấu hình hiện tại:

| Receiver | Latitude | Longitude | Altitude |
|---|---:|---:|---:|
| T37 | 21,485594 | 107,773191 | 60 m |
| QK4 | 18,760032 | 105,659087 | 20 m |
| Dao_Cai_chien | 21,320940 | 107,766116 | 28 m |
| BachLongVi | 20,132285 | 107,724413 | 28 m |

[ENGINEERING INTERPRETATION]

- T37 và Cái Chiên gần nhau: tốt cho common reception/clock redundancy nhưng cung cấp directional diversity hạn chế.
- QK4 tạo đỉnh tây nam, có vai trò lớn trong mở hull; baseline dài cũng làm common reception trở nên khó hơn.
- Bạch Long Vĩ tạo geometry ngoài khơi/phía đông và baseline hữu ích với QK4/T37.

[MEASURED] Test 7C ghi condition của các bộ ba:

| Bộ ba | Condition xấp xỉ |
|---|---:|
| T37 + QK4 + BLV | 5,18 |
| Cái Chiên + QK4 + BLV | 5,58 |
| T37 + Cái Chiên + QK4 | 19,6 |
| T37 + Cái Chiên + BLV | 22,2 và có hai nhánh |

Đây là minh họa rõ rằng thay T37 bằng Cái Chiên đôi khi ít thay đổi khi có QK4+BLV, trong khi bộ ba chứa cả T37+Cái Chiên dễ thiếu diversity.

## 23. Cách đọc Network Summary

### 23.1 Các field chung

- **Grid points**: số cell được đánh giá sau khi tạo grid trong surveillance polygon.
- **Subset evaluations**: tổng số subset-point đã tính.
- **4+ RX coverage**: phần trăm grid point có ít nhất bốn receiver eligible.
- **5+ RX coverage**: phần trăm có ít nhất năm.
- **6+ RX coverage**: phần trăm có ít nhất sáu.
- **Best GOOD**: tỷ lệ grid point mà best subset đạt GOOD.
- **Best GOOD+ACCEPTABLE**: tỷ lệ best đạt một trong hai lớp.
- **Worst GOOD**: tỷ lệ point mà ngay cả worst subset vẫn GOOD.
- **N-1 survivable**: tỷ lệ point thỏa định nghĩa N-1 chính xác ở mục 14.
- **>=2 GOOD subsets**: tỷ lệ point có ít nhất hai đường GOOD.
- **Best median/P90 P95**: median/P90 theo bản đồ của point-level best P95.
- **Worst median/P90 P95**: tương tự cho worst.
- **Runtime / max subsets**: thời gian chạy và số subset lớn nhất tại một point.
- **Reception source counts**: số receiver dùng simulated hay outline.
- **Importance median/P90 ratio, samples**: thống kê importance hữu hạn cho receiver đang chọn.

P95 summary chỉ lấy point có metric hữu hạn, không đưa NO_MLAT vào như giá trị vô hạn. Vì vậy phải đọc P95 cùng coverage; một scenario có P95 đẹp trên vùng rất nhỏ không tự động tốt hơn scenario coverage rộng.

### 23.2 Strict summary

Strict mode tập trung vào selected-4 coverage, quality distribution, median/P90 P95 và condition của đúng bộ bốn. Không nên so N-1 của strict-4 vì mất một trạm là không còn subset bốn.

### 23.3 Ví dụ candidate

Before:

    GOOD = 40%
    N-1 = 10%
    P90 best P95 = 2 km

After:

    GOOD = 70%
    N-1 = 55%
    P90 best P95 = 800 m

Candidate cải thiện cả geometry, tail và resilience.

Nếu GOOD tăng nhưng N-1 hầu như không tăng, candidate có thể tạo một subset mạnh mới nhưng không cung cấp đường thay thế cho mọi kịch bản mất trạm.

[SIMULATED] Phase Tool-3 acceptance ở grid 10 km ghi:

| Scenario | 4+ coverage | Best GOOD | GOOD+ACC | N-1 | Median best P95 | P90 best P95 |
|---|---:|---:|---:|---:|---:|---:|
| Current 4 | 48,81% | 23,92% | 43,43% | 0% | 518,1 m | 1.602,7 m |
| +RX-East | 100% | 67,56% | 88,04% | 9,27% | 235,8 m | 2.060,5 m |
| +RX-West | 100% | 67,78% | 88,69% | 37,07% | 213,1 m | 1.883,4 m |

Ví dụ này cũng cho thấy metric có thể đi ngược nhau: +RX-East làm median tốt nhưng P90 tail xấu hơn current trong tập point có metric; đồng thời coverage tăng lên 100%. Không được rút kết luận chỉ từ một cột.

## 24. Quy trình đầy đủ của planner

    Receiver positions
             +
    Reception models
             +
    Target altitude
             +
    Timing noise
             +
    Surveillance polygon
             |
             v
       Generate grid
             |
             v
    Reception eligibility
             |
             v
     Available receivers
             |
             v
       Enumerate C(N,4)
             |
             v
     Geometry calculation
             |
             v
    Branch / P95 / condition / hull
             |
             v
        Rank subsets
             |
             v
    Best / Worst / robustness / N-1
             |
             v
       Heatmaps + summary

[IMPLEMENTATION] Grid step hỗ trợ 20, 10 và 5 km; mặc định 10 km. Số point tối đa 25.000. Target altitude mặc định 2.500 m, input được validate trong 0–30.000 m.

## 25. Workflow đề xuất cho operator

1. **Vẽ surveillance polygon.** Đây là miền mà branch search và summary thực sự đánh giá.
2. **Nhập receiver thực với altitude đúng.** Sai tọa độ làm geometry sai.
3. **Gắn outline cho site đã có dữ liệu.** Luôn nhớ outline là observed traffic footprint.
4. **Dùng simulated range cho candidate.** Giữ cùng giả định khi so các candidate.
5. **Chọn target altitude phù hợp nhiệm vụ.** Có thể chạy nhiều altitude thay vì một giá trị.
6. **Chọn timing noise.** Dùng nhiều scenario để kiểm tra sensitivity.
7. **Analyze.**
8. **Xem Receiver Count trước.** Nếu không đủ 4+, geometry heatmap không cứu được.
9. **Xem Best Quality/P95.** Đánh giá potential nếu chọn subset tốt.
10. **Xem Worst và GOOD count/fraction.** Đánh giá độ mong manh.
11. **Xem N-1.** Kiểm tra mất bất kỳ site.
12. **Xem Receiver Importance.** Tìm vùng phụ thuộc vào từng site.
13. **Click các vùng critical.** Đọc subset table, branch separation, hull và full-N diagnostic.
14. **Lặp lại với altitude/noise/reception khác.** Một candidate tốt phải đủ ổn qua nhiều giả định hợp lý.

Khi đánh giá một receiver mới, metric đầu tiên nên xem là **Receiver Count/4+ reception coverage**, vì không có common reception thì mọi geometry metric vô nghĩa. Sau đó mới xem Best P95/Quality, rồi redundancy/N-1 và Importance.

## 26. Các cách hiểu sai thường gặp

1. **“Receiver càng xa càng tốt.”** Sai vì common reception giảm và target có thể ở ngoài intersection coverage.
2. **“Nhiều receiver hơn luôn tốt hơn.”** Sai nếu site mới cùng hướng, không thu chung hoặc clock kém.
3. **“Receiver Count cao là geometry tốt.”** Count chỉ là eligibility.
4. **“Condition thấp là accuracy theo mét.”** Condition không thứ nguyên; P95 mới biểu diễn error scale của model.
5. **“P95 là actual measured error.”** Đây là prediction từ noise assumption và local linear model.
6. **“Outline là guaranteed RF coverage.”** Nó là observed last24h footprint, chịu ảnh hưởng traffic.
7. **“Inside hull luôn accurate.”** Hull không kiểm tra timing noise, baseline degeneracy hoặc reception.
8. **“Outside hull là impossible.”** Code vẫn tính và có thể cho quality sử dụng được.
9. **“Best-4 chắc chắn là production result.”** Realtime hiện không chạy dynamic best 4-of-N.
10. **“N-1 là receiver uptime.”** Nó là pass/fail geometry/reception cho từng kịch bản drop.
11. **“Worst-4 là expected normal operation.”** Worst chỉ là stress/redundancy diagnostic.
12. **“Full-N là production solver.”** Hiện chỉ diagnostic trong planner.
13. **“Altitude không quan trọng.”** Nó tham gia 3D vector/Jacobian, dù một layout cụ thể có thể ổn định theo altitude.
14. **“Baseline dài luôn tốt.”** Directional diversity tăng nhưng common RF có thể sụt.
15. **“Center receiver thay thế perimeter.”** Center hỗ trợ overlap; perimeter tạo hull/diversity.
16. **“Branch-safe nghĩa là GOOD.”** Branch-safe dùng ngưỡng separation 0,5 micro giây; GOOD có thêm ngưỡng chặt hơn.
17. **“Một điểm màu xanh chứng minh RF tốt.”** Simulated provider không biết terrain, antenna hoặc interference.
18. **“P90 P95 là một percentile duy nhất.”** Đây là percentile qua hai tầng: P95 sample tại point, rồi P90 qua map.

## 27. Những giới hạn implementation cần công bố

- Local error model tuyến tính quanh true grid point; không chạy nonlinear solve cho mỗi sample.
- Branch search bị giới hạn bởi surveillance grid, min distance 25 km và nearest-signature search.
- Simulated reception dùng bán kính ngang, không terrain/radio horizon.
- Outline là binary point-in-polygon, không có xác suất reception.
- Quality thresholds là project diagnostic thresholds, không có mapping chuẩn vận hành được định nghĩa.
- Full-N chỉ diagnostic.
- Dynamic best 4-of-N chưa phải realtime operational path.
- Association error, packet collision, multipath và correlated clock noise không nằm trong planner model.
- Receiver perturbations được mô hình độc lập; common/correlated noise chưa được định nghĩa trong implementation.
- Hull chỉ boolean, không có metric “gần biên hull bao nhiêu”.
- Một grid-point-only surveillance làm branch separation vô hạn vì không có điểm cạnh tranh; không nên hiểu là bằng chứng unique toàn cầu.

### 27.1 Discrepancy giữa code và tài liệu cũ

1. Phase 1 từng mô tả planner gọi/import tool cũ; sau Phase 2 source hiện dùng package geometry_core.
2. Tài liệu spacing cũ gọi 4-of-5 là hướng phát triển; planner Phase Tool-3 đã có 4-of-N, nhưng realtime production vẫn fixed-4.
3. Một số wording nói Monte Carlo “solve”; code hiện dùng Jacobian/pseudo-inverse local estimator.
4. Help text NO_MLAT cũ chỉ nhắc selected simulated receiver; semantics hiện gồm outline và thiếu subset trong 4-of-N.
5. Trường robust_good_fraction_percent không phải average robustness fraction mà là phần trăm point có ít nhất hai subset GOOD.
6. full-N metrics được tính trong mọi non-strict run có 5+ RX, dù strategy không chọn full_n_diagnostic.
7. Worst tie-break dùng tuple ID lớn hơn do max key; best dùng tuple nhỏ hơn.

## 28. Kết luận thiết kế mạng

[ENGINEERING INTERPRETATION] Một mạng tốt phải đồng thời đạt:

- common reception đủ rộng;
- ít nhất bốn receiver ở mỗi vùng cần solve;
- azimuth diversity và baseline hữu ích;
- branch separation đủ;
- predicted P95 phù hợp với timing assumption;
- nhiều hơn một subset GOOD;
- N-1 tốt ở vùng quan trọng;
- không phụ thuộc quá mức vào một receiver;
- clock/association operational đủ tin cậy.

Không metric đơn lẻ nào thay thế được toàn bộ chuỗi này.

## Phụ lục A — Công thức liên quan trực tiếp implementation

### A.1 Khoảng cách và TDOA

    r_i = ||x - x_i||

    Delta t_ab = (r_b - r_a) / c

    Delta d = c Delta t

### A.2 Khử thời gian phát chung

Với N receiver:

    P = I - 11^T / N
    G = P H

### A.3 Condition

    condition = sigma_max(G) / sigma_min(G)

Nếu sigma_min gần 0 thì condition vô hạn.

### A.4 Estimator lỗi ngang

    estimator = pseudo-inverse(G) P
    e_horizontal = estimator e_range

Planner lấy norm của hai thành phần East/North.

### A.5 P95

Với 256 độ lớn lỗi ngang đã sắp xếp, P95 là percentile 95 theo quy tắc percentile của NumPy. Nó là thống kê mẫu của model.

### A.6 Số tổ hợp

    C(N,4) = N! / [4! (N-4)!]

### A.7 Robustness fraction

    fraction = số subset quality GOOD / tổng subset valid

### A.8 Receiver Importance

    importance_r =
        best P95 khi cấm receiver r
        /
        overall best P95

## Phụ lục B — Thuật ngữ

**Baseline:** khoảng cách giữa hai receiver; ảnh hưởng directional diversity và common reception.

**TDOA:** sai khác thời gian một transmission đến hai receiver.

**MLAT:** định vị đa trạm từ nhiều measurement, trong project chủ yếu dùng TDOA.

**Receiver:** trạm thu và timestamp message.

**Target:** transmitter/máy bay ở vị trí cần đánh giá.

**Grid point:** một điểm rời rạc trong surveillance polygon được planner phân tích.

**Convex hull:** đa giác lồi nhỏ nhất bao quanh receiver.

**Jacobian:** ma trận sensitivity của range/TDOA đối với dịch chuyển nhỏ của target.

**Condition number:** tỷ số sensitivity mạnh nhất/yếu nhất; chỉ báo geometry imbalance, không phải mét.

**Monte Carlo:** tạo nhiều timing perturbation để thu phân bố lỗi dự đoán; hiện áp dụng qua local linear estimator.

**P95:** ngưỡng mà 95% sample model nằm dưới hoặc bằng.

**Branch:** một vị trí cạnh tranh có chữ ký TDOA giống hoặc gần giống.

**Branch safety:** subset có metric hữu hạn, không collinear và separation ít nhất 0,5 micro giây.

**Reception:** điều kiện receiver được coi là có thể thu target tại một point.

**Outline:** polygon observed reception từ readsb last24h, không phải propagation guarantee.

**Subset:** một tổ hợp receiver; trong mode chính ở đây là bốn receiver.

**4-of-N:** liệt kê/chọn subset bốn từ N receiver eligible.

**Best subset:** subset đứng đầu ranking branch safety, P95, condition, hull, ID.

**Worst subset:** subset yếu nhất theo thứ tự ngược để chẩn đoán redundancy.

**N-1 survivability:** mất lần lượt bất kỳ receiver eligible nào vẫn còn ít nhất một subset GOOD.

**Leave-one-out:** kết quả chi tiết khi bỏ riêng từng receiver.

**Receiver Importance:** tỷ số best P95 khi cấm receiver so với overall best P95.

**Full-N:** geometry dùng mọi receiver eligible; hiện chỉ diagnostic.

**GOOD subset count:** số tổ hợp bốn receiver đạt đồng thời threshold GOOD.

**Robustness fraction:** GOOD count chia tổng valid subset tại một point.

**NO_MLAT:** không có đủ subset bốn receiver hợp lệ; khác với có geometry nhưng VERY_POOR.

## Phụ lục C — Checklist đánh giá một site mới

1. Site mới làm tăng 4+ reception coverage ở đâu?
2. Dữ liệu reception là simulated hay measured outline?
3. Best P95/quality có cải thiện ở vùng nhiệm vụ không?
4. Worst subset có còn vùng rất yếu không?
5. GOOD subset count và fraction có tăng không?
6. N-1 có cải thiện sau mọi kịch bản mất trạm không?
7. Receiver Importance có cho thấy chuyển dependency hay chỉ tạo thêm một critical site?
8. Candidate mở hull/azimuth diversity hay chỉ nằm cạnh site cũ?
9. Kết quả có ổn khi đổi target altitude và timing noise không?
10. RF/common reception thật có bằng chứng để hỗ trợ geometry prediction không?

Chỉ khi trả lời đồng thời các câu hỏi reception, geometry, redundancy và operational clock/association mới nên chuyển từ candidate planning sang thử nghiệm triển khai.

## Phụ lục D — Nguồn đã đối chiếu và trạng thái xác minh

Báo cáo này đã được đối chiếu trực tiếp với:

- package geometry_core, gồm chuyển đổi WGS-84/ECEF, Jacobian, condition, local Monte Carlo, TDOA signature, branch và quality threshold;
- deployment_planner backend, model/API, simulated provider, outline provider và frontend heatmap/summary;
- các tool receiver_geometry_analysis, receiver_layout_simulation và receiver_geometry_optimizer;
- tài liệu receiver geometry, spacing/layout và tài liệu/acceptance Phase Tool-1, Tool-2, Tool-3;
- test_deployment_planner, test_deployment_planner_phase2 và test_deployment_planner_phase3;
- source realtime clock, association và localization để phân biệt metric planner với hành vi operational fixed-4.

Lệnh test chuẩn theo acceptance report:

    python3 -m unittest discover -s tests -p 'test_deployment_planner*.py' -v

Kết quả tại thời điểm viết: 45 test planner/geometry/subset/outline/frontend contract chạy thành công.

Đối với ý nghĩa xác suất vận hành hoặc mapping của GOOD/ACCEPTABLE/POOR sang một tiêu chuẩn chứng nhận bên ngoài:

    Definition not explicitly documented in current implementation

Vì vậy tài liệu chỉ diễn giải các lớp này theo đúng threshold nội bộ, không gán thêm bảo đảm accuracy, availability hoặc safety không có trong source.
