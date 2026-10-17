# Design

## Decisions

### D-1209 — An identifier's value is its string
- Date: 2026-10-17 · Change/PR: clean-json-output · Status: decided
- Decision: `normalize/identifier.py` publishes the normalized string; the GTIN-14 equality key reads the scheme from the field spec.
- Alternatives: keep `{scheme, value}` and strip it only in output (two shapes of one value).
- Why: owner request (#51); the scheme is the field's declared one, so the object only repeated it.
- Reversible: yes — the normalizer and fixtures.

### D-1210 — Clean records: published fields only, money flat
- Date: 2026-10-17 · Change/PR: clean-json-output · Status: decided
- Decision: a clean record leaves out unpublished fields; a money field `x` writes its amount as `x` and its ISO 4217 code as `currency` when `x` is `price` and the schema has no `currency` field, else `x_currency`. Nested rows are written the same way. Records, CSV and Markdown exports are unchanged.
- Alternatives: separate `price` and `currency` schema fields (replaces the money type end to end); `price_currency` always. The owner chose the bare `currency` key.
- Why: owner request (#51). Amount and code are written verbatim, so no value changes (INV-27); only the clean layout does.
- Reversible: yes — `clean_record` and `cleanJson.ts`.

### D-1211 — Playground JSON without the item wrapper
- Date: 2026-10-17 · Change/PR: clean-json-output · Status: decided
- Decision: the JSON tab and the run drawer show a page's one record as an object, or its records as an array (none, or a listing's); with Metadata in JSON they sit under `data` beside `metadata`. The `json_values` API item keeps `{url, outcome, records}`: the results table reads it.
- Alternatives: URL plus the fields in one object.
- Why: owner choice (#51).
- Reversible: yes — `cleanJson.ts`.

### D-1212 — JSON view as a code editor
- Date: 2026-10-17 · Change/PR: clean-json-output · Status: decided
- Decision: `JsonView` numbers its lines and draws a guide per indent level in CSS (copied text has neither), uses VS Code's Light+/Dark+ token and editor colors, and keeps lines whole, scrolling sideways in its fixed box.
- Alternatives: folding (more state for little gain); wrapping long lines (breaks the line-number gutter).
- Why: owner request (#51) for a "VS Code view".
- Reversible: yes — `JsonView`, `jsonTokens.ts`, theme.css.

### D-1213 — Mode switch without captions; ten-line Batch box
- Date: 2026-10-17 · Change/PR: clean-json-output · Status: decided
- Decision: the mode groups keep their captions as tab-list names for assistive technology but do not show them. Batch's URL box is ten lines high and scrolls inside, so its command bar is taller than the single-URL modes' and switching to Batch moves the toolbar down.
- Alternatives: give every mode a ten-line box (empty space under a single URL).
- Why: owner request (#51).
- Reversible: yes — `ModeSwitch`, `UrlList`.
