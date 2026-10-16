# Resolution and confidence

Design rationale, split from the former `docs/ARCHITECTURE.md` with its section numbers kept (code and history cite `ARCHITECTURE §N`). Index: [README.md](README.md).

## 10. Resolution and confidence

Three structural stages, then a simple preference rule. A learned ranker is a candidate (§22).

| Stage | Mechanism |
|---|---|
| **Validity** | The type normalizer (§9). Invalid or ambiguous candidates keep a reason and never publish. |
| **Ownership** | From structure (§8.2 rule 3). A candidate not owned by the target entity never publishes. |
| **Intent** | `select_target(request_url, final_url, canonical_url, entities) → entity \| ambiguous`. Ambiguous means `conflict`. |
| **Preference** | **Exact-match types** (money, identifier, enum, date, range, location): if the valid, owned candidates agree after normalization, publish; if they disagree, the field is `conflict` and nothing is published. **Text, url and image:** a per-type source-precedence order in `source_precedence.yaml`, fitted on dev only and measured on hidden. |

**Atomic offers.** Price, currency and availability come from one `Offer`. With several Offers, the target's own
and its variants' (§8.2 rule 3), the field is `conflict` unless they all agree.
An aggregate `lowPrice` is never the current price.

**Variant matrix (Appendix A #37, #44, SPEC-13).** No variant is a default: what varies across variants is
published only in the row-mapped `variants` field, and what is common stays at the top level. The single offer
fields publish only when every Offer agrees (the rule above), whatever variant a page URL names; a top-level `sku`
or `gtin` the target leaves empty takes its variants' value only when every variant states the same one. A
single-variant product publishes at the top level as before. A row-mapped list resolves one row per variant: rows reached from the target, matched across
sources by key, each sub-field resolved by these stages inside its row, with price and availability from one
Offer of the row and evidence per sub-field. Only structured collectors give rows; learning and role C do not.

**Confidence from evidence buckets.** Each published field carries an `evidence` value:
- `adapter`: adapter or API recipe;
- `structured`: one structured source;
- `agreed`: two or more **independent** candidates of different source kinds agree;
- `dom`: one structural DOM value (§8.1);
- `config_corroborated`;
- `config_uncorroborated`: also used for `operator` fields, until labels show they need a bucket of their own;
- `llm_grounded`;
- `derived`: a detail page's `url` derived from the canonical link (RFC 6596) or the final URL when no candidate
  states it (SPEC-05 §4.8), with source kind `derived` and a `derived:` locator naming the derivation.

The field's confidence is the measured precision of its (field type, evidence) bucket on **dev**. Buckets with fewer
than 30 dev labels report `calibrated=false`. Once a bucket is calibrated, a bucket below τ (0.97 for required
fields, 0.95 for optional) abstains.

Uncalibrated buckets publish with the flag set. This is a deliberate trade-off for progressive cold mode (Appendix A
#23): the caller and agents can see that the value is not yet backed by measurement. Hidden and fresh report the
same buckets' precision, which shows whether dev calibration generalizes. Record confidence is the minimum over
required fields, and empty if any of them is uncalibrated.

**Incomplete pages.** When a required field or group doesn't publish:
- a **caller-supplied** URL (`scrape`, `batch_scrape`, `extract`, including URLs expanded from a caller's glob) returns the record with per-field statuses and
  `complete=false`, outcome `partial`. The caller chose the page kind, and every unpublished field says why;
- a **crawl-discovered** URL produces `no_match` and no record (§23).
