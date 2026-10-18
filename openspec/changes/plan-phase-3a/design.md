# Design: plan phase 3a, role C on detail pages

- Shape: `content.text.Mark(kind, start, end, path, target, name)`, recorded in the cleaned-text walk
  (`CleanedText.marks`); `llm.marked.MarkedText(text, cleaned, elements, inserted, lengths)`, the text the model reads
  with its ids, the cut cleaned text it maps back to, and the marks by id; the detail claim
  `{shown, ref, value, start, end}`; `llm.grounding.GroundedElement(value, path)` with a `dom:<path>` locator.
- A claim with a `ref` is grounded in the element; one without is a span, its offsets mapped from the marked text to
  the cleaned text before alignment, so every `text:` locator still points into the cleaned text.
