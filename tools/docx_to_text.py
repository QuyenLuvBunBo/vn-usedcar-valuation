"""Trích text từ file .docx (kể cả bảng biểu) — không cần pandoc/Word.

Chạy: python -m tools.docx_to_text <file.docx> [-o out.txt]
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _para_text(node) -> str:
    """Gộp text của 1 đoạn, có xử lý tab và ngắt dòng mềm."""
    parts: list[str] = []
    for child in node.iter():
        tag = child.tag
        if tag == f"{W}t":
            parts.append(child.text or "")
        elif tag == f"{W}tab":
            parts.append("\t")
        elif tag in (f"{W}br", f"{W}cr"):
            parts.append(" ")
    return "".join(parts).strip()


def _cell_text(cell) -> str:
    """Gộp text của 1 ô trong bảng."""
    return " ".join(t for t in (_para_text(p) for p in cell.findall(f"{W}p")) if t).strip()


def docx_to_text(path: Path) -> str:
    """Đọc word/document.xml và chuyển thành text (mỗi dòng 1 đoạn, bảng -> dạng 'a | b')."""
    with zipfile.ZipFile(path) as zf:
        with zf.open("word/document.xml") as fh:
            root = ET.parse(fh).getroot()

    body = root.find(f"{W}body")
    lines: list[str] = []
    for elem in body:
        if elem.tag == f"{W}p":
            text = _para_text(elem)
            if text:
                lines.append(text)
        elif elem.tag == f"{W}tbl":
            for row in elem.findall(f"{W}tr"):
                cells = [_cell_text(c) for c in row.findall(f"{W}tc")]
                if any(cells):
                    lines.append(" | ".join(cells))
            lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Trích text từ .docx")
    parser.add_argument("path", help="đường dẫn file .docx")
    parser.add_argument("-o", "--out", default=None, help="ghi ra file txt UTF-8")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print("Không thấy file:", path)
        return 1

    text = docx_to_text(path)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"Đã ghi {len(text)} ký tự -> {out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
