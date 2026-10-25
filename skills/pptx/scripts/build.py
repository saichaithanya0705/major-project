"""
Build a 16:9 PowerPoint deck from a pptx skill spec.

Usage: python build.py --spec spec.json --output deck.pptx
Prints {"path": ..., "slides": N} on success. Exit code 2 means the spec is invalid.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

MAX_BULLETS_PER_SLIDE = 6
DEFAULT_PRIMARY = "1F4E79"
SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)
MARGIN = Inches(0.6)
TITLE_TOP = Inches(0.45)
TITLE_HEIGHT = Inches(1.0)
BODY_TOP = Inches(1.6)
DARK_TEXT = RGBColor(0x26, 0x26, 0x26)
MUTED_TEXT = RGBColor(0x59, 0x59, 0x59)

# Default-template layout indexes.
LAYOUT_TITLE = 0
LAYOUT_SECTION = 2
LAYOUT_BLANK = 6


class SpecError(ValueError):
    pass


def _rgb(hex_color: str | None) -> RGBColor:
    value = (hex_color or DEFAULT_PRIMARY).lstrip("#")
    return RGBColor.from_string(value.upper())


def _bullet(item) -> tuple[str, int]:
    if isinstance(item, str):
        return item, 0
    return str(item.get("text", "")), int(item.get("level", 0) or 0)


def _chunks(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)] or [[]]


class DeckBuilder:
    def __init__(self, spec: dict) -> None:
        theme = spec.get("theme") or {}
        self.primary = _rgb(theme.get("primary_color"))
        self.font = theme.get("font") or "Calibri"
        self.prs = Presentation()
        self.prs.slide_width = SLIDE_WIDTH
        self.prs.slide_height = SLIDE_HEIGHT

    # Shared pieces -------------------------------------------------------

    def _text_box(self, slide, left, top, width, height, text, *, size, bold=False, color=DARK_TEXT, align=None):
        box = slide.shapes.add_textbox(left, top, width, height)
        frame = box.text_frame
        frame.word_wrap = True
        paragraph = frame.paragraphs[0]
        paragraph.text = text
        if align is not None:
            paragraph.alignment = align
        for run in paragraph.runs:
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.name = self.font
            run.font.color.rgb = color
        return box

    def _content_slide(self, title: str):
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[LAYOUT_BLANK])
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(0.18), SLIDE_HEIGHT)
        bar.fill.solid()
        bar.fill.fore_color.rgb = self.primary
        bar.line.fill.background()
        self._text_box(
            slide, MARGIN, TITLE_TOP, SLIDE_WIDTH - 2 * MARGIN, TITLE_HEIGHT, title,
            size=32, bold=True, color=self.primary,
        )
        return slide

    def _fill_bullets(self, frame, bullets: list, *, size: int = 22) -> None:
        frame.word_wrap = True
        for index, item in enumerate(bullets):
            text, level = _bullet(item)
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.text = ("• " if level == 0 else "– ") + text
            paragraph.level = level
            paragraph.space_after = Pt(10)
            for run in paragraph.runs:
                run.font.size = Pt(size - 3 * level)
                run.font.name = self.font
                run.font.color.rgb = DARK_TEXT if level == 0 else MUTED_TEXT

    @staticmethod
    def _notes(slide, notes: str | None) -> None:
        if notes:
            slide.notes_slide.notes_text_frame.text = notes

    # Layouts -------------------------------------------------------------

    def title(self, data: dict) -> None:
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[LAYOUT_BLANK])
        band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(2.3), SLIDE_WIDTH, Inches(2.9))
        band.fill.solid()
        band.fill.fore_color.rgb = self.primary
        band.line.fill.background()
        white = RGBColor(0xFF, 0xFF, 0xFF)
        self._text_box(slide, MARGIN, Inches(2.6), SLIDE_WIDTH - 2 * MARGIN, Inches(1.4), data["title"], size=44, bold=True, color=white)
        if data.get("subtitle"):
            self._text_box(slide, MARGIN, Inches(4.0), SLIDE_WIDTH - 2 * MARGIN, Inches(0.9), data["subtitle"], size=22, color=white)
        self._notes(slide, data.get("notes"))

    def section(self, data: dict) -> None:
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[LAYOUT_BLANK])
        background = slide.background.fill
        background.solid()
        background.fore_color.rgb = self.primary
        white = RGBColor(0xFF, 0xFF, 0xFF)
        self._text_box(slide, MARGIN, Inches(2.8), SLIDE_WIDTH - 2 * MARGIN, Inches(1.4), data["title"], size=40, bold=True, color=white, align=PP_ALIGN.CENTER)
        if data.get("subtitle"):
            self._text_box(slide, MARGIN, Inches(4.2), SLIDE_WIDTH - 2 * MARGIN, Inches(0.8), data["subtitle"], size=20, color=white, align=PP_ALIGN.CENTER)
        self._notes(slide, data.get("notes"))

    def bullets(self, data: dict) -> None:
        pages = _chunks(list(data.get("bullets") or []), MAX_BULLETS_PER_SLIDE)
        for page_index, page in enumerate(pages):
            title = data["title"] if page_index == 0 else f"{data['title']} (cont.)"
            slide = self._content_slide(title)
            box = slide.shapes.add_textbox(MARGIN, BODY_TOP, SLIDE_WIDTH - 2 * MARGIN, SLIDE_HEIGHT - BODY_TOP - MARGIN)
            self._fill_bullets(box.text_frame, page)
            self._notes(slide, data.get("notes") if page_index == 0 else None)

    def two_column(self, data: dict) -> None:
        slide = self._content_slide(data["title"])
        gap = Inches(0.5)
        width = (SLIDE_WIDTH - 2 * MARGIN - gap) // 2
        for index, side in enumerate(("left", "right")):
            column = data.get(side) or {}
            left = MARGIN + index * (width + gap)
            top = BODY_TOP
            if column.get("heading"):
                self._text_box(slide, left, top, width, Inches(0.6), column["heading"], size=24, bold=True, color=self.primary)
                top += Inches(0.7)
            box = slide.shapes.add_textbox(left, top, width, SLIDE_HEIGHT - top - MARGIN)
            self._fill_bullets(box.text_frame, list(column.get("bullets") or [])[: MAX_BULLETS_PER_SLIDE + 2], size=20)
        self._notes(slide, data.get("notes"))

    def table(self, data: dict) -> None:
        table_spec = data.get("table") or {}
        columns = [str(c) for c in table_spec.get("columns") or []]
        rows = table_spec.get("rows") or []
        if not columns:
            raise SpecError(f"Slide '{data['title']}' uses layout 'table' without table.columns")
        slide = self._content_slide(data["title"])
        height = min(Inches(0.5) * (len(rows) + 1), SLIDE_HEIGHT - BODY_TOP - MARGIN)
        shape = slide.shapes.add_table(len(rows) + 1, len(columns), MARGIN, BODY_TOP, SLIDE_WIDTH - 2 * MARGIN, height)
        grid = shape.table
        font_size = Pt(16 if len(rows) <= 8 else 12)
        for col, name in enumerate(columns):
            cell = grid.cell(0, col)
            cell.text = name
            cell.fill.solid()
            cell.fill.fore_color.rgb = self.primary
            for run in cell.text_frame.paragraphs[0].runs:
                run.font.bold = True
                run.font.size = font_size
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        for r, row in enumerate(rows, start=1):
            for col in range(len(columns)):
                value = row[col] if col < len(row) else ""
                cell = grid.cell(r, col)
                cell.text = "" if value is None else str(value)
                # Neutral banding so any theme color works with the header row.
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor(0xF2, 0xF2, 0xF2) if r % 2 else RGBColor(0xFF, 0xFF, 0xFF)
                for run in cell.text_frame.paragraphs[0].runs:
                    run.font.size = font_size
                    run.font.color.rgb = DARK_TEXT
        self._notes(slide, data.get("notes"))

    def image(self, data: dict) -> None:
        slide = self._content_slide(data["title"])
        image_path = Path(str(data.get("image_path") or "")).expanduser()
        area_top = BODY_TOP
        area_height = SLIDE_HEIGHT - area_top - MARGIN - (Inches(0.6) if data.get("caption") else 0)
        if image_path.is_file():
            picture = slide.shapes.add_picture(str(image_path), MARGIN, area_top)
            scale = min((SLIDE_WIDTH - 2 * MARGIN) / picture.width, area_height / picture.height, 1.0)
            picture.width = Emu(int(picture.width * scale))
            picture.height = Emu(int(picture.height * scale))
            picture.left = Emu(int((SLIDE_WIDTH - picture.width) / 2))
        else:
            self._text_box(slide, MARGIN, area_top, SLIDE_WIDTH - 2 * MARGIN, Inches(1), f"(Image not found: {image_path})", size=18, color=MUTED_TEXT)
        if data.get("caption"):
            self._text_box(
                slide, MARGIN, SLIDE_HEIGHT - MARGIN - Inches(0.5), SLIDE_WIDTH - 2 * MARGIN, Inches(0.5),
                data["caption"], size=16, color=MUTED_TEXT, align=PP_ALIGN.CENTER,
            )
        self._notes(slide, data.get("notes"))

    def build(self, spec: dict, output: Path) -> int:
        for slide in spec["slides"]:
            layout = slide.get("layout")
            handler = getattr(self, layout, None) if layout in {"title", "bullets", "two_column", "table", "image", "section"} else None
            if handler is None:
                raise SpecError(f"Unknown slide layout: {layout!r}")
            handler(slide)
        output.parent.mkdir(parents=True, exist_ok=True)
        self.prs.save(str(output))
        return len(self.prs.slides)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    output = Path(args.output)
    try:
        count = DeckBuilder(spec).build(spec, output)
    except (SpecError, KeyError, TypeError) as exc:
        print(f"Invalid spec: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"path": str(output.resolve()), "slides": count}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
