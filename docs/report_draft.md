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

8 mô hình × 2 bộ đặc trưng, **không tuning** (ngân sách 0s — cột `tuning` trong
`docs/benchmark.md` ghi rõ), mọi số trên val, không có số test:

| Bộ | Mô hình | R²(log) | MAPE | median APE | MAE (VND) |
| --- | --- | ---: | ---: | ---: | ---: |
| full | **catboost** | **0,9465** | 12,0% | 6,9% | 91.143.312 |
| full | **lightgbm** | 0,9462 | **11,5%** | 6,3% | 82.441.420 |
| full | rf | 0,9411 | 12,1% | 6,4% | 87.698.367 |
| full | xgboost | 0,9409 | **11,1%** | **5,7%** | **78.256.273** |
| full | ridge | 0,8970 | 18,0% | 10,4% | 141.897.201 |
| full | median (baseline) | 0,8773 | 18,8% | 7,3% | 101.649.813 |
| full | elasticnet | 0,8722 | 21,2% | 13,4% | 174.713.377 |
| full | lasso | 0,8561 | 22,9% | 14,8% | 190.664.684 |
| minimal | lightgbm | 0,9447 | 11,7% | 6,4% | 84.885.802 |
| minimal | catboost | 0,9438 | 12,3% | 7,1% | 95.474.212 |
| minimal | xgboost | 0,9388 | 11,3% | 6,0% | 80.850.994 |
| minimal | rf | 0,9370 | 12,6% | 6,7% | 94.182.039 |

Bốn điều phải nói thẳng trong mục này, kể cả khi nó làm mất tính "thành tích":

1. **Sàn canary là 0,946 / 11,6%; mô hình tốt nhất chỉ hơn ở R² 0,0005 và *kém* hơn ở MAPE.** Không
   có "bước nhảy" nào từ mô hình phức tạp: LightGBM chưa tune đã 0,9447–0,9462.
2. **CatBoost và LightGBM hoà nhau** (0,9465 vs 0,9462). Wilcoxon theo cặp trên APE nói catboost nhỉnh
   hơn (p = 2,3e-15) — nhưng R² chỉ chênh 0,0003 và seed sd là 0,0003, nên thứ tự này không đáng để
   đổi 291s lấy 6,5s huấn luyện.
3. **XGBoost thắng ở không gian VND** (MAPE 11,1%, MAE 78,3 triệu) dù R² thấp hơn — tức "mô hình tốt
   nhất" phụ thuộc metric, và báo cáo phải nói rõ chọn metric nào vì lý do gì.
4. **Baseline median mạnh hơn ridge ở median APE** (7,3% vs 10,4%) dù R² thấp hơn (0,8773 vs 0,8970).
   Một mô hình tuyến tính "trông tốt hơn" theo R² nhưng tệ hơn ở chính giữa phân bố — đúng loại kết
   luận sai mà bảng median APE sinh ra để chặn.

Bộ **full** chỉ hơn **minimal** khoảng 0,0015 R² (0,9462 vs 0,9447). Với seed sd 0,0003 thì chênh lệch
này nhỏ nhưng có thật (Wilcoxon p = 7,4e-07), nên giữ full là hợp lý nhưng không được mô tả là "cải
thiện lớn".

Đường cong học (LightGBM, 10/25/50/100% train): **0,8947 → 0,9107 → 0,9311 → 0,9440** — vẫn đang
tăng, nên trần hiện tại là *dữ liệu*, không phải đặc trưng.

**Mô hình dùng cho `predictions_val.csv`: lightgbm / full.** Lý do ghi rõ: R² hoà với catboost trong
phạm vi nhiễu, MAPE tốt hơn (11,5% vs 12,0%), và LightGBM cho quantile trực tiếp để sinh P10/P90 cho
T3 mà không phải thêm một mô hình thứ ba.

## 6. Phân tích sai số

- **Median APE 6,3%, MAPE 11,5%** trên val; đây là hai con số khác nhau và cả hai đều đúng — MAPE bị
  kéo bởi đuôi phải, median APE mô tả trải nghiệm của một tin rao điển hình.
- **Nhãn bất thường** (`data/master/anomaly_labels.csv`, review rate hiệu chỉnh đúng **3,00%**,
  P10/P90 lấy từ mô hình quantile của LightGBM): Fair **10.765** · Overpriced **2.103** ·
  Bargain **1.990** · Suspicious **106**.
- **Theo nhóm sai số** (`docs/error_taxonomy.md`, quy tắc hiển nhiên để đọc lại):
  tin dưới 200 triệu **1.461** tin, median APE **13,3%**, Δ trung bình **+25,1%** — mô hình **định giá
  cao** xe rẻ, vì nhóm này chứa nhiều giá đặt cọc/giá ảo; km bất thường **118** tin / 10,0%; nhóm còn
  lại **13.385** tin / 5,9%.
- **Theo nguồn**: carmudi **10,0%** (chỉ 105 tin) · chotot 7,2% (2.874) · muaban 6,6% · tinbanxe 6,6% ·
  carpla 6,5% · bonbanh 6,0% · oto.com.vn 6,0% · vucar 5,0%. Sai số không đều giữa các sàn và sàn nhỏ
  nhất có sai số lớn nhất, nên một MAPE tổng không đủ.
- **Theo decile giá**: decile rẻ nhất (< 200 triệu) có median APE **13,2%**, gần gấp đôi các decile
  phía trên (6,8% / 5,6%) — mô hình yếu nhất đúng ở nơi người mua ít tiền nhất.
- **Độ quan trọng** (`data/master/feature_importance.csv`): `brand_age_band` 0,510 ·
  `manufacture_year` 0,262 · `model` 0,231 · `model_group` 0,180 · `brand` 0,132 · `engine_capacity`
  0,130. Ba đặc trưng đầu đều là "xe gì, đời nào" — khớp với ablation ở mục 4.
- **Ba case study** (`docs/case_studies.md`, chọn bằng quy tắc nên tái lập được):
  `MUA_71248118` Toyota Corolla Cross 2022 rao **7,35 tỷ** trong khi mô hình ước **623 triệu**
  (Δ −91,5% — giá đặt cọc ảo); `CHOTOT_134989809` Aion Y Plus 2024 với **999.998 km** (Δ +502%);
  `CARPLA_F8W47` Audi Q5 2024 nhập khẩu rao **218 triệu** so với ước lượng **2,14 tỷ** (Δ +882%).

Ba case này không phải lỗi mô hình có thể sửa bằng tuning: chúng là **giá đặt cọc/giá ảo**, **odometer
bị chỉnh**, và **xe nhập khẩu**. Mục 7 phải nói rằng sản phẩm cần *dữ liệu* (lịch sử tai nạn, xác nhận
giá giao dịch) chứ không cần thêm một mô hình nữa.

_Các mục 3 và 7 do Phong viết, phần biên tập (một giọng văn, bố cục, PDF, form nộp) do người biên tập
làm; bản nháp này cố ý không viết thay số của họ._
