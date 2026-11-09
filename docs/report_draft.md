# Báo cáo tuần 3 — định giá xe cũ và sàng lọc tin bất thường

Bản nháp **đủ 8 mục**. Mọi số tái lập được bằng lệnh trong repo; số trên `val` trừ §5b (test, đánh giá
đúng một lần).

| Mục | Nguồn số | Lệnh sinh ra |
| --- | --- | --- |
| §1 Quy trình | `split_summary.json` | `python -m src.data_prep.pipeline` |
| §2 Chất lượng dữ liệu | `missing_report.json`, `normalize_report.json` | `python -m src.data_prep.missing` |
| §3 EDA | `docs/eda_summary.md` + 5 hình | `python -m tools.eda_summary` |
| §4 Đặc trưng | `feature_ablation.json`, `cardinality_study.json` | `python -m src.features.build_features --ablate` |
| §5 / §5b Mô hình | `docs/benchmark.md`, `docs/test_evaluation.md` | `python -m src.models.benchmark` · `python -m src.models.train --split test --at-m2` |
| §6 Sai số | `docs/error_taxonomy.md`, `docs/case_studies.md` | `python -m tools.error_report` |
| §7 Nhãn bất thường | `anomaly_labels.csv`, `anomaly_thresholds.json` | `python -m src.models.anomaly` |
| §8 Hạn chế | — | — |

## 1. Quy trình

Dữ liệu được chốt ngày 31/10 và đóng băng cho cả tuần: `master_clean_dataset.csv` (100.887 dòng) →
`src.data_prep.pipeline` (split theo `duplicate_group_id`, seed 42) → cohort + điền khuyết → bảng đặc
trưng `{train,val,test}_features_{minimal,full}.csv`. Tỉ lệ chia đạt **70,1% / 14,93% / 14,97%**
(70.244 / 14.964 / 14.980 dòng sau khi dựng đặc trưng), với **75.496 nhóm trùng** không nhóm nào nằm
hai phía của một split.

Ba cổng chặn chạy trước khi một con số được phép vào báo cáo:

| Cổng | Lệnh | Kết quả trên snapshot này |
| --- | --- | --- |
| Dữ liệu hợp nhất | `python -m tools.audit_master` | xem log lần chạy cuối |
| Hợp đồng nguồn | `python -m tools.validate_source_csv` | PASS cho từng nguồn |
| Rò rỉ đặc trưng | `python -m tools.model_gate` | PASS — không cột bị cấm, không bản sao target, các partition cùng cột, không nhóm vắt qua split |
| Kiểm thử | `python -m unittest discover -s tests` | xem `docs/test_results.txt` / lần chạy mới nhất |

Huấn luyện trên `log1p(price_vnd)`; mọi chỉ số báo cáo **cả log và VND** để không mô hình nào chỉ
khoe con số đẹp. Test set chỉ được đánh giá **một lần** tại M2.

## 2. Chất lượng dữ liệu

- **100.887 dòng** trong master, **100.868 dòng có nhãn giá**; 19 dòng không có giá bị loại (không
  điền khuyết vào target).
- **75.496 nhóm trùng** cho 100.887 tin ⇒ cross-posting là có thật; split theo nhóm nên val/test
  không bị thổi phồng bởi cùng một xe đăng nhiều nơi.
- **Tỉ lệ thiếu (train)**: `engine_capacity` **61,2%**, `sub_model_trim` **55,7%**, `seller_type`
  **34,1%**, `origin` **28,6%**, `seats` **21,3%**, `body_type` **18,6%**, `mileage_km` **12,7%**,
  `fuel_type` 0,7%, `transmission` 1,5%. Hai cột đầu là hạn chế thật của mô hình, không phải chi tiết
  kỹ thuật — xem `docs/data_limitations.md`.
- **Chuẩn hoá thương hiệu**: 164 cách viết → **146 hãng** (`Hyundai`/`HYUNDAI`,
  `Mercedes Benz`/`Mercedes-Benz`, `VinFast`/`Vinfast`, `LandRover`/`Land Rover`).
- **10.906 dòng** trong train có ít nhất một `quality_flags`; mô hình không được thấy cờ này (bị
  cấm làm feature) nên chúng được học như dòng bình thường.
