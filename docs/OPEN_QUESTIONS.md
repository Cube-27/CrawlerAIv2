# CrawlerAI v2 — Open Questions

These are decisions only the owner, or a future user of the system, can make. Each has a recommended default,
which `ARCHITECTURE.md` assumes until someone overrides it.
- **[User]** marks questions whose answer depends on who ends up using the system, especially config users of an
  external crawler platform.
- **[Owner]** marks ours.

Revised 2026-10-12 for architecture rev 5; rows 14–17 resolved 2026-10-13 (rev 7).

Decisions that belong to candidates (ARCHITECTURE §22) are made only when that candidate is admitted. That covers
CAPTCHA handling, unblocker vendors, the stealth/robots posture and the browser fleet's OS and GPU.

Decisions agents make during implementation go in `DECISIONS.md`. An agent decision that turns out to need the
owner is copied here.

| # | Question | Why it matters | Recommended default |
|---|---|---|---|
| 1 | **[User] What does the external crawler platform's config look like?** We need the field list, XPath dialect, whether CSS is accepted, the pagination and params shape, regex/transform syntax, how listings link to details, and how code hints are attached. | The exporter is what config users receive. | A portable IR around XPath 1.0 + regex + named params (§12), exported as `json` and `platform_draft`. Ask for three real configs: a plain HTML site, a custom site, and an API-backed site. |
| 2 | **[User] Which ATS platforms, and how many job sites per platform?** | Order of adapters after Greenhouse and Lever (§7, §22). | Greenhouse and Lever in L1. Others are admitted by volume or by measured shortfall. |
| 3 | **[User] Which fields are required per category, what precision bar, and which zero-touch target?** | Defines the presets' core fields, the eval composition and the target. | Core fields as in §5.3; precision 0.97; one zero-touch target per phase, measured on **fresh** sites (§16). |
| 4 | **[User] Are GMC or job XML feeds needed, or only CSV/JSON?** | Admits the exporter candidate (§22). | CSV/JSON only until someone asks. |
| 5 | **[Owner] Which LLM providers?** | Roles C, A, D, S (§11). | A provider-agnostic client with two configured providers. No aggregator in production. |
| 6 | **[Owner] Who is the custodian of the hidden and fresh evaluation sets?** | C1: agents must never see these cases, so someone has to hold the access. | The owner plus one engineer. Agent and development credentials get aggregates only. |
| 7 | **[Owner] Where do fresh sites come from, and how often?** | The fresh-site result is the headline accuracy figure (§16). | Monthly, 20–30 sites, stratified by category (§16.1). Sources: WDC Product/JobPosting host lists, ATS tenant lists, hosted-store lists, plus a deliberate share of DOM-only sites. |
| 8 | **[Owner] What labeling budget can we commit?** **Partly resolved 2026-10-12:** none before the crawler works; labeling is milestone M (ARCHITECTURE §21, Appendix A #29). | Without labels there is no measurement, and C13 can't admit anything. | At M: ~300 pages for dev + hidden, starting from the owner's review of crawler output, then ~8–12 hours a month for fresh sites. |
| 9 | ~~**[Owner] Which license?**~~ **Resolved 2026-10-12:** AGPL-3.0, public repo (Appendix A #26). | Dependency policy. | The dependency license deny-list (AGPL, GPL, SSPL, non-commercial) stays in CI so the owner keeps the option to license differently later. Eval data stays private. |
| 10 | **[Owner] Which proxy pool, if any, for sites set to use one?** | `site.proxy_pool` (§7). | One datacenter/ISP pool, configured by hand per site. Anything more is an anti-bot candidate (§22). |
| 11 | **[User] Can past crawl outputs from a user's platform serve as ground truth?** | Our own public-site eval may not match a user's site mix. | Assume no. If offered, such data goes into hidden and fresh, never only into dev. |
| 12 | **[User] Which language for code hints?** | Affects the API-backed site deliverable. | An API recipe as data, plus a PHP snippet rendered from a template. |
| 13 | **[Owner] Which region, and how long do we retain data?** | Object storage and LLM provider region. | One US region. Production captures kept 30 days; eval captures kept forever, privately. |
| 14 | ~~**[Owner] Confirm the agent decisions marked "pending owner confirmation" in `DECISIONS.md`.**~~ **Resolved 2026-10-13:** accepted as written (D-0234). | They were made while writing the specs, and implementation proceeds on them. | Accept them as written unless one is overridden. |
| 15 | ~~**[Owner] Pre-commit eslint hook over its 10 s budget on Windows: keep type-aware rules or speed the hook?**~~ **Resolved 2026-10-13:** moot; the Vite+ hook takes about 4 s (D-0227). (D-0110) | SPEC-00 §4.8 sets < 10 s per one-file commit; the hook takes 10.6–17.4 s on Windows for frontend files. | Keep type-aware eslint in the hook for now; revisit the lint config in a frontend row. |
| 16 | ~~**[Owner] Should hidden/fresh aggregates use secondary (complementary) suppression?**~~ **Resolved 2026-10-13:** yes, complementary suppression (D-0234, ARCHITECTURE rev 7 §16.3). (D-0187) | Bucket and config-status cells are subsets of field-type totals, so one suppressed cell can be recovered by subtraction (§16.3). | Add complementary suppression: when exactly one cell in a group is suppressed, also suppress the next-smallest. |
| 17 | ~~**[Owner] How are hidden/fresh pages labeled at milestone M?**~~ **Resolved 2026-10-13:** the same app on the custodian machine with a private backend, never deployed (D-0234). (D-0214) | The labeling API serves dev only; hidden/fresh labels must never pass through the main deployment (C1). | Run the same app on the custodian machine with a private backend, never deployed. |
