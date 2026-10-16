# SPEC-13 decisions

Decisions for [SPEC-13 — Variant matrix: per-variant rows from structured data](../specs/SPEC-13-variant-matrix.md).
Template, statuses and rules: [DECISIONS.md](../DECISIONS.md).

### D-0786 — SPEC-13 variant matrix approved
- Date: 2026-10-15 · Spec/PR: SPEC-13; ARCHITECTURE §5.2, §5.3, §10, §22, Appendix A #37, rev 16 (#169) · Status: decided
- Decision: The owner approved SPEC-13 and admitted the §22 variant-matrix candidate ahead of its labels criterion: row-mapped `list<object>` fields with a `key`, preset `commerce_detail` v3 `variants`, the selected variant by URL identity, variant fill for sku and gtin only, label version 2 with row scoring. Built as the spec's four PRs.
- Alternatives: Wait for labels (milestone M) before admitting; a platform adapter first (not now, owner).
- Why: Shopify baseline evidence (variant offers that disagree decline `offers_disagree`); owner approval 2026-10-15.
- Reversible: yes

### D-0787 — Alternatives are deduplicated per entity
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.1–§4.2 (#170) · Status: decided
- Context: §4.1 says the same value at the same locator reached twice is one candidate.
- Decision: A selection is dropped only when an earlier alternative already reached the same (entity, locator); one alternative's own selections are all kept.
- Alternatives: Dedupe on the locator alone, across entities.
- Why: Single paths stay byte-identical; ownership is per entity, and evidence counts distinct source kinds.
- Reversible: yes

### D-0788 — A sub-field candidate's entity is the alternative's root entity
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.1–§4.2 (#170) · Status: decided
- Context: §4.2: sub-fields yield candidates exactly as a top-level field does.
- Decision: `Candidate.entity_id` is the entity of the alternative's root type the path started from.
- Alternatives: The entity holding the value.
- Why: Reuses the existing ownership model.
- Reversible: yes

### D-0789 — og role with path alternatives
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.1–§4.2 (#170) · Status: decided
- Context: §4.1: a field's og role with alternatives.
- Decision: A role exists only when every alternative is two-step and all name the same property; a row-mapped field has none.
- Alternatives: Ignore alternatives that are not two-step.
- Why: Conservative: `Product.image|Product.brand.image` may name the brand's image.
- Reversible: yes

### D-0790 — The item of a row-mapped field has no `schema_org`
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.1–§4.2 (#170) · Status: decided
- Context: §4.2 defines the row path on the list and paths on the sub-fields only.
- Decision: A path on the item is rejected (SPEC-04 §4.2 text).
- Alternatives: Ignore it.
- Why: It would be a second row path with no meaning.
- Reversible: yes

### D-0791 — Adapters get no row-mapped fields
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.1–§4.2 (#170) · Status: decided
- Context: `collect/adapter` maps field paths to adapter queries.
- Decision: Row-mapped fields are left out; the entity kinds are the roots of every alternative of the mapped fields.
- Alternatives: Pass row paths to adapters.
- Why: A row path names nodes; adapters read values.
- Reversible: yes

### D-0792 — No vocabulary check of paths to extend
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.1–§4.2 (#170) · Status: decided
- Context: §4.1: every alternative is checked against the pinned schema.org vocabulary as today.
- Decision: No change: paths are checked by the naming pattern, now per alternative.
- Alternatives: Add a vocabulary check of properties.
- Why: No such check exists today; adding one is out of this row's scope.
- Reversible: yes

### D-0793 — An AggregateOffer is not a variant holder
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.6 (#171) · Status: decided
- Context: §4.6 lists the Offers directly under the target as variant holders.
- Decision: `EntityGraph.holders` excludes an AggregateOffer.
- Alternatives: Admit it as a holder.
- Why: schema.org: a summary of several offers, not the offer of one variant (as §4.3's never-a-row).
- Reversible: yes

### D-0794 — Variant fill when the selected holder is an Offer
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.6 (#171) · Status: decided
- Context: §4.6: fill takes the selected variant's candidates.
- Decision: A selected direct Offer is not a variant; fill then uses the every-variant-agrees rule.
- Alternatives: Fill from the Offer.
- Why: An Offer's own values are already the target's (atomic offers).
- Reversible: yes

### D-0795 — "The target has no owned candidate" for variant fill
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.6 (#171) · Status: decided
- Context: §4.6 conditions variant fill on the target stating nothing.
- Decision: No candidate of the field is `owned_by` the target, page-level ones included, whatever its validity.
- Alternatives: Only valid owned candidates count.
- Why: Conservative: an invalid value the target states is still its statement.
- Reversible: yes

### D-0796 — Variant rules apply to a detail page's target only
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.6 (#171) · Status: decided
- Context: `Resolver` also resolves listing rows and the listing page.
- Decision: `Resolver.variants` is None there; listings are unchanged.
- Alternatives: Apply to listing rows too.
- Why: §4.6 covers a detail page's single offer fields.
- Reversible: yes

### D-0797 — Role C skips every object field and list of objects
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.3–§4.9 (#172) · Status: decided
- Context: §4.9: role C is never asked for a row-mapped field nor any object-typed field.
- Decision: `_gaps` also skips a `list<object>` without `schema_org`.
- Alternatives: Skip row-mapped and object fields only.
- Why: A verbatim span cannot hold typed sub-fields either way.
- Reversible: yes

### D-0798 — A row field's locator and source kind
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.3–§4.9 (#172) · Status: decided
- Context: §4.5: source_kind and locator of the first published row's entity.
- Decision: The locator is that row's entity id; the source kind is its first published sub-field's.
- Alternatives: The first published sub-field's locator.
- Why: An entity id is a `jsonld:`/`microdata:` locator.
- Reversible: yes

### D-0799 — When an unpublished row field is abstained
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.3–§4.9 (#172) · Status: decided
- Context: §4.5: abstained when every row was dropped because its sub-fields abstained.
- Decision: `abstained`/`below_tau` only when every variant was dropped `key_unpublished` with an abstaining key sub-field; else `missing` with the furthest reason (`no_rows` < `no_row_key` < `row_key_conflict` < `key_unpublished`).
- Alternatives: Abstained whenever any sub-field abstained.
- Why: The literal reading of §4.5.
- Reversible: yes

### D-0800 — Reject reasons of dropped rows' candidates
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.3–§4.9 (#172) · Status: decided
- Context: Stored candidate rows need a reject reason.
- Decision: Candidates of rows dropped before resolution take the row's reason; those of a `key_unpublished` variant take `key_unpublished`.
- Alternatives: `not_owned`.
- Why: The stored candidate says why it was not used.
- Reversible: yes

### D-0801 — Learning's schema without row fields
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.3–§4.9 (#172) · Status: decided
- Context: §4.9: learning produces no steps for a row field.
- Decision: Induction and synthesis get the schema without row-mapped fields (`learnable`); the report says `not_learned: row_field`.
- Alternatives: Filter after induction.
- Why: No step is ever tried for a row field.
- Reversible: yes

### D-0802 — A URL the target and an Offer both carry
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.4 (#173) · Status: decided
- Context: §4.4 excludes the target's own URL as a key value and keeps its Offers' URLs; `Entity.urls` merges both, so a URL both carry could be either.
- Decision: Such a URL is a row key value only when exactly one row carries it; repeated by several rows, it names the group and is no key (clarifying edit to SPEC-13 §4.4).
- Alternatives: Keep it as a key (joins every row into one `row_key_conflict`); split `Entity.urls` by origin in the collectors.
- Why: One row's URL identifies that variant; a URL many rows repeat identifies the group (C7).
- Reversible: yes

### D-0803 — Row-mapped labels under `lists`
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.10 (#174) · Status: decided
- Context: SPEC-13 §4.10 shows the `variants` label but not where it sits in the labels document.
- Decision: A new top-level key `lists`, by field name, in `label_version` 2; left out of a dump when empty.
- Alternatives: Put row labels under `fields` as a union shape.
- Why: `fields` keeps one label shape for the API, stored documents and the labeling screen; v1 documents are unchanged.
- Reversible: yes

### D-0804 — Row metrics shape
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.10 (#174) · Status: decided
- Context: §4.10 asks for row precision and recall, with hidden cells suppressed.
- Decision: `row_matching`: one aggregate over all row-mapped fields (`n` = label rows), suppressed under `MIN_CELL`; `row_matching_by_field` per `schema|field`, dev only.
- Alternatives: Per-field cells only.
- Why: An aggregate that names no schema can leave the protected job.
- Reversible: yes

### D-0805 — Row sub-fields outside zero-touch and precedence fitting
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.10 (#174) · Status: decided
- Context: Zero-touch is about required fields (SPEC-03 §4.6); calibration measures row values apart (SPEC-13 §4.5).
- Decision: An unmatched engine row of a row-mapped field does not break zero-touch; sub-field judgments carry no source cells.
- Alternatives: Count them as listing rows are counted.
- Why: `variants` is optional; a row value can be wrong through a row match, which says nothing about a source kind.
- Reversible: yes

### D-0806 — Pre-fill and labeling screen with row-mapped fields
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.10 (#174) · Status: decided
- Context: Role C is never asked for a row field (§4.9); the screen edits only field labels.
- Decision: The pre-fill leaves row-mapped fields out and writes version 1; the screen keeps stored `lists` and writes version 2 only when `lists` is non-empty.
- Alternatives: Edit variant rows in the screen now.
- Why: A pass saved from the screen never drops row labels added through the API, and labeling keeps working on preset v3 pages.
- Reversible: yes

### D-0808 — An AggregateOffer is none of a variant holder's Offers
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.3, §4.4, §4.6 (#176) · Status: decided
- Context: §4.3 says an AggregateOffer summarizes several offers and is no offer of one item; §4.6's holders already left it out, but `offers_of` and the row key exclusion did not (CodeAnt comments on #171, #173).
- Decision: `offers_of` and `_not_keys` leave AggregateOffers out: a selected variant's AggregateOffer price does not publish as its price, and an AggregateOffer repeating the target URL does not make it a row key.
- Alternatives: Treat an AggregateOffer under a variant as that variant's offer.
- Why: One rule for AggregateOffers across holders, offers and row keys (C7: decline rather than guess).
- Reversible: yes

### D-0850 — Field types with a transitive equality define it as a hashable key
- Date: 2026-10-15 · Spec/PR: SPEC-13 §4.4, SPEC-04 §4.5 (#196) · Status: decided
- Decision: Each type module except location has `key(value, spec)`; `dispatch.equal` compares keys, and `dispatch.equality_key` is None for location and for a list or object that holds one. Row linking (`rows.linked`) buckets key values in one pass and compares only unkeyed values pairwise.
- Alternatives: Keep a per-type `equal` next to `key` (two definitions that can drift); keep row linking pairwise.
- Why: Linking becomes linear with the same result (a property test against the pairwise reference), and each type keeps one equality (C8).
- Reversible: yes

### D-0905 — A required row-mapped field counts toward zero-touch
- Date: 2026-10-16 · Spec/PR: follow-up (#202) · Status: decided
- Decision: A required, labeled row-mapped field holds when every sub-field judgment of its rows is TP or TN and at least one is TP, so a missing or extra row breaks zero-touch; version 1 labels leave it unscored. D-0805 still holds for optional row fields.
- Alternatives: Fold its sub-fields into one judgment (changes the report's shape).
- Why: SPEC-03 §4.6's required-field rule applies to it (#176).
- Reversible: yes

### D-0945 — No default-variant rule for multi-variant availability (round-1 class 12)
- Date: 2026-10-16 · Spec/PR: SPEC-13 §2, §4.6, round-1 eval class 12 (#207) · Status: superseded by D-1057
- Decision: Not built. With no variant named by the page URLs, offer fields stay `offers_disagree`; the URL-named variant is already selected (`select_variant`).
- Alternatives: First offer as the default.
- Why: SPEC-13 excludes any default other than the URL-named variant (C7); changing it is an owner question.
- Reversible: yes

### D-0963 — `variant_id` is not a row key
- Date: 2026-10-16 · Spec/PR: SPEC-13 §4.7 (#208) · Status: decided
- Decision: Each `variants` row gains `variant_id` (identifier, custom; `Product.productID`), the id the variant states. `key` stays `["gtin", "sku", "url"]`, so row matching (§4.4) is unchanged.
- Alternatives: add it to `key`.
- Why: a productID's scheme is the site's own, and row matching was designed and tested on the three keys.
- Reversible: yes

### D-0966 — No `variesBy` tuple or position as a variant row key
- Date: 2026-10-16 · Spec/PR: reference-eval follow-ups (#209) · Status: decided
- Decision: Row keys stay identifier or url sub-fields; a variant stating neither still drops `no_row_key`.
- Alternatives: Key on the `variesBy` properties' values, or on productID/mpn.
- Why: ARCHITECTURE §5.2 and §4.2/§4.7 here limit keys to identifier/url and do not read `variesBy`. On the eval-ref set's 11 `no_row_key` pages, 10 have Offers stating no identifier and no URL but the page's, and 1 is a standalone variant Product beside its ProductGroup (the §9 `isVariantOf` issue); a `variesBy` key recovers none. productID is `variant_id`, not a key (Appendix A #42).
- Reversible: yes.

### D-1057 — Owner answer to D-0945: no default variant; varying values only in `variants`
- Date: 2026-10-16 · Spec/PR: SPEC-13 §4.6 (#216) · Status: confirmed
- Decision: "no default — all variant schema goes into variants and common schema stays out of variants, simple." `select_variant` and the `other_variant` rejection are removed: a multi-variant product's top-level price, availability and stock quantity publish only when every Offer agrees (else `conflict`, `offers_disagree`, unchanged), and a top-level sku or gtin fills from variants only when all agree. A URL naming one variant selects nothing. INV-36 superseded by INV-38; Appendix A #37 amended, #44 added.
- Alternatives: keep the URL-named variant (the previous rule); the first Offer as default.
- Why: owner answer, 2026-10-16 (Appendix A #44).
- Reversible: yes

### D-1059 — Common-value reading of the variants answer
- Date: 2026-10-16 · Spec/PR: SPEC-13 §4.6 (#216) · Status: decided
- Decision: A top-level field whose variants disagree keeps status `conflict` with reason `offers_disagree` (no new reason), so the gap rule does not ask role C for it. `variants` rows are unchanged: each row keeps its own values even where all rows agree. The `commerce_detail` descriptions of price, availability, stock_quantity, sku, gtin and color now say the top-level value is the product's common one and per-variant values are in `variants` (role C and role A read them).
- Alternatives: a new reason such as `varies_by_variant`; dropping common values from rows.
- Why: the smallest change that matches the answer; a new reason would change the reason vocabulary the eval and UI read, and stripping common values from rows would make a row's meaning depend on its siblings.
- Reversible: yes
