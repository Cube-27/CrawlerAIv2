# Design: browser parity

## Decisions

### D-1204 — Full Chromium build, headless
- Date: 2026-10-16 · Change/PR: browser-parity (#229) · Status: decided (owner #50)
- Decision: launch `chromium.launch(channel="chromium", headless=True)`, Patchright's full Chromium build in
  Chromium's own headless mode; CI, the Makefile and `CLAUDE.md` install it with `patchright install --no-shell
  chromium`. INV-42.
- Alternatives: the headless shell (Playwright's default for `headless=True`); Google Chrome or a headed browser
  (owner: no).
- Why: Patchright's README installs `chromium`. Not a §22 identity measure: the same Chromium build Patchright ships,
  no forged fingerprint, headers or input.
- Reversible: yes — one launch argument and the install flag.

### D-1205 — No user-agent, client-hint or header override
- Date: 2026-10-16 · Change/PR: browser-parity (#229) · Status: decided (owner #50)
- Decision: drop the per-page CDP `Network.setUserAgentOverride` and the identity probe that built it; contexts set
  only the guard's proxy and `accept_downloads=False`. No `Accept-Language` either: no requirement names one. INV-44.
- Alternatives: the override at context level (Playwright invents high-entropy hints, e.g. `platformVersion`), or a
  `--user-agent` launch flag (empties the high-entropy hints); both measured, both forge a value.
- Why: Patchright README: "do NOT add custom browser headers or user_agent". Measured: the page-level override
  missed service workers, which kept `HeadlessChrome`. Chromium's own user agent still names `HeadlessChrome`; that is
  accepted (owner #50).
- Reversible: yes.

### D-1206 — Interstitial wait
- Date: 2026-10-16 · Change/PR: browser-parity (#229) · Status: decided
- Decision: when the main frame shows a 403, 429 or 503 document that `lacks_site_structure` (the 2xx shell and
  linkless rules of `classify`), the browser waits for the main frame's next document, polling every 0.25 s, up to
  40% of `browser_timeout_s` (18 s at the default 45 s), then settles as before. Each new interstitial waits again
  within the same deadline. Nothing is clicked or typed; no vendor strings.
- Alternatives: every 4xx (would hold real error pages); 401/407/451 too (they ask for credentials or are legal
  refusals, RFC 9110 §11.6, RFC 7725).
- Why: owner #49 (waiting is a browser wait rule, not a §22 measure); an interstitial's script may take longer than
  the 2 s DOM quiet to navigate on.
- Reversible: yes.

### D-1207 — Enforcing the setup
- Date: 2026-10-16 · Change/PR: browser-parity (#229) · Status: decided
- Decision: INV-42 to INV-44 are enforced by `tests/unit/test_browser_setup.py`: a fake Playwright records the exact
  launch options and the context option names, and a source scan of `crawlerai/` fails on identity-changing calls
  (`user_agent=`, extra headers, `setUserAgentOverride`, `add_init_script`, `new_cdp_session`,
  `isolated_context=False`, automation flags).
- Alternatives: review only.
- Why: owner #50 asks that future agents cannot change the fingerprint unnoticed.
- Reversible: yes.
