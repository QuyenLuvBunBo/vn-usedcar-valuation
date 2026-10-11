# Notebook

Quy ước để không conflict khi cả nhóm cùng làm EDA/model:

- Mỗi người tạo **một thư mục riêng theo tên mình**: `notebooks/quyen/`, `notebooks/bao/`…
  Không ai sửa notebook của người khác.
- **Luôn strip output trước khi commit** (output/execution_count làm diff loạn):

  ```powershell
  pip install nbstripout
  nbstripout --install        # tự động strip khi commit
  ```

- Tên notebook theo việc: `eda_gia_theo_hang.ipynb`, `baseline_median.ipynb`, …
- Notebook dài → tách hàm ổn định ra `src/` (ví dụ `src/data_prep/`), notebook chỉ gọi lại.

Phân công Tuần 2 (theo kế hoạch): EDA ở tiểu ban 3 (Phong, Tuấn Anh, Quang);
missing data ở tiểu ban 2 (Hiếu, Bảo, Duy); merge/dedupe ở tiểu ban 1 (Quyền, Quyết, Phương).
