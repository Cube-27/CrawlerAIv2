## MODIFIED Requirements

### Requirement: Browser on evidence
In `auto`, the system SHALL retry in the browser an HTTP `shell` or `blocked` result other than 429/503, keeping the
browser outcome only when `ok`; an HTTP `ok` detail page whose schema requires a `money` field and whose capture
holds no Offer entity and no `money` candidate, keeping the browser outcome only when `ok` and it holds either; and an
HTTP `ok` listing whose extraction gives no rows, keeping the browser outcome only when `ok` and its extraction gives
rows. Any later request of a fetch is sent only when `admit_next` allows. The browser MUST NOT be the default.
Refs: §7.1, D-0009, D-0203, D-0865, D-0900, owner #49, D-1202, owner #54, D-1246–D-1249.
(Previously: the render on evidence covered detail pages without offer data only.)
#### Scenario: Client-rendered offer
- **WHEN** an `auto` fetch of such a detail page answers HTTP `ok` with no Offer and no price, and the browser render
  holds an Offer
- **THEN** the browser capture is kept and the result lists both attempts
#### Scenario: Client-rendered listing
- **WHEN** an `auto` fetch of a listing answers HTTP `ok` with repeated links but no rows, and the render's extraction
  gives rows
- **THEN** the browser capture is kept, its extraction gives the records, and the result lists both attempts