- **Phân bố giá (train)**: trung vị 520 triệu, P10 199 triệu, P90 1,479 tỷ VND.
- **Khối lượng theo nguồn**: bonbanh 21.223 · oto.com.vn 20.764 · chotot 13.631 (19.428 toàn bộ) ·
  tinbanxe 5.355 · muaban 4.921 · carpla 2.932 · vucar 1.515 · **carmudi 366**.

## 3. Dữ liệu nhìn thấy (EDA)

Nguồn: `data/master/master_clean_dataset.csv` — **100.887 tin** trước cửa sổ giá, **100.803** sau khi
giữ 10 triệu – 50 tỷ VND (loại 84 tin, 0,08%, là giá đặt cọc/placeholder; giá thô lớn nhất 465 nghìn
tỷ). Tỉnh được chuẩn hoá trước khi đếm (bỏ dấu, không phân biệt hoa thường, bảng alias), nếu không
`TP HCM` và `TP.HCM` thành hai thị trường khác nhau và mọi số theo vùng đều sai.

| Hình | Nội dung | Con số phải nhớ |
| --- | --- | --- |
| `fig1_price_distribution.png` | phân bố giá | lệch phải mạnh ngay trong cửa sổ ⇒ mọi model fit `log1p(price_vnd)`, và R²(VND) luôn "đẹp" hơn R²(log) |
| `fig2_price_by_source.png` | giá theo sàn | trung vị 420 triệu (muaban.net) → 645 triệu (carpla): **×1,54** |
| `fig3_price_by_province.png` | giá theo tỉnh | TP.HCM 38.271 + Hà Nội 33.079 = **71%** khối lượng; chênh trung vị trong top 12 là **×1,7** |
| `fig4_price_by_year.png` | giá theo năm sản xuất | 225 triệu (2010) → 699 triệu (2025), tăng gần đơn điệu |
| `fig5_price_per_km_by_segment.png` | giá/1.000 km theo phân khúc | phân khúc lệch nhau **×9,4** theo giá/km, so với **×3,5** theo giá tuyệt đối |

Ba điều EDA nói rõ, và cả ba đều ảnh hưởng tới mục sau:

1. **Giá/km tách phân khúc mạnh hơn giá tuyệt đối, nhưng km vẫn là tín hiệu yếu.** Giữa 10 phân khúc
   có ≥900 tin, giá/km trải từ 4,6 triệu (Hatchback) đến 42,7 triệu (Coupe) — ×9,4; giá tuyệt đối chỉ
   từ 265 triệu đến 934 triệu — ×3,5. Nghĩa là km **không** "chuẩn hoá" được khác biệt phân khúc. Còn
   với mô hình, §4 đo được: bỏ `mileage_km` + `km_per_year` chỉ mất **ΔR² 0,0001**.
2. **`body_type` trống 18,2% ở toàn cửa sổ (18,6% ở train)** — một phần năm thị trường không gán được
   phân khúc, nên mọi kết luận "theo phân khúc" chỉ nói về 82% còn lại.
3. **Sàn nhỏ khác phân bố, không chỉ ít dòng.** carmudi 546 tin, vucar 2.124, carpla 4.179 — nhưng
   trung vị của carpla cao hơn muaban 1,54×. Vì vậy §6 báo sai số theo sàn thay vì một MAPE duy nhất,
   và §8 ghi rõ carmudi quá nhỏ để thành một phân đoạn riêng.

**"Cái mô hình không thấy"** (chuyển tiếp cho §6): giá rao chứ không phải giá giao dịch; không có lịch
sử tai nạn/bảo dưỡng; **4 dòng năm sản xuất không thể có thật** (1025, 2028, 2030, 2032) cộng 9 dòng
thiếu năm; và `engine_capacity` thiếu 61,2% — nên một phần đáng kể xe không phân biệt được bằng máy.

## 4. Đặc trưng

Hai bảng đặc trưng, cùng một whitelist cột:

- **minimal** — cột thô cộng tuổi xe: `manufacture_year`, `mileage_km`, `engine_capacity`, `seats`,
  `vehicle_age`, các categorical gốc.
- **full** — thêm `km_per_year`, `engine_per_seat`, `age_band`, `brand_age_band`,
  `is_luxury_segment` (theo hãng, **không** theo giá), `province_group`,
  `brand_retention_rate`, `province_price_index`, `n_imputed`.

