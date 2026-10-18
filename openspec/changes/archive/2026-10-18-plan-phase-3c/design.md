# Design: plan phase 3c, fragments of a text value and image size keys

- Shape: `resolve.supersede.superseded(type, kept) -> list[Candidate]`; `Resolver._by_precedence` ranks kinds over the
  other kept candidates. A superseded candidate stays kept: it can agree with the winner, else it is rejected with
  reason `precedence`.

## Decisions

### D-1660 — A fragment of another candidate's text ranks nowhere
- Date: 2026-10-18 · Change/PR: plan-phase-3c (#284) · Status: decided (owner-delegated 2026-10-17)
- Decision: For `long_text`, a candidate whose whitespace-collapsed text is a prefix, or an ellipsis-cut prefix, of a
  longer candidate's (any kind) is superseded by it. For `text`, a candidate equal to another kind's value plus
  ` <separator> ` and more text, at either end, is superseded by that value; the separator is one dash (Unicode `Pd`)
  or `|`, between spaces. Nothing is dropped for being short: an unrelated shorter text still competes by kind.
- Why: a truncation or a decorated title is the same statement cut or extended, so the kind order has nothing to decide.
- Reversible: yes (`resolve/supersede.py`, one call in `_by_precedence`)

### D-1661 — An Open Graph description yields to a longer description of another kind
- Date: 2026-10-18 · Change/PR: plan-phase-3c (#284) · Status: decided (owner-delegated 2026-10-17)
- Decision: For `long_text` only, an `og` candidate is superseded when a candidate of another kind is longer. An `og`
  text longer than all others, or equal, is not affected. `text` fields keep Open Graph in the order.
- Why: the Open Graph protocol defines `og:description` as a one-to-two sentence summary; a longer description elsewhere on the page
  is the fuller statement. Titles are covered by D-1660.
- Reversible: yes

### D-1662 — No rule for company legal suffixes or sku variants
- Date: 2026-10-18 · Change/PR: plan-phase-3c (#284) · Status: decided (owner-delegated 2026-10-17)
- Decision: "X Inc" against "X" and a variant's sku against the page's are not decided by a structural property (a
  legal form is a vocabulary, C4; a variant's identity is the variants layer's), so no rule is added for them.
  A `+`, a bracket or an unspaced hyphen is not decoration (it joins or qualifies a product name).
- Reversible: n/a

### D-1663 — The image resource key ignores renditions the path states
- Date: 2026-10-18 · Change/PR: plan-phase-3c (#284) · Status: decided (owner-delegated 2026-10-17)
- Decision: `normalize.url.resource_key` (scheme- and query-insensitive already) also drops a path segment
  `<digits>x<digits>` or a list of `<letters>_<digits>` pairs, a size before the extension (`-300x200`, `_1024x`,
  `@2x`), a format conversion appended as a second extension (`.jpg.webp`) and a trailing `=<options>`. The
  extension itself stays: another format is another file. Published values keep a real URL, `https` first
  (unchanged). Scoring's `_same_file` reads the same function (`eval.scoring`), so no scoring rule text changed; it
  matches the renditions the resolver treats as one.
- Reversible: yes

### D-1664 — Measured on the full dev copy, no LLM (`--llm unanswered`)
- Date: 2026-10-18 · Change/PR: plan-phase-3c (#284) · Status: decided (owner-delegated 2026-10-17)
- Decision: image_url P 0.625 → 0.875, C 0.769 → 0.824; list P 0.364 → 0.455, C 0.800 → 0.833; every other type
  unchanged. Descriptions do not move: the false publishes there state one collected candidate (an Open Graph
  summary) or no fuller candidate exists, because the full text is a DOM block no collector reads, so there is
  nothing to prefer.
- Reversible: n/a
