# Design: plan phase 0, part 2

## Decisions

### D-1527 — Session parameters: two rows, one occurrence, item URL fields only
- Date: 2026-10-18 · Change/PR: plan-phase-0-2 (#272) · Status: decided (owner-delegated 2026-10-17)
- Decision: A parameter is a session parameter when at least two published row item URLs (`item_url_fields`) all carry
  it exactly once with one same value and none of the page's request, final or canonical URLs carries it. It is
  dropped from the published row URLs after resolution (`resolve/row_keys.py`); the extraction result lists the names,
  and eval drops the same names from label URLs, both for matching and for judging the URL value.
- Alternatives: a list of tracking parameter names (C4); dropping from every URL field (a page field shows no rows to
  compare); one row as evidence (nothing to compare against).
- Why: owner #67 decision 6; the rule only drops, never invents (C7).
- Reversible: yes

### D-1528 — Row matching falls back to path and text, then text alone
- Date: 2026-10-18 · Change/PR: plan-phase-0-2 (#272) · Status: decided (owner-delegated 2026-10-17)
- Decision: After URL matching, a label row left unmatched matches the first engine row left with the same host and
  path whose text-type fields equal the label's; a label row with no URL matches by its text fields alone. One to one,
  in page order.
- Why: plan §8.3 ("fallback (path, title)"); the text fields are the schema's `text` type, so no field name is assumed.
- Reversible: yes

### D-1529 — Re-keying is a command over draft labels, stored on the label row
- Date: 2026-10-18 · Change/PR: plan-phase-0-2 (#272) · Status: decided (owner-delegated 2026-10-17)
- Decision: `crawlerai eval re-key <file> --split dev` recomputes each draft page's labels from the label file against
  its stored capture and stores `stale` on the rows the capture does not show (`LabelRow.stale`); labeled and checked
  pages are skipped. A stale row is counted in `label_stale` only when no engine row matched it; a matched stale row is
  judged as any row.
- Alternatives: a scoring option (staleness is a fact about labels and capture, not about one run).
- Reversible: yes

### D-1530 — Presence is a search for the written value
- Date: 2026-10-18 · Change/PR: plan-phase-0-2 (#272) · Status: decided (owner-delegated 2026-10-17)
- Decision: `eval.presence.Capture` searches the capture's document (markup, attributes, inline JSON and tag-free text;
  character references decoded, escaped solidus read, case folded, white space collapsed) for strings, URL paths,
  location texts and list items; values under 3 characters, root paths, amounts, numbers, dates and enums are unknown.
- Why: a ceiling must not guess; an amount has too many written forms to search reliably.
- Reversible: yes

### D-1531 — Disagreement kinds
- Date: 2026-10-18 · Change/PR: plan-phase-0-2 (#272) · Status: decided (owner-delegated 2026-10-17)
- Decision: FN is `declined:<reason>` when the engine output the field with a reason, else `absent`, `unread` or
  `not_output` (presence unknown); FP is `wrong_value`, `on_absent`, or `extra_row` with `:on_page`/`:not_on_page`.
  The former `FN|<reason>` keys become `FN|declined:<reason>`.
- Reversible: yes

### D-1532 — Cost per correct field is priced on the capture's day
- Date: 2026-10-18 · Change/PR: plan-phase-0-2 (#272) · Status: decided (owner-delegated 2026-10-17)
- Decision: `Pricing.call_usd` applies the rule `services.llm_costs` applies in SQL, for replayed calls that are not
  stored; a page's calls are priced on its capture's UTC fetch day, so two replays give the same report (INV-10). An
  unpriced call makes the cost unknown, never zero.
- Reversible: yes

### D-1533 — A normalized location label is read by its text
- Date: 2026-10-18 · Change/PR: plan-phase-0-2 (#272) · Status: decided (owner-delegated 2026-10-17)
- Decision: In a label file, a location given as `{text, locality?, region?, country?, remote_flag?}` is read by its
  `text`, as the pipeline reads a page's place text; the normalizer itself is unchanged.
- Why: the golden labels give places in that form, and 302 values were declined `no_item`.
- Reversible: yes
