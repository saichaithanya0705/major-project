---
name: browser-form-fill
description: Inspect web forms, fill user-authorized text and options, verify entered values, and obtain chat confirmation before final submission.
metadata:
  version: "1.0"
---
# Fill and verify forms

Inspect fields, required indicators, labels, available choices, and validation
messages. Use supplied details faithfully; ask for missing information instead
of inventing it. Field entry itself needs no confirmation. Prefer a single
`browser_fill_form` action for a related batch, with the actual field types.

Verify entries and selected options through runtime read-back. Values may be
hidden in the model snapshot for privacy; verified field progress is evidence
of successful entry. Do not echo secrets in the final answer.

If the request is to fill a draft, stop after verification. If the user requests
submission, choose the real final submit control; the runtime asks in chat and
binds that review to the current form. Enter and JavaScript-app submission use
the same review. Refusal leaves the draft intact and ends submission attempts.
After approval, inspect the confirmation or validation error. Report submission
as complete only when the resulting page provides evidence; never resubmit an
operation merely because its response timed out.
