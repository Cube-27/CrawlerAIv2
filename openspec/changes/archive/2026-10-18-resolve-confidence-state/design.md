# Design: resolve-confidence-state

## Decisions

### D-1770 — Calibrated confidence is reported; only a request's `min_confidence` gates
- Date: 2026-10-18 · Change/PR: resolve-confidence-state (#289) · Status: decided (owner-delegated 2026-10-17)
- Decision: A chosen value always publishes with its bucket's confidence and `calibrated` flag. The fixed thresholds
  (0.97 required, 0.95 optional) are deleted. Supersedes the hold of D-1743.
- Why: with the first fitted table every text, url and money bucket is below those thresholds, so a gate would remove
  nearly every value; the calibrated number tells the caller how far to trust a value, and the caller decides.
- Reversible: yes

### D-1771 — `min_confidence` is one threshold for every field and applies to calibrated buckets only
- Date: 2026-10-18 · Change/PR: resolve-confidence-state (#289) · Status: decided (owner-delegated 2026-10-17)
- Decision: The request's `min_confidence` (0 to 1, unset by default) holds every field alike, required or not, page
  field, row sub-field or page-URL derivation: a calibrated bucket below it abstains with reason
  `below_min_confidence` (was `below_tau`) and keeps its measurement. An uncalibrated bucket never abstains: nothing
  measures it. It is a request member of scrape, batch, crawl and extract (stored in the job's request, read by the
  worker), the playground's Options hold it as a percent, MCP takes the request bodies, and the CLI has it on
  `eval run` only, whose gated run is not stored (a fit on it would be of its own selection).
- Why: a per-field threshold needs a schema-level notion nobody asked for; one number is the smallest control.
- Reversible: yes

### D-1772 — The first calibration table ships
- Date: 2026-10-18 · Change/PR: resolve-confidence-state (#289) · Status: decided (owner-delegated 2026-10-17)
- Decision: `backend/data/calibration.json` is fitted from an uncalibrated `eval run --out` report of the dev split:
  nine buckets (money, text, url; `structured`, `dom`, `agreed`; n 25 to 332; precision 0.59 to 0.97). Records that
  publish from them report `calibrated=true`, and a record's confidence is the least of its required fields'. A refit
  needs the file removed first (a fit refuses a report of a calibrated engine).
- Why: the table is what makes the confidence a measurement; with no gate it costs no coverage.
- Reversible: yes (delete the file)

### D-1773 — A state JSON value has the bucket `state` and ranks last
- Date: 2026-10-18 · Change/PR: resolve-confidence-state (#289) · Status: decided (owner-delegated 2026-10-17)
- Decision: A candidate of source kind `js_state` takes the evidence bucket `state`, and `js_state` is the last kind
  of the text, long_text, url and image_url orders. A key the item layer proved on the page's blocks
  (`collect.items.bind`) is then enough for a row whose block lacks the field to publish it. Exact-match types need
  no order: a lone value publishes, and any other value of the field disagreeing is a conflict as before.
- Why: a proven key is the one way a state value is trusted on its own (it reproduced the blocks' values on at least
  `MIN_ITEMS` rows); ranking it last never lets it beat a value the page shows.
- Reversible: yes

### D-1774 — Rows only in state JSON are not recovered by this change
- Date: 2026-10-18 · Change/PR: resolve-confidence-state (#289) · Status: decided (owner-delegated 2026-10-17)
- Decision: On the dev split the change moves no value of the class "row fields whose labelled value sits in state
  JSON" (77 FN, 0 TP, 48 FP before and after, on 4 listings): no golden page has a proven key whose value lacks a
  bucket. The one clean instance has no block showing any field, so nothing anchors a key (induction proves a key by
  a value the page already holds). Mapping a key by its name would break the generic rules; a per-host config learned
  across pages is the in-architecture route, left as a follow-up.
- Why: avoid a state-row collector that guesses keys; measured, not assumed.
- Reversible: yes