Đóng góp của từng nhóm đặc trưng (drop-one, Ridge trên 20k dòng theo đúng phân công; ΔR² là mức giảm
R²(log) khi bỏ nhóm, baseline **0,9184**):

| Bỏ nhóm | Cột | R²(log) còn lại | ΔR² |
| --- | --- | ---: | ---: |
| timing | `manufacture_year`, `vehicle_age`, `age_band`, `brand_age_band` | 0,7904 | **+0,1280** |
| cat_identity | `brand`, `model`, `model_group` | 0,8656 | **+0,0528** |
| cat_spec | `transmission`, `fuel_type`, `origin`, `body_type`, `seller_type` | 0,9109 | +0,0075 |
| size | `engine_capacity`, `engine_per_seat`, `seats` | 0,9149 | +0,0035 |
| source | `source_platform` | 0,9154 | +0,0030 |
| flags | `n_imputed`, `is_luxury_segment` | 0,9169 | +0,0015 |
| usage | `mileage_km`, `km_per_year` | 0,9183 | +0,0001 |
| geo | `province_group`, `province_price_index`, `brand_retention_rate` | 0,9187 | −0,0003 |

Hai đọc hiểu quan trọng, cả hai đều **ngược với kỳ vọng ban đầu** và phải được viết thẳng vào mục 4:

1. **Tuổi xe + hãng/dòng là 90% giá trị** (ΔR² 0,1280 + 0,0528). Bỏ `km_per_year`/`mileage_km` gần như
   không đổi R² (+0,0001) — số km không phải tín hiệu định giá ở dữ liệu này, dù ai cũng nghĩ nó là.
2. **Nhóm geo không đóng góp** (ΔR² âm nhẹ): `province_group`, `province_price_index`,
   `brand_retention_rate` **không** giúp Ridge. Điều này khớp với quyết định loại hai thống kê giá
   khỏi cấu hình mặc định của preprocessor — bỏ đi không mất gì, mà lại tránh rò rỉ target.

Nghiên cứu cardinality (bảng đầy đủ ở `docs/cardinality_research.md`, LightGBM trên 20k dòng, chỉ đổi
cách mã hoá brand/model): `brand+model` categorical **0,9319** · `model_group` **0,9313** ·
`model` **0,9304** · target encoding out-of-fold **0,9178**. Kết luận: **target encoding không thắng**
ở cardinality này (1.912 model, 103 brand) — nó là lựa chọn kiểm soát phương sai cho mô hình tuyến
tính, không phải một cải thiện độ chính xác. Mục 4 phải nói đúng như vậy.

---

## 5. So sánh mô hình (val, 14.964 dòng)

8 mô hình × 2 bộ đặc trưng; 3 tổ hợp được tune trong **600 s, 25 draws × 2 grouped folds = 50 fits**,
phần còn lại dùng tham số cố định — cột `tuning` của `docs/benchmark.md` ghi từng dòng. Mọi số trong mục
này trên **val**; test chỉ được đánh giá **một lần** và để riêng ở §5b.

| Bộ | Mô hình | R²(log) | MAPE | median APE | MAE (VND) |
| --- | --- | ---: | ---: | ---: | ---: |
| full | **lightgbm+tuned** | **0,9471** | 11,4% | 6,2% | 82.087.205 |
| full | catboost | 0,9465 | 12,0% | 6,9% | 91.143.312 |
| minimal | lightgbm+tuned | 0,9464 | 11,6% | 6,3% | 84.155.488 |
| full | lightgbm | 0,9462 | 11,5% | 6,3% | 82.441.420 |
| full | **xgboost+tuned** | 0,9440 | **11,0%** | **5,9%** | **78.041.635** |
| full | rf | 0,9411 | 12,1% | 6,4% | 87.698.367 |
| full | xgboost | 0,9409 | 11,1% | 5,7% | 78.256.273 |
| full | ridge | 0,8970 | 18,0% | 10,4% | 141.897.201 |
| full | median (baseline) | 0,8773 | 18,8% | 7,3% | 101.649.813 |
| full | elasticnet | 0,8722 | 21,2% | 13,4% | 174.713.377 |
| full | lasso | 0,8561 | 22,9% | 14,8% | 190.664.684 |
| minimal | lightgbm | 0,9447 | 11,7% | 6,4% | 84.885.802 |
| minimal | xgboost | 0,9388 | 11,3% | 6,0% | 80.850.994 |

