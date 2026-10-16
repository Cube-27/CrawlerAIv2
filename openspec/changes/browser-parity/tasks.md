# Tasks

## 1. Browser parity

- [ ] 1.1 Launch full Chromium in headless mode (`channel="chromium"`); install `--no-shell chromium` in CI, the
      Makefile and `CLAUDE.md` §7.
- [ ] 1.2 Remove the user-agent and client-hint override and the identity probe; no custom headers.
- [ ] 1.3 Wait for a main-frame navigation, bounded by a share of `browser_timeout_s`, on a 403/429/503 document
      with no site structure; tests with the local fake server.
- [ ] 1.4 Probe the browser rung before and after each step on the dev interstitial and blocked rows (idx only in
      the PR).
