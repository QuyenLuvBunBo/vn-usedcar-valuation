"""Build docs/ke_hoach_tuan3.docx — the Vietnamese week-3 assignment plan for Group 14.

Optional dependency (not in requirements.txt): `pip install python-docx`.
Regenerate after editing the content here:

    python tools/build_plan_docx.py

The document is A4, Times New Roman 13 pt, with one table per sub-team and a page-number footer.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(__file__).resolve().parents[1] / "docs" / "ke_hoach_tuan3.docx"
FONT = "Times New Roman"
BODY = Pt(13)
HEAD_COLOR = RGBColor(0x1F, 0x38, 0x64)
TABLE_WIDTH = Cm(16.0)          # A4 (21 cm) - margins (2.5 + 2.5)


# --------------------------------------------------------------------- helpers
def shade(cell, hex_fill: str) -> None:
    """Fill a table cell with a colour (header rows)."""
    element = OxmlElement("w:shd")
    element.set(qn("w:val"), "clear")
    element.set(qn("w:color"), "auto")
    element.set(qn("w:fill"), hex_fill)
    cell._tc.get_or_add_tcPr().append(element)


def set_widths(table, widths_cm: list[float]) -> None:
    table.autofit = False
    for row in table.rows:
        for cell, width in zip(row.cells, widths_cm):
            cell.width = Cm(width)
    for column, width in zip(table.columns, widths_cm):
        column.width = Cm(width)


def add_table(document, headers: list[str], rows: list[list[str]],
              widths: list[float], size: float = 11.5) -> None:
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for cell, text in zip(table.rows[0].cells, headers):
        cell.text = ""
        run = cell.paragraphs[0].add_run(text)
        run.bold = True
        run.font.size = Pt(size)
        run.font.name = FONT
        cell.paragraphs[0].paragraph_format.space_after = Pt(2)
        shade(cell, "D9E2F3")
    for values in rows:
        cells = table.add_row().cells
        for cell, text in zip(cells, values):
            cell.text = ""
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(2)
            for index, line in enumerate(str(text).split("\n")):
                run = paragraph.add_run(line)
                run.font.size = Pt(size)
                run.font.name = FONT
                if index < len(str(text).split("\n")) - 1:
                    run.add_break()
    set_widths(table, widths)
    document.add_paragraph()


def add_bullets(document, items: list[str], style: str = "List Bullet") -> None:
    for item in items:
        paragraph = document.add_paragraph(style=style)
        paragraph.paragraph_format.space_after = Pt(2)
        run = paragraph.add_run(item)
        run.font.size = BODY
        run.font.name = FONT


def add_code(document, lines: list[str]) -> None:
    for line in lines:
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.left_indent = Cm(0.6)
        paragraph.paragraph_format.space_after = Pt(0)
        run = paragraph.add_run(line)
        run.font.name = "Consolas"
        run.font.size = Pt(10.5)
    document.add_paragraph()


def add_heading(document, text: str, level: int = 1) -> None:
    heading = document.add_heading(level=level)
    run = heading.add_run(text)
    run.font.name = FONT
    run.font.size = Pt(14 if level == 1 else 12.5)
    run.font.color.rgb = HEAD_COLOR
    run.bold = True
    heading.paragraph_format.space_before = Pt(12 if level == 1 else 8)
    heading.paragraph_format.space_after = Pt(6)


def add_paragraph(document, text: str, bold: bool = False, italic: bool = False,
                  size: float = 13, align=None) -> None:
    paragraph = document.add_paragraph()
    if align is not None:
        paragraph.alignment = align
    paragraph.paragraph_format.space_after = Pt(4)
    run = paragraph.add_run(text)
    run.font.name = FONT
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic


def add_rule(document) -> None:
    """A horizontal line as a paragraph bottom border (never a table)."""
    paragraph = document.add_paragraph()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "8")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "1F3864")
    borders.append(bottom)
    paragraph._p.get_or_add_pPr().append(borders)


def add_page_number_footer(section) -> None:
    paragraph = section.footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run("Kế hoạch tuần 3 — Nhóm 14 — trang ")
    run.font.name = FONT
    run.font.size = Pt(10)
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = "PAGE"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for element in (begin, instruction, end):
        field_run = paragraph.add_run()
        field_run.font.name = FONT
        field_run.font.size = Pt(10)
        field_run._r.append(element)


# ----------------------------------------------------------------------- build
def build() -> Document:
    document = Document()

    # A4, Vietnamese-report margins, Times New Roman body
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(2)
    section.left_margin = section.right_margin = Cm(2.5)
    normal = document.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = BODY
    normal.paragraph_format.line_spacing = 1.15
    normal.paragraph_format.space_after = Pt(4)
    add_page_number_footer(section)

    # ---------------------------------------------------------------- title
    add_paragraph(document, "INTRODUCTION TO DATA SCIENCE — ĐỒ ÁN NHÓM 14",
                  bold=True, size=11, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_paragraph(document, "KẾ HOẠCH TUẦN 3", bold=True, size=20,
                  align=WD_ALIGN_PARAGRAPH.CENTER)
    add_paragraph(document, "Kỹ nghệ đặc trưng · Mô hình định giá · Phát hiện bất thường",
                  italic=True, size=12.5, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_paragraph(document, "Đề tài: Định giá xe ô tô đã qua sử dụng và phát hiện tin đăng bất thường",
                  size=12, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_paragraph(document, "Thời gian: 31/10/2026 – 06/11/2026  ·  Hạn nộp báo cáo: 10/11/2026",
                  bold=True, size=12, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_rule(document)

    add_paragraph(
        document,
        "Tuần 3 tạo ra toàn bộ số liệu cho báo cáo “Initial Results on Applying ML Models” mà giảng "
        "viên yêu cầu (hạn 10/11/2026). Tuần này sản xuất số liệu và tệp mô hình; từ 07/11 đến 10/11 "
        "chỉ còn viết báo cáo, rà soát và nộp. Mỗi thành viên cần trả lời được hai câu: tôi bàn giao "
        "gì, và khi nào.")

    # ------------------------------------------------------- 1. mốc thời gian
    add_heading(document, "1. Mốc thời gian và sản phẩm phải có")
    add_table(
        document,
        ["Mốc", "Ngày", "Sản phẩm / điều kiện"],
        [
            ["Khởi động", "T7 31/10", "Cài thư viện, tạo nhánh riêng, TB1 công bố danh sách cột đặc trưng"],
            ["M1 — con số đầu tiên", "T2 02/11", "model_results.json có ≥ 3 dòng và đọc được R² trên tập val"],
            ["M2 — chốt mô hình", "T6 06/11", "Mô hình tốt nhất cố định, đánh giá test đúng 1 lần, số liệu đã ghi"],
            ["Viết và rà soát báo cáo", "T7 07/11 – T2 09/11", "Báo cáo hoàn chỉnh, rà soát 2 lượt, chạy thử nộp"],
            ["Nộp bài", "T3 10/11, trước 12:00", "Nộp qua form của giảng viên, đúng định dạng đã thống nhất"],
        ],
        widths=[4.2, 3.8, 8.0],
    )

    # ----------------------------------------------------------- 2. dữ liệu
    add_heading(document, "2. Dữ liệu đầu vào (đã chốt — không thu thập thêm trong tuần này)")
    add_table(
        document,
        ["Tệp", "Số dòng", "Dùng để"],
        [
            ["data/master/train_cohort_imputed.csv", "70.244", "Fit mọi thống kê học từ dữ liệu"],
            ["data/master/val_cohort_imputed.csv", "14.964", "Chọn mô hình và chọn ngưỡng"],
            ["data/master/test_cohort_imputed.csv", "14.980", "Đánh giá đúng một lần, tại thời điểm chốt"],
        ],
        widths=[7.2, 2.4, 6.4],
    )
    add_paragraph(document, "Mỗi dòng có 26 cột: 21 cột theo hợp đồng dữ liệu, cộng tier, "
                            "duplicate_group_id, quality_flags, imputed và model_group. Bốn nguyên tắc "
                            "bắt buộc:")
    add_bullets(document, [
        "price_vnd là biến mục tiêu, tuyệt đối không đưa vào X. Cũng không dùng: raw_price_text, "
        "price_status, listing_date, scraped_at, source_url, listing_id, quality_flags.",
        "Mọi thống kê học từ dữ liệu chỉ được fit trên train; val và test chỉ biến đổi, không fit "
        "(encoder, target encoding, scaler, brand_retention_rate đều nằm trong luật này).",
        "Không crawl thêm và không dựng lại split trong tuần này: đổi dữ liệu là đổi "
        "duplicate_group_id, mọi con số trong báo cáo sẽ lệch khỏi dữ liệu.",
        "Huấn luyện trên log1p(price_vnd) và báo cáo chỉ số ở cả không gian log và VND.",
    ])

    # ------------------------------------------------------- 3. việc chung
    add_heading(document, "3. Việc chung ngày đầu tiên — mọi thành viên")
    add_paragraph(document, "Môi trường hiện chưa có thư viện học máy, đây là việc chặn toàn bộ tuần:")
    add_code(document, [
        "pip install scikit-learn lightgbm joblib",
        "pip install xgboost catboost optuna shap   # tuỳ chọn, chỉ khi cài được trên Windows",
        "python -c \"import sklearn, lightgbm, joblib; print('ok')\"",
    ])
    add_paragraph(document, "requirements.txt là tệp dùng chung: Hiếu mở pull request bổ sung ba dòng phụ "
                            "thuộc bắt buộc, Quyền và Phương review. Trước khi PR được merge, không ai "
                            "thêm import mới khiến bản clone sạch không chạy được.")

    # ---------------------------------------------------------- 4. phân công
    add_heading(document, "4. Phân công theo tiểu ban")
    add_paragraph(document, "Mục tiêu chung: một bảng so sánh mô hình trung thực, một bộ nhãn bất thường "
                            "có căn cứ, và một báo cáo mà mọi con số đều tái lập được bằng lệnh trong "
                            "kho mã.", italic=True)

    add_heading(document, "4.1. Tiểu ban 1 — Kỹ nghệ đặc trưng và tiền xử lý", level=2)
    add_table(
        document,
        ["Thành viên", "Nhiệm vụ chính", "Hoàn thành khi"],
        [
            ["Lê Thế Quyền\n(phụ trách)",
             "src/features/build_features.py: vehicle_age, km_per_year, is_luxury_segment, cờ theo sàn, "
             "giá trên mỗi km; viết tools/model_gate.py chặn cột bị cấm lọt vào X",
             "Một lệnh ghi ra ba bảng feature và in số dòng/số cột; gate trả mã 1 khi phát hiện rò rỉ"],
            ["Nguyễn Thế Phương",
             "src/features/pipeline.py: ColumnTransformer — one-hot cho cột ít giá trị, encode "
             "brand|model (fit bên trong fold), scale biến số, cờ missing sinh từ cột imputed; lưu "
             "models/preprocess.joblib",
             "Fit trên train rồi transform val/test bằng một lệnh; có test chứng minh encoder không "
             "nhìn thấy val"],
            ["Nguyễn Văn Quyết",
             "brand_retention_rate (trung vị giá theo hãng × nhóm tuổi, chỉ tính trên train) và geo_tier; "
             "chốt dùng model gốc hay model_group",
             "Hai đặc trưng có công thức rõ ràng và ghi chú “fit trên train” trong báo cáo"],
        ],
        widths=[3.5, 7.5, 5.0],
    )

    add_heading(document, "4.2. Tiểu ban 2 — Mô hình định giá có giám sát", level=2)
    add_table(
        document,
        ["Thành viên", "Nhiệm vụ chính", "Hoàn thành khi"],
        [
            ["Phạm Xuân Hiếu\n(phụ trách)",
             "src/models/train.py --model … --features minimal|full: nạp bảng feature, huấn luyện, tính "
             "R²/RMSE/MAE/MAPE ở cả log và VND, lưu models/<ten>.joblib, seed cố định",
             "Mỗi mô hình chạy bằng một lệnh và tự ghi một dòng vào model_results.json"],
            ["Đinh Gia Bảo",
             "Mô hình cơ sở và tuyến tính: trung vị theo brand|model|year, Ridge, Lasso; "
             "src/models/benchmark.py dựng bảng markdown từ model_results.json",
             "docs/benchmark.md có tối thiểu 4 dòng (cơ sở + 3 mô hình)"],
            ["Phạm Hải Duy",
             "Mô hình cây: Random Forest, LightGBM (XGBoost/CatBoost nếu cài được) và tuning bằng "
             "RandomizedSearchCV (≤ 40 lần fit) hoặc Optuna (≤ 50 trial); feature importance",
             "Chọn mô hình tốt nhất trên val, ghi rõ ngân sách tuning và không gian tìm kiếm"],
        ],
        widths=[3.5, 7.5, 5.0],
    )
    add_bullets(document, [
        "Chọn mô hình trên val; test chỉ chạy một lần tại thời điểm chốt.",
        "Chỉ so sánh các mô hình trên cùng một bộ đặc trưng và cùng một split.",
        "Mô hình không được tuning phải ghi rõ là không tuning — không trình bày như đã tối ưu.",
    ])

    add_heading(document, "4.3. Tiểu ban 3 — Phát hiện bất thường và gán nhãn thị trường", level=2)
    add_table(
        document,
        ["Thành viên", "Nhiệm vụ chính", "Hoàn thành khi"],
        [
            ["Trịnh Hải Phong\n(phụ trách)",
             "src/models/anomaly.py: sai số tương đối Δ = (ŷ − y)/y, IsolationForest trên bảng đặc "
             "trưng, bốn nhãn Bargain Deal / Fair Value / Overpriced / Suspicious; ngưỡng chọn trên val",
             "data/master/anomaly_labels.csv (listing_id, delta, iso_score, label, reason) và bảng "
             "ngưỡng trong báo cáo"],
            ["Đỗ Tuấn Anh",
             "Hai case study (một tin kiểu đặt cọc ảo, một tin odometer bất thường) và ma trận nhầm lẫn "
             "dạng proxy: quality_flags (luật) × nhãn Suspicious (mô hình); ghi rõ đây là proxy, không "
             "phải ground truth",
             "Ma trận nhỏ và hai tin kèm URL cùng số liệu cụ thể"],
            ["Nguyễn Huy Quang",
             "Cập nhật EDA trên master 100.887 dòng: giá theo vùng (chotot nay 19.426 tin), chênh lệch "
             "giá giữa các sàn, 3–4 hình dùng lại cho mục 3 của báo cáo; giữ script chạy lại được",
             "eda_summary.md được tạo lại và có danh sách hình đưa vào báo cáo"],
        ],
        widths=[3.5, 7.5, 5.0],
    )
    add_paragraph(document, "Lưu ý phải giữ trong bài viết: giá rao thấp không đủ chứng minh là “hời”, và "
                            "sai số lớn không đủ chứng minh là gian lận. Nhãn chỉ là hàng đợi để rà soát.",
                  italic=True)

    # ------------------------------------------------------ 5. hợp đồng bàn giao
    add_heading(document, "5. Hợp đồng bàn giao giữa ba tiểu ban")
    add_paragraph(document, "Làm song song chỉ merge được nếu artefact có tên và cấu trúc cố định. Chủ sở "
                            "hữu công bố bản đầu tiên trước thứ Hai 02/11 và thông báo trong nhóm:")
    add_table(
        document,
        ["Artefact", "Chủ sở hữu", "Đường dẫn", "Ai dùng"],
        [
            ["Bảng đặc trưng", "Quyền (TB1)", "data/master/{train,val,test}_features.csv", "TB2, TB3"],
            ["Preprocessor đã fit", "Phương (TB1)", "models/preprocess.joblib", "TB2, TB3"],
            ["Bảng so sánh mô hình", "Bảo (TB2)", "data/master/model_results.json, docs/benchmark.md", "mục 5 báo cáo"],
            ["Dự đoán trên tập test", "Hiếu (TB2)", "data/master/predictions_test.csv", "TB3"],
            ["Nhãn bất thường", "Phong (TB3)", "data/master/anomaly_labels.csv", "mục 7 báo cáo"],
        ],
        widths=[4.0, 3.2, 6.0, 2.8],
    )
    add_paragraph(document, "predictions_test.csv phải có đủ các cột: listing_id, duplicate_group_id, "
                            "brand, model, manufacture_year, mileage_km, location_province, "
                            "source_platform, price_vnd, y_pred_log, y_pred_vnd, residual, "
                            "abs_pct_error. TB3 không huấn luyện lại mô hình, chỉ đọc tệp này.")

    # ------------------------------------------------------------ 6. lịch ngày
    add_heading(document, "6. Lịch làm việc theo ngày")
    add_table(
        document,
        ["Ngày", "Nội dung"],
        [
            ["T7 31/10", "Cài thư viện; mở PR requirements.txt; mỗi người tạo nhánh từ main; TB1 công bố danh sách cột feature"],
            ["CN 01/11", "TB1 dựng bảng đặc trưng; TB2 chạy baseline trung vị + Ridge trên bộ minimal; TB3 tính Δ từ dự báo baseline"],
            ["T2 02/11", "MỐC M1: model_results.json có ≥ 3 dòng, đọc được R² trên val — chủ động báo trong nhóm"],
            ["T3 03/11", "Mô hình cây chạy được; preprocess.joblib v1; TB3 có anomaly_labels.csv đầu tiên"],
            ["T4 04/11", "Tuning; bộ đặc trưng đầy đủ; TB2 phân tích sai số theo hãng/phân khúc/sàn"],
            ["T5 05/11", "Hoàn tất bảng so sánh v1 (≥ 5 mô hình × 2 bộ đặc trưng); vẽ hình cho báo cáo"],
            ["T6 06/11", "MỐC M2: chốt mô hình tốt nhất, đánh giá test đúng một lần, mọi số liệu đã ghi; sau mốc này không đổi đặc trưng"],
            ["T7 07/11 – T2 09/11", "Viết báo cáo theo mục 8, rà soát chéo hai lượt, chạy thử quy trình nộp"],
            ["T3 10/11", "Nộp form trước 12:00"],
        ],
        widths=[4.0, 12.0],
    )

    # ------------------------------------------------------------- 7. định nghĩa
    add_heading(document, "7. Định nghĩa “xong” của tuần 3")
    add_bullets(document, [
        "Chạy được từ bản clone sạch: python -m src.features.build_features và "
        "python -m src.models.train --model lgbm, sinh đủ artefact ở mục 5.",
        "docs/benchmark.md so sánh ≥ 5 mô hình trên val, ghi rõ bộ đặc trưng và ngân sách tuning, và "
        "chỉ có đúng một cột test được điền tại thời điểm chốt.",
        "Có anomaly_labels.csv, bảng ngưỡng, hai case study và ma trận nhầm lẫn proxy.",
        "tools/model_gate.py cùng bộ unit test đều chạy qua; nếu có rò rỉ dữ liệu thì gate phải báo lỗi "
        "thay vì vẫn cho ra điểm số.",
        "Mọi con số nêu trong báo cáo đều tái lập được bằng một lệnh trong kho mã.",
    ], style="List Number")

    # ------------------------------------------------------------ 8. báo cáo
    add_heading(document, "8. Phân công viết báo cáo (07/11 – 10/11)")
    add_table(
        document,
        ["Mục", "Người viết", "Nội dung"],
        [
            ["1. Tóm tắt quy trình", "Quyền", "8 sàn, 100.887 dòng, khử trùng lặp, cách chia train/val/test và lý do"],
            ["2. Chất lượng dữ liệu", "Hiếu", "tỷ lệ thiếu, 5 nhóm lỗi đã sửa, số dòng bị loại khỏi cohort kèm lý do"],
            ["3. Phân tích khám phá", "Quang", "phân phối giá, giá theo năm, theo số km, chênh lệch giữa các sàn"],
            ["4. Đặc trưng", "Phương", "bảng đặc trưng, cách mã hoá, các biện pháp chống rò rỉ"],
            ["5. So sánh mô hình", "Duy", "bảng chỉ số, ngân sách tuning, mô hình thắng và lý do"],
            ["6. Phân tích sai số", "Bảo", "sai số theo hãng, theo phân khúc, theo sàn; điều mô hình không thấy được"],
            ["7. Bất thường", "Phong", "Δ, IsolationForest, ngưỡng, case study"],
            ["8. Hạn chế", "Tuấn Anh", "giá rao ≠ giá giao dịch, độ lệch bộ đếm chotot, mặc định coupe của carmudi, engine điền 61%"],
            ["Rà soát, định dạng, nộp bài", "Quyết", "thống nhất văn phong, một bố cục, kiểm tra form và hạn nộp"],
        ],
        widths=[4.6, 2.8, 8.6],
    )

    # -------------------------------------------------------------- 9. rủi ro
    add_heading(document, "9. Rủi ro và phương án dự phòng")
    add_table(
        document,
        ["Rủi ro", "Phương án"],
        [
            ["LightGBM/CatBoost không cài được trên Windows",
             "Dùng HistGradientBoostingRegressor của scikit-learn làm mô hình cây; ghi rõ trong báo cáo là có thay thế"],
            ["R² thấp hơn mục tiêu 0,88",
             "Báo cáo số thật, bổ sung log target và target encoding, giải thích phần dữ liệu còn thiếu (trim trống 56%, engine phải điền 61%)"],
            ["Tuning tốn thời gian",
             "Giới hạn 40 lần fit ngẫu nhiên, ghi rõ ngân sách, giữ mô hình chưa tuning làm dòng cơ sở"],
            ["Một tiểu ban bị chậm",
             "Hợp đồng ở mục 5 là chuẩn: các nhóm khác vẫn chạy tiếp với artefact mẫu miễn đúng cột"],
            ["Ai đó muốn thêm dữ liệu",
             "Không làm trong tuần này. Sau 10/11 mới đổi dữ liệu, và khi đó dựng lại split cùng toàn bộ số liệu một lần"],
        ],
        widths=[6.0, 10.0],
    )

    # ------------------------------------------------------------ 10. checklist
    add_heading(document, "10. Danh sách kiểm tra trước khi nộp")
    add_bullets(document, [
        "☐ Cài đủ thư viện và PR requirements.txt đã được merge.",
        "☐ model_results.json có đủ mô hình, mỗi dòng ghi rõ bộ đặc trưng và ngân sách tuning.",
        "☐ Chỉ số trên test được điền đúng một lần, tại M2 ngày 06/11.",
        "☐ anomaly_labels.csv có bảng ngưỡng đi kèm và hai case study có URL.",
        "☐ Báo cáo nêu rõ giá rao không phải giá giao dịch, và nêu các hạn chế dữ liệu.",
        "☐ Mọi hình và bảng trong báo cáo tái lập được bằng lệnh trong kho mã.",
        "☐ Đã kiểm tra định dạng, số trang, tên tệp và người nộp theo thông báo của giảng viên.",
        "☐ Nộp trước 12:00 ngày 10/11, giữ buổi chiều làm dự phòng.",
    ])

    return document


if __name__ == "__main__":
    document = build()
    document.save(OUT)
    print(f"saved {OUT}")