Năm điều phải nói thẳng trong mục này, kể cả khi nó làm mất tính "thành tích":

1. **Sàn canary là 0,946 / 11,6%; mô hình tốt nhất hơn ở cả hai — nhưng rất mỏng: +0,0011 R², −0,2 điểm
   MAPE.** Không có "bước nhảy" nào từ mô hình phức tạp: LightGBM chưa tune đã 0,9447–0,9462, và bản
   chưa tune *nằm đúng trên sàn* (0,9462 vs 0,946). Câu "đáng làm phức tạp" chỉ đứng được nhờ dòng tuned.
2. **Tuning mua được rất ít: +0,0009 R²** (0,9462 → 0,9471) đổi lấy 50 fits và 31,9 s → 468,5 s huấn
   luyện. Wilcoxon theo cặp nói chênh lệch này *có thật* (p = 7,8e-05, seed sd 0,0003), nhưng 0,0009
   không phải thứ người dùng cảm nhận được.
3. **CatBoost và LightGBM hoà nhau** (0,9465 vs 0,9462 khi chưa tune). Wilcoxon nói catboost nhỉnh
   (p = 2,3e-15) nhưng chênh R² chỉ 0,0003 — đúng một seed sd — và MAPE lại *kém* hơn (12,0% vs 11,5%).
4. **XGBoost thắng ở không gian VND** (MAPE 11,0%, median APE 5,9%, MAE 78,0 triệu — tốt nhất bảng) dù
   R² thấp hơn hẳn (0,9440); ngược lại Wilcoxon theo cặp nói nó **kém** lightgbm+tuned (p = 5,8e-12).
   Hai kết luận trái nhau vì XGBoost thắng ở nhóm xe đắt nhưng thua lẻ tẻ ở số đông. Đây chính là lý do
   phải chốt *một* metric chính **trước** khi đọc bảng, không phải sau.
5. **Baseline median mạnh hơn ridge ở median APE** (7,3% vs 10,4%) dù R² thấp hơn (0,8773 vs 0,8970).
   Một mô hình tuyến tính "trông tốt hơn" theo R² nhưng tệ hơn ở chính giữa phân bố — đúng loại kết
   luận sai mà cột median APE sinh ra để chặn.
4. **Baseline median mạnh hơn ridge ở median APE** (7,3% vs 10,4%) dù R² thấp hơn (0,8773 vs 0,8970).
   Một mô hình tuyến tính "trông tốt hơn" theo R² nhưng tệ hơn ở chính giữa phân bố — đúng loại kết
   luận sai mà bảng median APE sinh ra để chặn.

Bộ **full** chỉ hơn **minimal** khoảng 0,0015 R² (0,9462 vs 0,9447) ở cặp chưa tune. Với seed sd 0,0003
thì chênh lệch này nhỏ nhưng có thật (Wilcoxon p = 7,4e-07), nên giữ full là hợp lý nhưng không được mô
tả là "cải thiện lớn".

Đường cong học (LightGBM, 10/25/50/100% train): **0,8947 → 0,9107 → 0,9311 → 0,9440** — vẫn đang
tăng, nên trần hiện tại là *dữ liệu*, không phải đặc trưng. Đây cũng là lý do không đáng đổ thêm thời
gian vào tuning: 50 fits mua 0,0009, trong khi thêm dữ liệu vẫn đang mua hàng chục điểm phần nghìn.

**Mô hình dùng cho artefact (`predictions_{val,test}.csv`): lightgbm+tuned / full**, tham số đóng băng
`n_estimators=900, learning_rate=0.03, num_leaves=63, min_child_samples=20` — thắng trong 600 s / 25
draws. Lần chạy lại bằng `--params` cho **đúng** 0,9471 / 0,1904 / 82.087.205 / 0,114 trong 31,9 s thay
vì 468,5 s, nên artefact tái lập được mà không cần tune lại. Lý do chọn LightGBM thay vì catboost: MAPE
tốt hơn (11,4% vs 12,0%), và LightGBM cho quantile trực tiếp để sinh P10/P90 cho T3 mà không phải thêm
một mô hình thứ ba.

## 5b. Kết quả test — lần đánh giá duy nhất

