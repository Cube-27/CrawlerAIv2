## Decisions

### D-1270 — A minus negates money and count only when it touches the number
- Date: 2026-10-17 · Change/PR: normalize-collect-content · Status: decided (owner-delegated 2026-10-17)
- Decision: `numbers.negated`: a minus (`-`, U+2212) negates when no white space lies between it and the number (CLDR writes the sign against the digits, `-$5` included). `number` keeps its own rule (`numbers.negative`).
- Why: "In stock - 5 left" is punctuation. Scope follows the backlog line (money and count).
- Reversible: yes

### D-1271 — `unitText` beside C62 declines when it names a CLDR measurement unit
- Date: 2026-10-17 · Change/PR: normalize-collect-content · Status: decided (owner-delegated 2026-10-17)
- Decision: the label (NFKC, case folded) is compared with every CLDR unit pattern text (names and symbols, all widths) of the page's languages, or of every language when it states none; `concentr-item` is excluded. A match declines (`unit`); other text ("items") passes.
- Alternatives: decline any `unitText` (loses "items", "pieces"); a hand-written unit list (C4).
- Reversible: yes

### D-1272 — A location's remote phrase counts only as a whole clause
- Date: 2026-10-17 · Change/PR: normalize-collect-content · Status: decided (owner-delegated 2026-10-17)
- Decision: `vocab.clause_codes` matches a phrase against each whole clause of the text (clauses as `first_clause` ends them), not only the first: a location lists places, so "Lakeside, Remote" is remote, "Not remote" and "Remote-friendly" are not. `Remote - US` (a dash joins words) is not remote either; the text keeps it.
- Why: INV-37's first-clause rule alone would drop "City, Remote". No negation word list (C4).
- Reversible: yes

### D-1273 — A field mapped to `identifier` reads its own scheme's sub-properties
- Date: 2026-10-17 · Change/PR: normalize-collect-content · Status: decided (owner-delegated 2026-10-17)
- Decision: a path ending in `identifier` widens to the schema.org property named as the field's `scheme` and its sub-properties, when the vocabulary declares it a sub-property of `identifier`; `custom`, `mpn` and `isbn` (not declared) read `identifier` alone.
- Reversible: yes

### D-1274 — `site_names` combines the first 8 separator parts
- Date: 2026-10-17 · Change/PR: normalize-collect-content · Status: decided (owner-delegated 2026-10-17)
- Decision: runs of consecutive parts are taken over the first 8 parts (36 runs); the whole name is always a run.
- Reversible: yes

### D-1275 — Inline runs in div/td/li are wrapped in a `p` before trafilatura
- Date: 2026-10-17 · Change/PR: normalize-collect-content · Status: decided (owner-delegated 2026-10-17)
- Decision: on the markdown copy of the tree, each run of phrasing content (HTML Standard §3.2.5.2.5) with an element and text of its own, in a `div`, `td` or `li`, is wrapped in a `p`; trafilatura keeps the spaces of a `p`'s inline content (verified; `li` and `td` already kept them).
- Reversible: yes

### D-1276 — A listing without repeated items is extracted in recall mode
- Date: 2026-10-17 · Change/PR: normalize-collect-content · Status: decided (owner-delegated 2026-10-17)
- Decision: `page_kind == "listing"` with no item group uses `favor_recall`; other pages stay on `favor_precision`. The "tiny output" trigger is not built: a size ratio needs a threshold with no standard behind it.
- Reversible: yes

### D-1277 — Item groups rank by structural evidence, then size
- Date: 2026-10-17 · Change/PR: normalize-collect-content · Status: decided (owner-delegated 2026-10-17)
- Decision: a group scores one per item holding an image and one per item with two or more text runs; the highest score wins, ties go to the larger group. A bare tag cloud or pager scores 0 and still wins when alone.
- Reversible: yes
