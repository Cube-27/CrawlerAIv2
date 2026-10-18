# Design: learning-live

## Decisions

### D-1500 — A listing's engine rows align with the config's as a subsequence
- Date: 2026-10-18 · Change/PR: learning-live (#269) · Status: decided (owner-delegated 2026-10-17)
- Decision: held-out validation and the release check align the engine's rows of a page with the config's (or the
  release executor's) rows in document order, as the order-preserving subsequence with the most agreeing values
  (`config_ir/row_alignment.py`). An engine row aligned with no config row is not reproduced; a config row no engine row
  aligns with is checked for validity like any match; the executors must select as many rows as each other and at least
  as many as the engine published. Synthesis keeps its exact row count on the sample pages. Supersedes D-0566.
- Alternatives: equal counts only (D-0566: every listing whose rows come from role C failed: role C left 2 of 16 and
  11 of 12 items out on held-out pages of two live hosts); match rows by URL (role C rows often carry none).
- Why: the engine's rows are a subset of the page's items whenever role C reads them; the rows it did publish still
  check every value the config gives them, so precision is checked where the engine has a value.
- Reversible: yes.

### D-1501 — The IR's JSONPath is the subset the engine reads
- Date: 2026-10-18 · Change/PR: learning-live (#269) · Status: decided (owner-delegated 2026-10-17)
- Decision: `jsonld` and `jsonpath` steps validate with the API recipe's `EngineJsonPath` (RFC 9535 name, wildcard and
  index segments), so role A's `$.name` is an `invalid_step` diagnostic in its repair round, and role A's prompt states
  the form (as the key paths it is shown are written).
- Alternatives: teach the engine's reader dot notation (a second form of one query, and the release executor's reader
  already differs); prompt only (the IR would still store steps no executor runs).
- Why: §4.2, a document that validates is one both executors run; live, role A's description steps for one host
  failed all repair rounds on `unsupported_jsonpath`.
- Reversible: yes.

### D-1502 — Structured values are read as the structured collectors read them, in both executors
- Date: 2026-10-18 · Change/PR: learning-live (#269) · Status: decided (owner-delegated 2026-10-17)
- Decision: a value a `jsonld` or `jsonpath` step selects goes through `schema_org_map.fragment_read` (a text field
  reads markup as its rendered text) before its post ops, in the engine executor and, through
  `FieldRule.structured` from `release_rules`, in the release executor (which still imports nothing of the engine).
  XPath element values keep their string-value.
- Alternatives: render XPath element values for text fields too (a second parse of page content, INV-26; left as a
  follow-up); leave the read to the normalizer (it does not parse HTML, by design).
- Why: a JobPosting description written as HTML (the common form) was published as rendered text, so no induced or
  synthesized step could reproduce it: two of two live job hosts lost `description`.
- Reversible: yes.

### D-1503 — How config mode was measured against cold mode
- Date: 2026-10-18 · Change/PR: learning-live (#269) · Status: decided (owner-delegated 2026-10-17)
- Decision: each learned config was copied as the `config_snapshot` of its host's dev page in a copy of the dev eval
  database (labels and captures untouched), and the 8 pages were replayed with and without snapshots
  (`crawlerai eval run --split dev --labels all --llm live --llm-max-calls 30`). The copy's `job_listing` schema predates
  `locations`, so its snapshot names that field `location`; listing rows were re-matched locally by URL without a
  trailing slash, else by title, since the harness matches exact URLs. No configs were learned from a dev page.
- Alternatives: compare live config-mode scrapes with the labels (pages change since capture).
- Why: C10; the dev labels hold one page per host and kind, so only the harness can replay them in both modes.
- Reversible: yes.
