# Delta: acquisition

## ADDED Requirements

### Requirement: Page artifacts from the browser rung (INV-45)
A fetch policy that asks for `screenshot` (viewport or full page, PNG) or `pdf` (print media) SHALL be fetched on the
browser rung, with no adapter or recipe, and the rung SHALL make the files from the rendered page by reading it only
(INV-42..44). A file the browser cannot make, or one over 25 MB, is left out and the fetch still stands. The files live
beside the capture's bundle, are output only (replay never reads them), and are deleted with the bundle by retention.
Enforced by: `tests/unit/test_browser_fetch.py`, `tests/db/test_output_formats.py`; active. Refs: D-1420, D-1421.
#### Scenario: Screenshot over HTTP
- **WHEN** a request asks for `screenshot` or `pdf` and the browser rung is off
- **THEN** it is refused before any job is made
