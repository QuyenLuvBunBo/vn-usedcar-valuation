# Bàn giao phần việc của Nguyễn Thế Phương

Ngày bàn giao: 04/11/2026. Phạm vi: việc chính và việc phụ của Phương trong kế
hoạch tuần 3. Các kết quả dưới đây được tạo từ 70.244 dòng train đã cung cấp.

## Năm dòng tóm tắt gửi người viết báo cáo

1. Đã triển khai `src/features/pipeline.py`: one-hot cho cột có tối đa 40 giá trị trên train, ordinal cho `age_band`, scaler và target encoding cho cặp `brand|model`.
2. Target encoding dùng 5 fold theo `duplicate_group_id`; 52.417 nhóm không bị chia sang hai phía của một fold; cặp chưa gặp nhận trung bình `log1p(price_vnd)` của phần train tương ứng.
3. Đã tạo `models/preprocess.joblib` và ma trận OOF gồm 70.244 dòng × 59 đặc trưng; các mô hình downstream phải dùng ma trận OOF để train.
4. Đã chạy qua 27 kiểm thử và kiểm tra độc lập toàn bộ giá trị target encoding OOF; chưa sử dụng validation/test và chưa công bố chỉ số dự báo.
5. Còn cần cột `imputed` gốc để fit 8 cờ theo từng trường; bản hiện tại chỉ có cờ tổng hợp từ `n_imputed`; tài liệu và metadata ghi rõ giới hạn này.

## Đối chiếu với phân công

| Yêu cầu | Trạng thái | Bằng chứng |
| --- | --- | --- |
| One-hot cho cột có tối đa 40 giá trị | Hoàn thành | Chọn nhánh từ cardinality của train, kiểm thử mốc 40/41 |
| Ordinal cho age_band | Hoàn thành | Thứ tự 0–2, 3–5, 6–9, 10–14, 15+; giá trị lạ = -1 |
| Target encoding brand và model có K-fold bên trong | Hoàn thành | GroupKFold 5 fold, kiểm thử thay đổi target của fold giữ lại |
| Scaler | Hoàn thành | Median còn thiếu và StandardScaler fit trên train |
| Cờ missing từ imputed | Mã nguồn hoàn thành; artifact còn thiếu dữ liệu | Có join theo listing_id và chế độ --require-imputed; chưa có imputed gốc |
| Lưu models/preprocess.joblib | Đã tạo bản aggregate_only | Fitted trên 70.244 dòng, 59 đặc trưng; load được trong tiến trình mới |
| tests/test_features.py | Hoàn thành | 27 kiểm thử chạy qua; log ở docs/test_results.txt |
| Encoder không học từ val | Hoàn thành trong phạm vi module | transform không thay đổi mapping, categories hoặc scaler |
| Giá trị lạ về trung bình toàn cục | Hoàn thành cho target encoder | Dùng mean log-target của train; trong OOF dùng mean của từng fold train |
| docs/features.md sinh bằng --describe | Hoàn thành | Có thống kê cardinality, chính sách missing, fold audit và phiên bản |
| Duy rà soát chéo | Chờ người thực hiện | Chưa có comment review, chưa tạo hoặc merge PR |

## Quyết định kỹ thuật cần ghi vào báo cáo

Các cột categorical có trên 40 giá trị dùng frequency encoding fit trên train;
cặp brand/model có thêm target encoding được làm trơn với hệ số 20. Frequency
encoding là quyết định triển khai để xử lý các cột vượt ngưỡng; đây chưa phải
kết luận thực nghiệm về chất lượng mô hình. Phần so sánh cardinality vẫn do
Quyết thực hiện.

`brand_retention_rate` và `province_price_index` bị loại khỏi X theo cấu hình mặc
định vì các giá trị đã được tính bằng target trên toàn bộ train. Dùng nguyên
các giá trị đó trong outer CV sẽ đưa thông tin target của fold giữ lại vào
đặc trưng. Có tùy chọn `--include-frozen-price-stats` cho giao thức train/val đã
chốt; phải ghi rõ bộ đặc trưng trong benchmark. Không sửa lại mã của Quyền
hoặc các thống kê gốc.

Việc điền khuyết và nhóm category upstream đã được thực hiện trước khi nhận CSV.
Muốn kiểm định hoàn toàn độc lập theo outer fold phải chạy lại các bước upstream
trong từng fold. Các kiểm thử ở đây chứng minh phạm vi encoder mới, không chứng
minh toàn bộ quá trình dựng dữ liệu upstream.

## Đầu vào còn thiếu và cách hoàn tất

Cần `data/master/train_cohort_imputed.csv`, hoặc CSV chỉ gồm `listing_id,imputed`
của đúng tập train. Không thể suy ngược tên các trường đã điền từ `n_imputed`.

```bash
python -m src.features.pipeline --features full \
  --cohort data/master/train_cohort_imputed.csv \
  --require-imputed --describe
```

Lệnh sẽ tạo lại đồng bộ joblib, tên đặc trưng, metadata và ma trận OOF. Với cùng
dữ liệu và schema này, tám cờ theo trường nâng số đặc trưng từ 59 lên 67. Mô hình
downstream cần được train lại sau khi đổi preprocessor.

## Điểm Duy cần rà soát

- Kiểm tra GroupKFold có giữ nguyên duplicate_group_id và mean của fold giữ lại không dùng target của chính fold đó.
- Kiểm tra luồng train dùng fit_transform hoặc ma trận OOF, còn val/test dùng transform.
- Kiểm tra việc ghi nhận bộ đặc trưng khi bật/tắt hai thống kê từ giá.
- Kiểm tra join imputed bằng listing_id và khả năng import src.features.pipeline khi load joblib.
- Chạy tests/test_features.py và thử tích hợp với mã train của nhóm 2 trước khi comment PR.

Chưa có quyền truy cập nội dung repository qua kết nối GitHub (HTTP 404), nên
chưa đối chiếu trực tiếp API với `src/models/train.py` hoặc chạy gate của repo.
Gói này không thay thế kết quả review của Duy. Tập test vẫn dành cho lần đánh
giá duy nhất tại M2 ngày 07/11/2026 theo kế hoạch.
