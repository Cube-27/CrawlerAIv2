## MODIFIED Requirements

### Requirement: Derived values (INV-07)
Derived values SHALL fill only `missing` fields and carry `derived_by`; the only derivations are `absolutize`, then for
a detail page's `T.url` field (`T.url` in every alternative of its path) `canonical_link` (RFC 6596), then
`final_url`, each a named function (`resolve/derive.py`). (Previously: a field whose last rank was `T.url`, such as
`apply_url`, took the page URL too.) Refs: §9, §10, Appendix A #40, D-0442, D-0910, D-1625. Enforced by: resolver
tests; active.
#### Scenario: No url candidate
- **WHEN** a detail page has no url candidate and `<link rel=canonical href="https://example.com/p/1">`
- **THEN** `url` publishes that URL with `derived_by=canonical_link`, source kind `derived`, evidence `derived`
#### Scenario: No stated apply link
- **WHEN** a job page states no apply link and role C claims none
- **THEN** `apply_url` stays `missing`
