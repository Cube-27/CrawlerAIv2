# Tasks

## 1. Acquisition

- [x] 1.1 Vendor stand-in markers in `adapters/challenges.py`; a 2xx HTML document showing one is `blocked` with the vendor's label (HTTP and browser rungs); a 2xx document that declares a refresh and links to no web page is `blocked`; INV-24 amended. (#266)
- [x] 1.2 In `auto`, an HTTP `network_error` gets one browser attempt, kept only when `ok`. (#266)

## 2. Content and extraction

- [x] 2.1 `markdown`/`markdown_fit`/`chunks` of a JSON body: the answer pretty-printed in a fenced `json` block; `html` empty. (#266)
- [x] 2.2 A listing with no rows: `reason` `no_rows` with its cause on the scrape answer and the task, and a `page` member with the page-scope fields; API client and SDKs regenerated. (#266)
- [x] 2.3 `job_listing.locations` (a list of locations) replaces `location`. (#266)
- [x] 2.4 Role C on a listing reads the item blocks' text, mapped back to cleaned-text offsets; measured on the sweep listings. (#266)

## 3. Tracker

- [x] 3.1 Backlog lines of the QA sweep (#263) this change closes removed; follow-ups for what it leaves. (#266)
