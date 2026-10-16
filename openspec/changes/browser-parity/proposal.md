# Change: browser parity with Patchright's documented setup

## Why

The browser rung fails interstitial pages (403 documents with no site structure that replace themselves after a
script runs) that an earlier Patchright setup passed. v2 departs from Patchright's documented setup in three ways: it
runs the Chromium headless shell instead of the full Chromium build, it overrides the user agent and client hints
per page (Patchright's README: do not set a custom user agent or browser headers), and it reads a 4xx document after
2 s of DOM quiet, before the document has had time to navigate on. The owner (2026-10-16): Patchright already works;
align with its documented practice, add no anti-bot measure.

## What Changes

- Launch the full Chromium build in headless mode (`channel="chromium"`), and install it with
  `patchright install --no-shell chromium` (CI, Makefile, `CLAUDE.md` §7).
- Drop the user-agent and client-hint override and the identity probe: the page, its workers and its requests show
  Chromium's own identity. No custom headers.
- A 403, 429 or 503 document whose structure is no site page (a shell, or text without a hyperlink:
  `acquire/classify.py`) is read once the main frame navigates on, or after a bounded share of `browser_timeout_s`,
  instead of after 2 s of DOM quiet. No clicks, no input, no vendor strings.

Not a §22 identity measure: it is the same Chromium build Patchright ships, with no forged fingerprint, headers or
input.

## Impact

- Capability: [acquisition](../../specs/acquisition/spec.md) (delta in `specs/acquisition/spec.md`).
- Files: `backend/src/crawlerai/acquire/browser.py`, `backend/src/crawlerai/acquire/classify.py`, their tests,
  `.github/workflows/ci.yml`, `Makefile`, `CLAUDE.md`, `backend/pyproject.toml` (marker text).
