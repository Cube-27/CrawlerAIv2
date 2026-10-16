# Tasks

## 1. Browser waits

- [ ] 1.1 Content-stable exit: after `load`, read the page when the DOM's structure and text have been unchanged for
      2 s or (2xx/3xx documents) the network is idle, within the hard cap. Browser tests with the local fake server.
- [ ] 1.2 Follow the document's own navigation: the exchange and raw body come from the main frame's latest
      document response; a navigation in flight is waited for within the budget. Browser test: a 403 page that
      replaces itself with a 200 page is read as `ok`.

## 2. Browser on missing offer data

- [ ] 2.1 `acquire` takes a `needs_render` check from its caller; in `auto`, an HTTP `ok` result it holds true for is
      fetched again in the browser (admission allowing), and the browser result is kept when `ok` and the check no
      longer holds. Scrape, batch and crawl records tasks pass the check for detail schemas that require a money field.

## 3. Archive

- [ ] 3.1 Apply the delta to `openspec/specs/acquisition/spec.md` and archive the change.
