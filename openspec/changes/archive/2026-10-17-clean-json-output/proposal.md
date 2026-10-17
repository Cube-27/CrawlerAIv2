# Clean JSON output

## Why
Owner request (2026-10-17): the playground's JSON repeats things the reader does not need. Every identifier is
`{"value": …, "scheme": …}` although the field already declares its scheme; a price is `{amount, currency}`; unpublished
fields show as `null`; and each page sits in a `{url, outcome, records: […]}` wrapper. The owner also asked for the JSON
view to read like a code editor, no "Pages"/"Sites" captions over the mode switch, and a Batch URL box that shows ten
URLs and scrolls inside.

## What changes
- `normalize/identifier.py`: an identifier's value is its string alone (D-1209).
- `json_values` clean records: published fields only, in name order; a money value is written flat, its amount under the
  field's name and its currency under `currency` (beside `price`) or `<field>_currency` (D-1210).
- Playground JSON: the page's record as an object, or its records as an array, with no wrapper (D-1211).
- `JsonView`: line numbers, indent guides and VS Code Light+/Dark+ colors, lines kept and scrolled sideways (D-1212).
- Mode switch without visible captions; Batch's URL box ten lines high, scrolling inside (D-1213).