Test chỉ được chấm **một lần**, sau khi đã đóng băng mô hình và tham số; file ghi
`docs/test_evaluation.md`, coverage band `docs/intervals_test.md`.

| Thước đo | val (14.964) | **test (14.980)** |
| --- | ---: | ---: |
| R²(log) | 0,9471 | **0,9487** |
| RMSE(log) | 0,1904 | 0,1869 |
| R²(VND) | 0,9215 | 0,9026 |
| MAE (VND) | 82.087.205 | 89.731.484 |
| MAPE | 11,4% | **10,9%** |
| MAPE clean | 10,3% | 10,1% |
| median APE | 6,2% | 6,1% |
| band phủ (nominal 80%) | 81,70% | **81,91%** |

Đọc bảng này cho ba điều:

1. **Test không dễ hơn val một cách bất thường.** R²(log) và MAPE *tốt hơn* val 0,0016 / 0,5 điểm —
   trong phạm vi biến động giữa hai tập cùng phân phối, không phải "test dễ".
2. **MAE và R²(VND) lại kém hơn** (89,7 vs 82,1 triệu; 0,9026 vs 0,9215) vì chúng tính bằng VND tuyệt
   đối và test có mix xe đắt hơn. Cùng một mô hình, hai kết luận trái chiều — lặp lại bài học ở mục 5.
3. **Band chuyển được sang test** (81,91% so với nominal 80%, lệch 8,62% dưới P10 / 9,47% trên P90), nên
   ngưỡng hiệu chỉnh trên train OOF không bị overfit vào val.

Điều **không** được làm sau khi đọc bảng trên: tune lại, đổi mô hình, đổi band, rồi chạy test lần hai.
Split đã tiêu; nếu có ai chạy lại `predictions_test.csv` thì con số "một lần" trong báo cáo mất nghĩa.

## 6. Phân tích sai số

- **Median APE 6,2%, MAPE 11,4%** trên val (trên test: 6,1% / 10,9%); đây là hai con số khác nhau và cả
  hai đều đúng — MAPE bị kéo bởi đuôi phải, median APE mô tả trải nghiệm của một tin rao điển hình.
- **Nhãn bất thường** (`data/master/anomaly_labels.csv`, review rate hiệu chỉnh đúng **3,00%**,
  P10/P90 lấy từ mô hình quantile của LightGBM): Fair **12.225** · Bargain **1.331** · Overpriced
  **1.325** · Suspicious **83**.
- **Theo nhóm sai số** (`docs/error_taxonomy.md`, quy tắc hiển nhiên để đọc lại):
  tin dưới 200 triệu **1.461** tin, median APE **13,2%**, Δ trung bình **+24,7%** — mô hình **định giá
  cao** xe rẻ, vì nhóm này chứa nhiều giá đặt cọc/giá ảo; km bất thường **118** tin / 9,6%; nhóm còn
  lại **13.385** tin / 5,8%.
- **Theo nguồn**: carmudi **10,0%** (105 tin) · chotot 7,1% (2.874) · muaban 6,7% (1.044) ·
  tinbanxe 6,5% (1.124) · carpla 6,3% (610) · oto.com.vn 5,9% (4.369) · bonbanh 5,9% (4.529) ·
  vucar 4,8% (309). Sai số không đều giữa các sàn và sàn nhỏ nhất có sai số lớn nhất, nên một MAPE
  tổng không đủ.
- **Theo decile giá**: decile rẻ nhất (< 200 triệu) có median APE **13,0%**, gần gấp đôi các decile
  phía trên (6,8% / 5,4%) — mô hình yếu nhất đúng ở nơi người mua ít tiền nhất.
- **Độ quan trọng** (`data/master/feature_importance.csv`): `brand_age_band` 0,510 ·
  `manufacture_year` 0,262 · `model` 0,231 · `model_group` 0,180 · `brand` 0,132 · `engine_capacity`
  0,130. Ba đặc trưng đầu đều là "xe gì, đời nào" — khớp với ablation ở mục 4.
- **Ba case study** (`docs/case_studies.md`, chọn bằng quy tắc nên tái lập được):
  `MUA_71248118` Toyota Corolla Cross 2022 rao **7,35 tỷ** trong khi mô hình ước **631 triệu**
  (Δ −91,4% — giá đặt cọc ảo); `CHOTOT_134989809` Aion Y Plus 2024 với **999.998 km** (Δ +488%);
  `CARPLA_F8W47` Audi Q5 2024 nhập khẩu rao **218 triệu** so với ước lượng **2,06 tỷ** (Δ +843%).

