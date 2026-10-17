## MODIFIED Requirements

### Requirement: Browser on evidence
In `auto`, the system SHALL retry in the browser an HTTP `shell` or `blocked` result other than 429/503, and an HTTP
`error` whose reason is `network_error`, keeping the browser outcome only when `ok`; a 503 that
`classify.interstitial` judges to stand in for the page, after the site's pause (`Retry-After`, else the first
backoff), keeping the browser outcome only when `ok`; an HTTP `ok` detail page whose schema requires a `money` field
and whose capture holds no Offer entity and no `money` candidate, keeping the browser outcome only when `ok` and it
holds either; and an HTTP `ok` listing whose extraction gives no rows, keeping the browser outcome only when `ok` and
its extraction gives rows. An HTTP listing shell kept with no browser outcome is `ok` when it is a shell by the listing
rule alone. Any later request of a fetch is sent only when `admit_next` allows. The browser MUST NOT be the default.
(Previously: a network error ended the fetch.)
Refs: §7.1, D-0009, D-0203, D-0865, D-0900, owner #49, D-1202, owner #54, D-1246–D-1249, D-1261, D-1263, D-1472.
#### Scenario: Client-rendered offer
- **WHEN** an `auto` fetch of such a detail page answers HTTP `ok` with no Offer and no price, and the browser render
  holds an Offer
- **THEN** the browser capture is kept and the result lists both attempts
#### Scenario: Client-rendered listing
- **WHEN** an `auto` fetch of a listing answers HTTP `ok` with repeated links but no rows, and the render's extraction
  gives rows
- **THEN** the browser capture is kept, its extraction gives the records, and the result lists both attempts
#### Scenario: Listing shell whose render fails
- **WHEN** a listing answers HTTP with site structure but no repeated items, and the browser render is `blocked`
- **THEN** the HTTP capture is kept as `ok` and its attempt stays `shell`
#### Scenario: 503 interstitial
- **WHEN** HTTP answers 503 with `Retry-After: 7` and a script-only document
- **THEN** the browser attempt waits for a turn at least 7 s later, and its `ok` is kept
#### Scenario: Network error
- **WHEN** an `auto` fetch's HTTP attempt ends `error` with `network_error: curl 92` and the browser answers `ok`
- **THEN** the browser capture is kept and the result lists both attempts

### Requirement: Structural outcome classification (INV-24)
The system SHALL classify each final response from status and structure (the classes and the shell, linkless page,
self-refreshing page and listing-shell rules in `acquire/classify.py`: a 2xx HTML page that is no shell and has no
hyperlink, or that declares a refresh and has no hyperlink to a web page, is `blocked`; a listing without repeated items
is a shell unless its structured data lists items), and from one kind of site data only: a 2xx HTML document that shows
a vendor's stand-in marker (`adapters/challenges.py`) is `blocked`. Generic code and the remembered fetch method MUST NOT
use vendor or challenge-page strings, and blocked and shell pages end with zero records. Bodies are decoded by HTML
encoding sniffing (D-1152). (Previously: no vendor data selected a class.) Refs: §7.1, C2, C3, D-0114, D-0932, D-0993,
D-1157, D-1158, D-1326, D-1380, D-1470, D-1471.
Enforced by: the site-literal scan (INV-03), classify and challenge tests and review; active.
#### Scenario: Status classes
- **WHEN** the final status is 410, 451 or 418
- **THEN** the class is `not_found`, `blocked` or `error` respectively
#### Scenario: Vendor stand-in served with 200
- **WHEN** a 200 HTML document shows a vendor's stand-in marker and links to pages of its site
- **THEN** the class is `blocked` with that vendor's challenge label

### Requirement: Challenge labels
A `blocked` or `shell` attempt of any rung SHALL carry `challenge`: the vendor whose signature (`adapters/challenges.py`:
response header names, cookie names, also those a browser context holds, challenge resource paths, stand-in markers)
the response shows, else `structural` when `classify.interstitial` holds, else none; the label is counted per label and
rung and slows the host's rate. (Previously: no stand-in markers.) Refs: owner #58, D-1326, D-1355, D-1470.
#### Scenario: Structural challenge
- **WHEN** HTTP answers 403 with a script-only document that matches no vendor signature
- **THEN** the attempt is `blocked` with `challenge: structural`
