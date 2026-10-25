---
name: xlsx
description: Create an Excel workbook (.xlsx) such as a budget, tracker, timetable, or data table, optionally with formulas and a chart. Use when the user asks for a spreadsheet, Excel file, or .xlsx.
metadata:
  jarvis:
    kind: structured
    entrypoint: scripts/build.py
    schema: schema.json
    output_extension: .xlsx
    triggers:
      - '\bxlsx\b'
      - '\bexcel\b'
      - '\bspreadsheets?\b'
      - '\bworkbooks?\b'
---

# Excel workbook

You write a JSON spec; `scripts/build.py` turns it into an `.xlsx` with a styled header row, frozen panes, filters, and fitted column widths.

```
python scripts/build.py --spec spec.json --output budget.xlsx
```

## Writing the spec

- Each sheet has `columns` (header names) and `rows` (lists of cell values in column order).
- Use JSON numbers for numeric cells (`1200`, not `"1,200"`) so Excel can calculate with them.
- A string starting with `=` is a formula, written for the row it is in, e.g. `"=B2*C2"` in row 2. Row 1 is the header, so data starts at row 2.
- `number_formats` maps a column name to an Excel format: `"#,##0"`, `"#,##0.00"`, `"0%"`, `"yyyy-mm-dd"`, `"₹#,##0"`.
- Add a `totals_row` to sum numeric columns automatically.
- `chart` draws a `bar`, `line`, or `pie` chart from one category column and one or more value columns.
- Do not invent data the user did not give you; leave cells empty (`null`) for the user to fill.

## Example

```json
{
  "sheets": [
    {
      "name": "October Budget",
      "columns": ["Category", "Planned", "Spent", "Remaining"],
      "rows": [
        ["Rent", 12000, 12000, "=B2-C2"],
        ["Food", 6000, 4800, "=B3-C3"],
        ["Travel", 2000, 2600, "=B4-C4"]
      ],
      "number_formats": {"Planned": "₹#,##0", "Spent": "₹#,##0", "Remaining": "₹#,##0"},
      "totals_row": true,
      "chart": {"type": "bar", "title": "Planned vs spent", "category_column": "Category", "value_columns": ["Planned", "Spent"]}
    }
  ]
}
```