Ba case này không phải lỗi mô hình có thể sửa bằng tuning: chúng là **giá đặt cọc/giá ảo**, **odometer
bị chỉnh**, và **xe nhập khẩu**. Mục 7 phải nói rằng sản phẩm cần *dữ liệu* (lịch sử tai nạn, xác nhận
giá giao dịch) chứ không cần thêm một mô hình nữa.

## 7. Nhãn bất thường (Bargain · Overpriced · Suspicious)

Cơ chế (`src/models/anomaly.py`, `data/master/anomaly_thresholds.json`):

1. **Band** — P10/P90 lấy từ bộ ba quantile của LightGBM, đã hiệu chỉnh trên train OOF (không hiệu chỉnh
   trên val/test), phủ **81,70%** giá val và **81,91%** giá test so với nominal 80%.
2. **Isolation Forest** — 300 cây, `max_samples` 4096, chạy trên ma trận đặc trưng của val (numeric giữ
   nguyên, categorical mã hoá), để tách "ngoài band **và** bất thường về tổ hợp đặc trưng".
3. **Ngưỡng review** — đặt tại phân vị 97% của điểm IF, tức **3,00%** dòng val (449 tin) vào hàng đợi rà
   soát; đây là **ngân sách vận hành**, không phải ước lượng tỉ lệ tin bất thường thật.

Nhãn trên **val** (14.964 tin); test không được gán nhãn — test chỉ dùng cho §5b.

| Nhãn | Số tin | % | Δ trung vị (giá so với ước lượng) |
| --- | ---: | ---: | ---: |
| Fair | 12.225 | 81,7% | −0,6% |
| Bargain | 1.331 | 8,9% | **+19,7%** |
| Overpriced | 1.325 | 8,9% | **−14,7%** |
| Suspicious | 83 | 0,6% | +8,9% |

Trong 449 tin vượt ngưỡng IF, chỉ **83** đồng thời nằm ngoài band — nên `Suspicious` hẹp hơn "hàng đợi
rà soát" rất nhiều, và đó là con số đúng để nói với người dùng.

**Theo dải giá** — nhãn tập trung ở nhóm rẻ, khớp với §6:

| Dải giá | Số tin | Bargain | Overpriced | Suspicious | % bị gắn nhãn |
| --- | ---: | ---: | ---: | ---: | ---: |
| < 200 triệu | 1.501 | 336 | 49 | **25** | **27,3%** |
| 200–400 triệu | 3.555 | 374 | 232 | 17 | 17,5% |
| 400–700 triệu | 5.170 | 370 | 409 | 12 | 15,3% |
| 700 triệu – 1,5 tỷ | 3.226 | 211 | 386 | 15 | 19,0% |
| > 1,5 tỷ | 1.512 | 40 | 249 | 14 | 20,0% |

**Theo sàn** — Bargain nhiều nhất ở tinbanxe.vn (9,9%), Overpriced nhiều nhất ở carpla (12,6%):

| Sàn | Số tin | % Bargain | % Overpriced |
| --- | ---: | ---: | ---: |
| bonbanh | 4.529 | 9,5% | 9,3% |
| oto.com.vn | 4.369 | 8,3% | 9,8% |
| chotot | 2.874 | 8,9% | 7,3% |
| tinbanxe.vn | 1.124 | **9,9%** | 6,6% |
| muaban.net | 1.044 | 9,5% | 7,7% |
| carpla | 610 | 8,5% | **12,6%** |
| vucar.vn | 309 | 3,9% | 10,7% |
| carmudi | 105 | 5,7% | 3,8% |

Ba điều phải nói thẳng:

1. **`Bargain` không có nghĩa là "nên mua".** 336 trong 1.331 tin Bargain nằm dưới 200 triệu — đúng nhóm
   mà §6 xác định là giá đặt cọc/giá ảo (24/25 case tệ nhất). Nhãn này chỉ nói "thấp hơn mô hình", và mô
   hình không biết tin đó là cọc hay xe thật.
