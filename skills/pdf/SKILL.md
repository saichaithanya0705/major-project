---
name: pdf
description: Create a PDF document such as a report, handout, summary, or notes. Use when the user asks for a PDF file to read or share (not to edit in Word).
metadata:
  jarvis:
    kind: structured
    entrypoint: scripts/build.py
    schema: schema.json
    output_extension: .pdf
    triggers:
      - '\bpdfs?\b'
---

# PDF document

You write a JSON spec; `scripts/build.py` lays it out as an A4 PDF with page numbers.

```
python scripts/build.py --spec spec.json --output summary.pdf
```

## Writing the spec

- `sections` are in reading order. Each can have a `heading` (with `level` 1-3), `paragraphs`, `bullets`, `numbered` steps, a `table`, and an `image_path`, rendered in that order.
- Write complete paragraphs, not notes. Use `**bold**` and `*italic*` inside text for emphasis; no other Markdown.
- Use `page_break_before: true` to start a major part on a new page.
- Only use `image_path` with a file path the user gave you. Never invent paths.
- Do not fabricate facts, citations, quotes, or statistics.

## Example

```json
{
  "title": "Trip Checklist",
  "subtitle": "Goa, 3 days",
  "sections": [
    {"heading": "Documents", "level": 1, "bullets": ["ID card", "Train tickets (**printed**)", "Hotel booking"]},
    {"heading": "Day plan", "level": 1, "table": {"columns": ["Day", "Plan"], "rows": [["1", "Beaches"], ["2", "Old Goa churches"], ["3", "Markets"]]}}
  ]
}
```
