# Change: owner items D-0783, D-0784, D-0915 and three resolution follow-ups

## Why

Three investigate items waited on the owner (`openspec/project.md` "Open owner items"): SimHash at Hamming 0 still
lets about one in ten one-word edits of a long page pass as `unchanged` (D-0915); role C is asked on every page for a
required field a site never states (D-0784); a learned config becomes the recipe a site is extracted with without a
person seeing it (D-0783). The owner delegated these decisions on 2026-10-17. Three resolution follow-ups ride along:
`js_state` admission stores thousands of copies of one price on a large state blob (#227); a Product that names its
group only through `isVariantOf` holds the group as a child, so the group's variants are not rows (SPEC-13 §9, #247);
a related item alone in its state array still lends its visible price to the page (#243).

## What Changes

- **Unchanged content** (`recurring/`): a page is `unchanged` only when the exact digest of its visible words (BLAKE2b
  over the words SimHash reads, nonce-like tokens left out) equals the stored one; SimHash stays stored beside it and
  reports how far a changed page moved. Owner #40's "only an equal fingerprint is unchanged" holds, now without misses.
- **Absent fields** (`config_ir/`, `resolve/pipeline.py`): learning records in the config's `absent` list each detail
  page field that no page of the run stated (no published value, no valid candidate from any source, role C's
  included). In config mode role C is not asked for an absent field, which stays `missing` with reason `absent`; a
  config page that states it re-tests it (the field leaves `absent` and the site re-learns).
- **Config approval** (`config_ir/`, `services/configs.py`, API, UI): a project setting `require_config_approval`
  (default off: behaviour unchanged). When on, a learning run's validated config is stored `pending_approval`, the
  serving config (or cold extraction) goes on, and `POST /v1/configs/{id}/approve` activates it. The config view shows
  the status and an Approve button; Settings shows the switch.
- **Duplicate state candidates** (`collect/admission.py`): one candidate per field, normalized value and owner, with the
  shortest locator.
- **`isVariantOf`** (`resolve/`): a Product that names its group through `isVariantOf` becomes the group's `hasVariant`
  member, with the group in its place, in every syntax.
- **Lone related items** (`collect/admission.py`): one object in an array that names a document of its own (a URL in its
  scope that is not a media file) is a row, as the rows of an array of two or more are.

## Impact

- Capabilities: [jobs](../../specs/jobs/spec.md), [learning-configs](../../specs/learning-configs/spec.md),
  [llm](../../specs/llm/spec.md), [resolution](../../specs/resolution/spec.md),
  [extraction](../../specs/extraction/spec.md), [variants](../../specs/variants/spec.md),
  [rest-api](../../specs/rest-api/spec.md), [frontend](../../specs/frontend/spec.md).
- Design: owner decision #58 (owner delegation 2026-10-17); D-0783, D-0784, D-0915 answered; D-1340–D-1349.
- Database: `url_state.content_digest`, `project.require_config_approval`, config status `pending_approval` (baseline
  migration, greenfield).
