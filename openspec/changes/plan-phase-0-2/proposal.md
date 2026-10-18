# Change: plan phase 0, part 2 — row keys without session parameters, a golden-set report that means something

## Why

The master improvement plan (owner, 2026-10-18) found that a quarter of the golden set's listing misses and extras are
scoring artifacts: row URLs that differ from their label only by a visit's query (`searchId`, `sid`), label rows of a
dynamic list that the capture no longer shows, `locations` labels the importer declined (302 values), and a report
that cannot tell a value the capture lacks from one the engine did not read. Phase 0 makes the headline number mean
something before any engine coverage work.

## What Changes

- **Row keys:** `normalize.url_key.session_parameters` finds a listing page's session parameters (one same value on
  every row link, absent from the page's own URLs); the engine drops them from published row item URLs
  (`resolve/row_keys.py`) and eval row matching drops them from label URLs: one function for both. Eval matches the
  rows left by (URL path, text fields), and by the text fields alone when a label row has no URL.
- **`crawlerai eval re-key <file> --split dev`:** recomputes a golden page's draft labels from the label file against
  its stored capture and marks label rows the capture does not show (`stale`); a stale row that no engine row
  matches is reported separately, never as FN.
- **List labels:** a label file may give a location in its normalized form; its `text` is read as the page writes it,
  so `locations` lists import.
- **Report:** per field type the labeled values present in the capture (the coverage ceiling); FN split into
  `declined:<reason>`, `absent`, `unread`; FP split into `wrong_value`, `on_absent`, `extra_row:on_page`,
  `extra_row:not_on_page`; LLM tokens and USD per correct field.

## Impact

- Capabilities: [evaluation](../../specs/evaluation/spec.md), [extraction](../../specs/extraction/spec.md).
- Files: `backend/src/crawlerai/normalize/url_key.py`, `resolve/row_keys.py` (new), `resolve/pipeline.py`,
  `resolve/types.py`, `eval/` (`metrics.py`, `presence.py` and `rekey.py` new, `labels.py`, `label_file.py`,
  `replay.py`), `cli.py`, `llm/pricing.py`.