2. **Nhãn phụ thuộc band, nên phụ thuộc mô hình.** Đổi model hoặc đổi cách hiệu chỉnh band là đổi tỉ lệ
   nhãn; vì vậy §6 nói rõ band phủ bao nhiêu, và ngưỡng IF được ghi lại trong `anomaly_thresholds.json`
   để lần chạy sau so được.
3. **Review rate 3% là lựa chọn vận hành.** Đặt 2% hay 5% chỉ đổi số tin con người phải đọc, không đổi
   bản chất vấn đề: 83 tin Suspicious trên 14.964 là đủ ít để đọc tay, và đó là toàn bộ mục đích của T3.

## 8. Hạn chế

**Về dữ liệu** (chi tiết: `docs/data_limitations.md`):

- **Giá rao không phải giá giao dịch.** Mọi con số ở đây là "mô hình khớp giá rao", không phải "mô hình
  định đúng giá bán": khoản mặc cả và giá thực trả không có trong dữ liệu, nên sai số trên giá rao là
  **cận trên** của sai số trên giá giao dịch (không đo được từ snapshot này).
- **Thiếu trường quan trọng**: `engine_capacity` 61,2%, `sub_model_trim` 55,7%, `body_type` 18,2% (toàn
  cửa sổ), `mileage_km` 12,7%. Không có lịch sử tai nạn, bảo dưỡng, số chủ, tình trạng pháp lý.
- **Một snapshot, không có thời gian.** Không có ngày đăng làm feature (bị cấm vì rò rỉ), nên mô hình
  không biết mùa vụ hay xu hướng giá theo tháng.
- **Mất cân đối nguồn**: carmudi 546 tin (105 ở val) — không đủ để thành phân đoạn riêng; kết luận theo
  sàn cho carmudi/vucar là kết luận trên mẫu nhỏ.
- **19 dòng mất nhãn bị loại**, không điền khuyết vào target; **4 dòng năm sản xuất không thể có thật**
  vẫn nằm trong bảng đặc trưng (được mô hình xử lý như categorical, không bị sửa tay).

**Về mô hình và quy trình** (những điều chỉ thấy được khi đã làm xong):

- **Trần là dữ liệu, không phải mô hình.** 9 họ mô hình nằm gọn trong 0,937–0,947; tuning 50 fits mua
  0,0009; đường cong học vẫn tăng 0,8947 → 0,9440 khi từ 7k lên 70k dòng. Thêm feature tốt (km thật,
  taxonomy hãng–dòng, mùa vụ) đáng giá hơn thêm model.
- **Thứ hạng mô hình phụ thuộc metric.** LightGBM+tuned thắng R²(log) 0,9471; XGBoost+tuned thắng MAE
  (78,0 triệu), MAPE (11,0%) và median APE (5,9%) nhưng Wilcoxon theo cặp nói nó *kém* hơn
  (p = 5,8e-12). Báo cáo chốt R²(log) làm metric chính vì đó là mục tiêu huấn luyện và là ngưỡng sàn
  canary — đổi metric chính là đổi kết luận, nên phải nói trước.
- **Điểm số tuned bị lạc quan nhẹ.** 0,9471 là max của 25 draws chọn trên chính 14.964 dòng val; về lý
  thuyết nó sẽ rơi khi sang dữ liệu mới. Trên test nó *tăng* lên 0,9487, nhưng đó là một lần đo, không
  phải bằng chứng chống lạc quan.
- **Band không chứa điểm dự báo** ở 1,80% dòng val / 1,78% dòng test, vì band do model quantile sinh
  còn điểm do model trung bình sinh. Đã ghi trong `docs/intervals.md`; ép band chứa điểm sẽ làm band
  rộng ra và phá calibration.
- **Test đã tiêu.** `docs/test_evaluation.md` được ghi đúng một lần và công cụ từ chối ghi đè. Mọi thay
  đổi sau thời điểm này chỉ được báo cáo như hạn chế, không được kèm theo một lần chạy test thứ hai —
  nếu không, con số "một lần duy nhất" trong báo cáo mất nghĩa.

_§3 và §7 được soạn từ artefact có sẵn (`docs/eda_summary.md`, `anomaly_labels.csv`,
`anomaly_thresholds.json`); Phong và Tuấn Anh review lại trước khi nộp. Phần biên tập (một giọng văn, bố
cục, PDF, form nộp) vẫn là việc của người biên tập._
