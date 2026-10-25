---
name: docx
description: Create a Word document (.docx) such as a report, letter, essay, notes, or assignment. Use when the user asks for a Word file, a .docx, or a document to edit in Word.
metadata:
  jarvis:
    kind: structured
    entrypoint: scripts/build.py
    schema: schema.json
    output_extension: .docx
    triggers:
      - '\bdocx\b'
      - '\bms ?word\b'
      - '\bword (?:document|doc|file)s?\b'
      - '\b(?:report|letter|essay|assignment|cover letter|resume|cv)\b.*\bword\b'
---

# Word document

You write a JSON spec; `scripts/build.py` turns it into a `.docx`.

```
python scripts/build.py --spec spec.json --output report.docx
```

## Writing the spec

- `sections` are in reading order. Each can have a `heading` (with `level` 1-3), `paragraphs`, `bullets`, `numbered` steps, a `table`, and an `image_path`, rendered in that order.
- Write complete paragraphs, not notes. Use `**bold**` and `*italic*` inside text for emphasis; no other Markdown.
- A letter has no headings: put the greeting, body paragraphs, and sign-off in `paragraphs`.
- Use `page_break_before: true` to start a major part (for example an appendix) on a new page.
- Only use `image_path` with a file path the user gave you. Never invent paths.
- Do not fabricate facts, citations, quotes, or statistics.

## Example

```json
{
  "title": "Weekly Lab Report",
  "subtitle": "Physics 101, Experiment 4",
  "author": "Student Name",
  "sections": [
    {"heading": "Objective", "level": 1, "paragraphs": ["Measure the acceleration due to gravity using a **simple pendulum**."]},
    {"heading": "Procedure", "level": 1, "numbered": ["Set the string length to 1 m.", "Time 20 oscillations.", "Repeat for 0.8 m and 0.6 m."]},
    {"heading": "Results", "level": 1, "table": {"columns": ["Length (m)", "Period (s)"], "rows": [[1.0, 2.01], [0.8, 1.80], [0.6, 1.55]]}},
    {"heading": "Conclusion", "level": 1, "paragraphs": ["The measured value was close to 9.8 m/s²."]}
  ]
}
```
