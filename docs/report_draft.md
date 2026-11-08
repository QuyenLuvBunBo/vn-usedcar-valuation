# Báo cáo — bản nháp tuần 3 (mục 1 · 2 · 4 · 8)

Bản nháp này chỉ chứa những mục **tái lập được bằng lệnh trong repo**; mục 3, 5, 6, 7 do Hiếu và
Phong viết trên cùng bộ artefact. Mọi số dưới đây lấy từ `data/master/*.json` và các bảng sinh bởi
`python -m src.models.benchmark` / `python -m tools.error_report`.

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

## 8. Hạn chế

Xem `docs/data_limitations.md` — ba hạn chế chính: **giá rao không phải giá giao dịch**;
**`engine_capacity` thiếu 61,2% và `sub_model_trim` thiếu 55,7%**; **carmudi chỉ có 366 dòng** nên
không đủ cho một phân đoạn theo nền tảng. Thêm: chỉ một snapshot, không có lịch sử tai nạn/bảo dưỡng,
và 19 dòng mất nhãn bị loại chứ không điền.

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

_Các mục 3 và 7 do Phong viết, phần biên tập (một giọng văn, bố cục, PDF, form nộp) do người biên tập
làm; bản nháp này cố ý không viết thay số của họ._
