"""
Build a Word document from a docx skill spec.

Usage: python build.py --spec spec.json --output report.docx
Prints {"path": ..., "sections": N} on success. Exit code 2 means the spec is invalid.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

_INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*)")


class SpecError(ValueError):
    pass


def add_rich_text(paragraph, text: str) -> None:
    """Add text with **bold** and *italic* spans as separate runs."""
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            paragraph.add_run(part[2:-2]).bold = True
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            paragraph.add_run(part[1:-1]).italic = True
        else:
            paragraph.add_run(part)


def build(spec: dict, output: Path) -> int:
    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)

    document.add_heading(spec["title"], level=0)
    if spec.get("subtitle"):
        subtitle = document.add_paragraph(spec["subtitle"])
        subtitle.runs[0].font.size = Pt(13)
        subtitle.runs[0].font.color.rgb = RGBColor(0x59, 0x59, 0x59)
    if spec.get("author"):
        document.add_paragraph(spec["author"]).runs[0].italic = True

    sections = spec["sections"]
    for section in sections:
        if section.get("page_break_before"):
            document.add_page_break()
        if section.get("heading"):
            document.add_heading(section["heading"], level=int(section.get("level") or 1))
        for text in section.get("paragraphs") or []:
            add_rich_text(document.add_paragraph(), str(text))
        for text in section.get("bullets") or []:
            add_rich_text(document.add_paragraph(style="List Bullet"), str(text))
        for text in section.get("numbered") or []:
            add_rich_text(document.add_paragraph(style="List Number"), str(text))

        table_spec = section.get("table")
        if table_spec:
            columns = [str(c) for c in table_spec.get("columns") or []]
            if not columns:
                raise SpecError("A section table has no columns")
            rows = table_spec.get("rows") or []
            table = document.add_table(rows=len(rows) + 1, cols=len(columns))
            table.style = "Light Grid Accent 1"
            for col, name in enumerate(columns):
                cell = table.cell(0, col)
                cell.text = name
                cell.paragraphs[0].runs[0].bold = True
            for r, row in enumerate(rows, start=1):
                for col in range(len(columns)):
                    value = row[col] if col < len(row) else ""
                    table.cell(r, col).text = "" if value is None else str(value)
            document.add_paragraph()

        if section.get("image_path"):
            image_path = Path(str(section["image_path"])).expanduser()
            if image_path.is_file():
                document.add_picture(str(image_path), width=Inches(6))
                document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            else:
                document.add_paragraph(f"(Image not found: {image_path})").runs[0].italic = True
        if section.get("caption"):
            caption = document.add_paragraph(section["caption"])
            caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
            caption.runs[0].italic = True

    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output))
    return len(sections)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    output = Path(args.output)
    try:
        count = build(spec, output)
    except (SpecError, KeyError, TypeError) as exc:
        print(f"Invalid spec: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"path": str(output.resolve()), "sections": count}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
