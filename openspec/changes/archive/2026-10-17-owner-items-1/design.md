# Design: owner-items-1

The owner delegated these decisions on 2026-10-17 ("take decisions yourself"); each is logged here and the ones that
change the design are owner decision #60.

## Decisions

### D-1340 — Unchanged is an equal digest of the visible words; SimHash only reports
- Date: 2026-10-17 · Change/PR: owner-items-1 (#252) · Status: decided (owner-delegated 2026-10-17)
- Decision: D-0915 option (c). A page is `unchanged` only when the BLAKE2b-128 digest of its visible words (the words
  SimHash reads: whitespace-split, nonce-like tokens left out) equals `url_state.content_digest`. The SimHash is still
  stored (`content_fingerprint`) and a change logs how many of its 64 bits moved, the near-duplicate report. Owner #40
  ("only an equal fingerprint is unchanged") holds, now with no misses: every one-word edit of the 100 fixed 500-word
  texts changes the digest, where SimHash stayed equal on some.
- Alternatives: (a) keep SimHash and amend §14; (b) the digest alone, SimHash dropped.
- Reversible: yes — one column and `record_content`.

### D-1341 — An `absent` field status, learned from pages that never state a required field
- Date: 2026-10-17 · Change/PR: owner-items-1 (#252) · Status: decided (owner-delegated 2026-10-17)
- Decision: answers D-0784. A learning run lists in the IR's `absent` (field status `absent`) each required field or
  required-group member of a detail schema that, on every one of the `LEARN_AFTER_PAGES` pages it reads (fewer: none),
  nothing published, no source gave a valid candidate for, and whose extraction called the LLM (role C asks every
  missing required field at once, so it was asked). Synthesis does not try it; its report reason is `absent`. In config
  mode role C is not asked for it and it stays `missing` with reason `absent`; any collector that states it still
  publishes it, and a config page that publishes it re-tests it: `drift.record_run` removes it from `absent` and
  `field_status`, logs `absent_stated` and starts a forced learning run. Completeness is unchanged: a page missing an
  absent required field is still `partial`.
- Alternatives: optional fields too (they never make role C run, they only ride along); counting only role C's
  `shown: false` claims (not stored per field).
- Reversible: yes — the IR's `absent` defaults to empty.

### D-1342 — Approval of learned configs is an opt-in project setting
- Date: 2026-10-17 · Change/PR: owner-items-1 (#252) · Status: decided (owner-delegated 2026-10-17)
- Decision: answers D-0783 with approval as the mechanism, kept optional. `project.require_config_approval` (off: as
  before). When on, a learning run's validated config is stored `pending_approval`, the run ends as a failed one does
  without the retry bump (an active state keeps its config, a learning one goes cold), and the job completes with the
  config id and reason `pending_approval`. `trigger_learning` starts no run while a config waits; a forced run may, and
  the config it stores replaces the waiting one (`suspended`). `POST /v1/configs/{id}/approve` suspends the active
  version and activates the waiting one in any mode (event `approve`, the operator's edges). Operator corrections are
  not gated: an operator is the person approving. The corroboration ideas of D-0783 (independent references, constant
  values as `suspect`) are not built.
- Alternatives: approval only where sources conflict (needs a conflict measure first); a review queue (§22, frontend
  scope limits).
- Reversible: yes.

### D-1343 — One state candidate per field, normalized value and owner, with the shortest locator
- Date: 2026-10-17 · Change/PR: owner-items-1 (#252) · Status: decided (owner-delegated 2026-10-17)
- Decision: `admit` keeps one candidate per (field, owner entity, independent, normalized value), the one whose locator
  is shortest (nearest the document root, or the first document), at the place of the first repeat. Repeats are the
  same evidence, and agreement counts source kinds, not candidates (§10), so no published value changes; on 3 live
  product pages the `js_state` candidates fell from 91 to 17, 86 to 31 and 6 to 4 with identical records.
- Alternatives: the first in document order (a deep cache copy can come first); the deepest path.
- Reversible: yes.

### D-1344 — `isVariantOf` makes the Product its group's variant
- Date: 2026-10-17 · Change/PR: owner-items-1 (#252) · Status: decided (owner-delegated 2026-10-17)
- Decision: schema.org `isVariantOf` is the inverse of `hasVariant`. A root Product (not a ProductGroup) that holds a
  ProductGroup in `isVariantOf` has the group detached to a root before identity merging, so the Product joins the
  group's member it states (shared identifier or item URL, D-1290) or else becomes the group's `hasVariant` member. A
  root Product naming a standalone group's IRI in `isVariantOf` (a `{"@id": ...}` reference, `Entity.variant_of`) is
  that group's member, as `inProductGroupWithID` makes it. A ProductModel is not inverted (it has no members), nor is a
  nested Product. Supersedes D-1293's "`isVariantOf` stays as it is". Live: a product page listing its group and nine
  colour Products that reference it by `@id` went from an ambiguous target (price `not_owned`, no rows) to the group with
  nine variant rows, each with its price, availability and colour.
- Alternatives: inverting in each collector (two places for one rule, C8).
- Reversible: yes.

### D-1345 — A lone object that names a document of its own is an array row
- Date: 2026-10-17 · Change/PR: owner-items-1 (#252) · Status: decided (owner-delegated 2026-10-17)
- Decision: the only object of a JSON state array is a row when its own scope (its members and nested objects, not its
  arrays) writes a URL that canonicalizes and does not name a media file. A media file is one whose path extension maps
  to an `image`, `audio`, `video` or `font` media type (RFC 6838 top-level types) in Python's built-in `mimetypes` table
  (`MimeTypes()` reads no host file, so the answer is the same everywhere). Ownership then decides as for any row: a row
  naming the page or the target is the target's, a related item naming another page is not. A lone object with no URL,
  or only media URLs, stays its holder's.
- Alternatives: keying on the array's member name (no standard names it, C2); any URL (the page's own item holding its
  image would lose its values).
- Reversible: yes.

### D-1346 — `PATCH /v1/project/settings` takes `require_config_approval` like the other settings
- Date: 2026-10-17 · Change/PR: owner-items-1 (#252) · Status: decided (owner-delegated 2026-10-17)
- Decision: the settings body stays a full replacement: `require_config_approval` is required, as both caps are, so a
  client that omits it gets a 422 rather than a silent reset. The UI sends the loaded value.
- Reversible: yes.

### D-1347 — Absent fields on detail schemas only
- Date: 2026-10-17 · Change/PR: owner-items-1 (#252) · Status: decided (owner-delegated 2026-10-17)
- Decision: a listing asks role C once, only when structured data gives no rows, so a page field a listing never
  states costs no call per page; `absent_fields` returns none for a listing.
- Reversible: yes.
