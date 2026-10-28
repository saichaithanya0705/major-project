---
name: pptx
description: Create a PowerPoint presentation (.pptx) from a topic, notes, or an outline. Use when the user asks for slides, a deck, a presentation, or a .pptx file.
metadata:
  jarvis:
    kind: structured
    entrypoint: scripts/build.py
    schema: schema.json
    output_extension: .pptx
    triggers:
      - '\bpptx\b'
      - '\bpower ?points?\b'
      - '\bslide ?decks?\b'
      - '\bdecks?\b'
      - '\bslides?\b'
      - '\bpresentations?\b'
---

# PowerPoint presentation

You write a JSON spec; `scripts/build.py` turns it into a 16:9 `.pptx`.

Run it yourself with:

```
python scripts/build.py --spec spec.json --output deck.pptx
```

## Writing the spec

- Start with one `title` slide, end with a short `bullets` summary or a closing `section` slide.
- 6 to 12 slides is right for most requests unless the user asks for a number.
- Keep each bullet under 15 words. Use `level: 1` for sub-points. At most 6 bullets per slide; the builder splits longer lists onto continuation slides.
- Put detail the presenter should say, not show, in `notes`.
- Use `two_column` to compare two things, `table` for numbers or feature grids, `section` to separate parts of a long deck.
- Only use `image` with a file path the user gave you. Never invent paths or URLs.
- Facts, figures, and dates must come from the user's request or well-known knowledge. Do not fabricate statistics.
- `theme.primary_color` is a hex color like `#1F4E79`. Pick one that suits the topic, or omit it.

## Example

```json
{
  "title": "Solar Energy Basics",
  "theme": {"primary_color": "#C55A11"},
  "slides": [
    {"layout": "title", "title": "Solar Energy Basics", "subtitle": "How sunlight becomes electricity"},
    {"layout": "bullets", "title": "How a panel works", "bullets": [
      "Photons knock electrons loose in silicon cells",
      {"text": "Cells are wired in series for higher voltage", "level": 1},
      "An inverter converts DC to household AC"
    ], "notes": "Mention that panels still work on cloudy days, just less."},
    {"layout": "table", "title": "Panel types", "table": {
      "columns": ["Type", "Efficiency", "Cost"],
      "rows": [["Monocrystalline", "20-23%", "High"], ["Polycrystalline", "15-18%", "Medium"]]
    }},
    {"layout": "two_column", "title": "Pros and cons",
      "left": {"heading": "Pros", "bullets": ["No fuel cost", "Low maintenance"]},
      "right": {"heading": "Cons", "bullets": ["Intermittent", "Upfront cost"]}},
    {"layout": "section", "title": "Questions?"}
  ]
}
```
