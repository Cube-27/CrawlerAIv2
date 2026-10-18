# CrawlerAI v2 — Open Questions

These are decisions only the owner, or a future user of the system, can make. Each has a recommended default,
which the design (`design/`, the former `ARCHITECTURE.md`) assumes until someone overrides it.
- **[User]** marks questions whose answer depends on who ends up using the system, especially config users of an
  external crawler platform.
- **[Owner]** marks ours.

Revised 2026-10-12 for architecture rev 5; rows 14–17 resolved 2026-10-13 (rev 7); row 19 resolved 2026-10-14; rows 18, 20, 21, 24, 29, 31 and 32 resolved 2026-10-16; rows 26, 27, 30 and 33 resolved 2026-10-17; rows 3, 6, 7, 10, 11, 16 and 17 answered or reframed 2026-10-18 by the master improvement plan (`design/owner-decisions.md` #67).

Decisions that belong to candidates (ARCHITECTURE §22) are made only when that candidate is admitted. That covers
CAPTCHA handling, unblocker vendors, the stealth/robots posture and the browser fleet's OS and GPU.

**Current plan (owner, 2026-10-18, #67).** Work follows the master improvement plan's phases: 0 measure what is real
(golden-set scoring fixes, deletions), 1 acquisition robustness, 2 the item layer, 3 detail precision and recall,
4 learning that adds coverage, 5 acquisition access (**deferred**: vendor-blocked pages stay `blocked`), 6 set growth
in fresh batches. The plan's decision 7 (licensed feeds, managed access, residential proxies) is open and waits for
the owner.

Decisions agents make during implementation go in the decision logs (`decisions/README.md`). An agent decision that turns out to need the
owner is copied here.

| # | Question | Why it matters | Recommended default |
|---|---|---|---|
| 1 | **[User] What does the external crawler platform's config look like?** We need the field list, XPath dialect, whether CSS is accepted, the pagination and params shape, regex/transform syntax, how listings link to details, and how code hints are attached. | The exporter is what config users receive. | A portable IR around XPath 1.0 + regex + named params (§12), exported as `json` and `platform_draft`. Ask for three real configs: a plain HTML site, a custom site, and an API-backed site. |
| 2 | **[User] Which ATS platforms, and how many job sites per platform?** | Order of adapters after Greenhouse and Lever (§7, §22). | Greenhouse and Lever in L1. Others are admitted by volume or by measured shortfall. Shopify admitted by the owner, 2026-10-16 (ARCHITECTURE Appendix A #46, SPEC-15). |
| 3 | **[User] Which fields are required per category, what precision bar, and which zero-touch target?** | Defines the presets' core fields, the eval composition and the target. | Core fields as in §5.3; precision 0.97; one zero-touch target per phase, measured on each **fresh batch** of the golden set (#67). |
| 4 | **[User] Are GMC or job XML feeds needed, or only CSV/JSON?** | Admits the exporter candidate (§22). | CSV/JSON only until someone asks. |
| 5 | **[Owner] Which LLM providers?** | Roles C, A, D, S (§11). | A provider-agnostic client with two configured providers. No aggregator in production. |
| 8 | **[Owner] What labeling budget can we commit?** **Partly resolved 2026-10-12:** none before the crawler works; labeling is milestone M (ARCHITECTURE §21, Appendix A #29). | Without labels there is no measurement, and C13 can't admit anything. | At M: ~300 pages for dev + hidden, starting from the owner's review of crawler output, then ~8–12 hours a month for fresh sites. |
| 10 | **[Owner] Which proxy pool, if any, for sites set to use one?** | `site.proxy_pool` (§7). | One datacenter/ISP pool, configured by hand per site. Residential proxies and managed access are **deferred** (#67, decision 7): a vendor-blocked page stays `blocked` with its label. |
| 11 | **[User] Can past crawl outputs from a user's platform serve as ground truth?** | Our own public-site eval may not match a user's site mix. | Assume no. If offered, such data enters as a fresh batch, scored once before any fix (#67). |
| 12 | **[User] Which language for code hints?** | Affects the API-backed site deliverable. | An API recipe as data, plus a PHP snippet rendered from a template. |
| 13 | **[Owner] Which region, and how long do we retain data?** | Object storage and LLM provider region. | One US region. Production captures kept 30 days; eval captures kept forever, privately. |
| 23 | **[Owner] Should the jobs API expose task failure and block reasons?** (D-0745) | SPEC-10 has no field or event for `url_task.last_error`, so the job page shows a failed or blocked task with no reason (UAT F17), and it cannot show "cancel requested" while a dead worker's lease runs out (F16). | Option (a): `PageOutput.last_error: str \| null` on `/results`, a `task_failed` event `{task_id, url, attempts, last_error}`, and `cancel_requested: bool` on the job summary. |
