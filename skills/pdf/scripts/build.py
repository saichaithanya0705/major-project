"""
Build an A4 PDF from a pdf skill spec.

Usage: python build.py --spec spec.json --output summary.pdf
Prints {"path": ..., "pages": N} on success. Exit code 2 means the spec is invalid.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ACCENT = colors.HexColor("#1F4E79")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"\*([^*]+)\*")


class SpecError(ValueError):
    pass


def markup(text: str) -> str:
    """Escape text for reportlab and turn **bold**/*italic* into tags."""
    escaped = html.escape(str(text), quote=False)
    return _ITALIC.sub(r"<i>\1</i>", _BOLD.sub(r"<b>\1</b>", escaped))


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("DocTitle", parent=base["Title"], textColor=ACCENT, spaceAfter=6),
        "subtitle": ParagraphStyle("DocSubtitle", parent=base["Normal"], fontSize=13, textColor=colors.HexColor("#595959"), alignment=TA_CENTER, spaceAfter=4),
        "author": ParagraphStyle("DocAuthor", parent=base["Italic"], alignment=TA_CENTER, spaceAfter=14),
        1: ParagraphStyle("H1", parent=base["Heading1"], textColor=ACCENT),
        2: ParagraphStyle("H2", parent=base["Heading2"], textColor=ACCENT),
        3: ParagraphStyle("H3", parent=base["Heading3"]),
        "body": ParagraphStyle("Body", parent=base["BodyText"], fontSize=10.5, leading=15, spaceAfter=6),
        "cell": ParagraphStyle("Cell", parent=base["BodyText"], fontSize=9, leading=11),
        "head_cell": ParagraphStyle("HeadCell", parent=base["BodyText"], fontSize=9, leading=11, textColor=colors.white, fontName="Helvetica-Bold"),
        "caption": ParagraphStyle("Caption", parent=base["Italic"], fontSize=9, alignment=TA_CENTER, spaceAfter=10),
    }


def _list(items: list, styles: dict, numbered: bool) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(markup(item), styles["body"]), leftIndent=12) for item in items],
        bulletType="1" if numbered else "bullet",
        start="1" if numbered else None,
        leftIndent=14,
    )


def _table(table_spec: dict, styles: dict, width: float) -> Table:
    columns = [str(c) for c in table_spec.get("columns") or []]
    if not columns:
        raise SpecError("A section table has no columns")
    data = [[Paragraph(markup(c), styles["head_cell"]) for c in columns]]
    for row in table_spec.get("rows") or []:
        values = [row[i] if i < len(row) and row[i] is not None else "" for i in range(len(columns))]
        data.append([Paragraph(markup(value), styles["cell"]) for value in values])
    table = Table(data, colWidths=[width / len(columns)] * len(columns), repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BFBFBF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def _page_number(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#7F7F7F"))
    canvas.drawCentredString(A4[0] / 2, 1.2 * cm, f"Page {doc.page}")
    canvas.restoreState()


def build(spec: dict, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output), pagesize=A4, title=spec["title"], author=spec.get("author", ""),
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
    )
    styles = _styles()
    story: list = [Paragraph(markup(spec["title"]), styles["title"])]
    if spec.get("subtitle"):
        story.append(Paragraph(markup(spec["subtitle"]), styles["subtitle"]))
    if spec.get("author"):
        story.append(Paragraph(markup(spec["author"]), styles["author"]))
    story.append(Spacer(1, 8))

    for section in spec["sections"]:
        if section.get("page_break_before"):
            story.append(PageBreak())
        if section.get("heading"):
            story.append(Paragraph(markup(section["heading"]), styles[int(section.get("level") or 1)]))
        for text in section.get("paragraphs") or []:
            story.append(Paragraph(markup(text), styles["body"]))
        if section.get("bullets"):
            story.append(_list(section["bullets"], styles, numbered=False))
        if section.get("numbered"):
            story.append(_list(section["numbered"], styles, numbered=True))
        if section.get("table"):
            story.extend([_table(section["table"], styles, doc.width), Spacer(1, 10)])
        if section.get("image_path"):
            image_path = Path(str(section["image_path"])).expanduser()
            if image_path.is_file():
                image = Image(str(image_path))
                scale = min(doc.width / image.imageWidth, (10 * cm) / image.imageHeight, 1.0)
                image.drawWidth, image.drawHeight = image.imageWidth * scale, image.imageHeight * scale
                story.append(image)
            else:
                story.append(Paragraph(markup(f"(Image not found: {image_path})"), styles["caption"]))
        if section.get("caption"):
            story.append(Paragraph(markup(section["caption"]), styles["caption"]))

    doc.build(story, onFirstPage=_page_number, onLaterPages=_page_number)
    return doc.page


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    output = Path(args.output)
    try:
        pages = build(spec, output)
    except (SpecError, KeyError, TypeError) as exc:
        print(f"Invalid spec: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"path": str(output.resolve()), "pages": pages}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
