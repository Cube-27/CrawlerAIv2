# Delta: acquisition

## MODIFIED Requirements

### Requirement: Browser on evidence
In `auto`, the system SHALL retry in the browser an HTTP `shell` or `blocked` result other than 429/503, keeping the
browser outcome only when `ok`; and an HTTP `ok` detail page whose schema requires a `money` field and whose capture
holds no Offer entity and no `money` candidate, keeping the browser outcome only when `ok` and it holds either. Any
later request of a fetch is sent only when `admit_next` allows. The browser MUST NOT be the default. (Previously:
shell or blocked only.) Refs: §7.1, D-0009, D-0203, D-0865, D-0900, owner #48, D-1202.
#### Scenario: Client-rendered offer
- **WHEN** an `auto` fetch of such a detail page answers HTTP `ok` with no Offer and no price, and the browser render
  holds an Offer
- **THEN** the browser capture is kept and the result lists both attempts

### Requirement: HTTP and browser rungs
The HTTP rung SHALL use `curl_cffi` impersonating Chrome (`CRAWLERAI_IMPERSONATE`), at most 5 manual redirects, and
record headers without cookies or proxy credentials. The browser rung SHALL use Patchright headless Chromium, a fresh
context per fetch, one navigation, no scripted actions, capped by `browser_timeout_s`; it reads the page after `load`
once the DOM's structure and text are unchanged for 2 s or, for a 2xx/3xx document, the network is idle, and keeps
the main frame's latest document, following a navigation the document starts itself. The JSON rung (`fetch_json`,
`httpx`, method `api`) shares the HTTP rung's guard, caps, cookie jar and reasons. (Previously: network idle up to
90% of the cap; the first document's response.) Refs: §7.1, D-0130, D-0251, D-0268, owner #48, D-1200, D-1201.
