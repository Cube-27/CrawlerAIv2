# Design overview

Why the system is shaped as it is: goals, the evidence behind the generalization contract (the rules C1–C13 are in
[../project.md](../project.md#generalization-contract-c1c13)), what must not reappear, the milestone-M rules and the
candidates register. Sections are verbatim from ARCHITECTURE rev 26 with their numbers; the full rev-26 text, which
code comments cite as `ARCHITECTURE §N`, is frozen in the [archive](../changes/archive/2026-10-16-architecture-rev26/ARCHITECTURE.md).
Since rev 27 (2026-10-16, D-1136) the current behaviour lives in [../specs/](../specs/), owner decisions in
[owner-decisions.md](owner-decisions.md), and this file changes only with owner approval (`CLAUDE.md` §6).

## 1. Goals and non-goals

**What it is.** It takes any URL or site and returns clean, normalized, typed records for a schema the caller
chooses, plus an executable per-site config. It is used through a REST API, an MCP server and a web UI. The API shapes are
our own. Commerce and jobs are the first schema presets, not the limit. The
project is open source under AGPL-3.0 (Appendix A #26).

**Users** (Appendix B):
- *config users* (crawl and solution engineers) consume configs for an existing crawler platform;
- *data users* consume records;
- agents use it through MCP.

### Goals

| # | Goal | Measured by |
|---|---|---|
| G1 | **Works on sites nobody tuned against.** | Precision and coverage per field type on the **hidden** and **fresh** sets (§16). The gap between dev and fresh results. |
| G2 | **Precision first.** A wrong published value is worse than a missing one. | Required-field precision ≥ 0.97 on hidden. False publishes on `absent` labels ≈ 0. Wrong-product values = 0. |
| G3 | **Any schema.** Callers define a schema, or describe one in a prompt (§5). | Custom schemas use the same pipeline. Accuracy is claimed per schema only after it has labels. |
| G4 | **Records and executable configs** from one pipeline. | Every exported config is re-executed on held-out pages before release (§12). |
| G5 | **Progressive.** The first call on an unknown site works; repeat calls become deterministic and cheap. | Share of pages served by a config. Time from URL to accepted config. |
| G6 | **Recurring crawls are cheap.** Change detection from day one. | LLM calls per 1k recurring pages ≈ 0. |
| G7 | **Replayable.** Any record can be regenerated from its stored capture. | Replay harness in CI. |

Usage (LLM tokens, browser-seconds, proxy bytes) is counted per job for visibility and runaway budgets. An
estimated LLM cost, from the providers' published prices kept as versioned data, is shown for visibility too
(owner, 2026-10-14). There is no billing (Appendix A #2).

### Non-goals

- Page-type detection. The caller chooses detail or listing (§23).
- Web search and scripted browser actions (Appendix A #21), except a single-URL listing scrape's paging actions
  (Appendix A #52).
- Multi-tenant SaaS machinery: billing, signup, tenancy, user accounts, roles. One deployment serves one
  organization, with API keys.
- Enrichment, product intelligence, knowledge graphs.
- Web-scale crawling. The design point is 5k–10k pages/day, with 10× headroom by adding workers.
- Authenticated or paywalled crawls.
- Anything listed in §22, until it is admitted.

## 2. Generalization contract

Both earlier versions worked on the sites they were tuned on and produced garbage on new ones. These rules are
binding. A change that conflicts with them is wrong, even if it fixes a site.

### 2.1 What went wrong (evidence)

| Mechanism | Invoro **[Invoro]** | v1 **[v1]** |
|---|---|---|
| **The quality check was the tuning set** | `TEST_SITES.md`: 253 URLs, no expected values. The loop was: an LLM audits output for those URLs, then another agent fixes each defect. The labeled set the harness pointed to was never committed. | The one labeled set had 82 cases on 79 hosts, and 78 of those were test hosts. The `unseen_domain` partition was never run. Corpus gates were banned. Fixes were judged by case number. |
| **Fixes became global lists** | 309 rule keys and 4,507 entries. Cookie-consent words became variant noise. One retailer's image filenames became a colorway rule. | 8,311 config literals. One title list grew from 15 to 45 entries taken from individual retailer pages. One retailer's search-vendor attribute went into the generic card selectors. |
| **"Literals in config" moved site logic instead of removing it** | 209 retailer-literal lines in 24 non-adapter files; a 25-host currency table. | The same tables were inherited. 36 "platform families", some of them a single company. The genericness test scanned the wrong folder. |
| **Normalization guessed** | `$`→USD. Availability matched by substring order ("unavailable" contains "available"). | `$`→USD (an Argentine store published USD). URL size code `004` published as a size. Seller published as brand. Color guessed from quoted words. |
| **Same field normalized in many places** | — | Currency in 13 files, availability in 12, brand in 14 functions. |
| **Agents optimized visible checks** | About 10 of 15 commits were churn from LOC budgets and bot-review backlogs. | 10 of 23 sampled fixes were site patches presented as generic. 222 tests name a retailer. Zero property tests. |
| **Rules carried forward** | Lists were copied into v1 almost verbatim. | — |

The cause was a feedback loop with **no held-out signal**, combined with fixing one site by adding a rule that runs
on every site.

### 2.2 Rules

C1–C13: [../project.md](../project.md#generalization-contract-c1c13).

### 2.3 How v2 handles sites nobody has looked at

The generic layer is small: structured-data standards (§8.1), type normalizers (§9), and grounded per-page LLM
extraction for whatever those miss (§8.4). Site-specific knowledge is learned per site at run time, stored as data
(§8.3), and measured on sites nobody tuned against (§16).

## 20. Prior versions

v2 is built from scratch (Appendix A #24). No code, lists, config, tests, prompts or data are ported (C12). When a
candidate from §22 is admitted, its design may *read* Invoro or v1 to learn what was tried. The mechanism is then
re-derived from standards and evidence; nothing is copied.

**Must not reappear**, whatever form it takes:

| Pattern | Seen in |
|---|---|
| Generic DOM selectors per field (`[class*='price' i]`, bare `h1`, card-selector lists) | Both |
| Noise, stop-word or phrase lists grown from observed pages | Both (4,507 and 8,311 entries) |
| Host-keyed tables: currency, brand fallbacks, "platform families" of one company | Both |
| Defaults that invent values (`$`→USD, size from URL code, seller as brand, color from title) | Both |
| Several modules normalizing the same field | v1 |
| Root/entity selection by additive weights; multiple rollup passes re-deciding fields | v1 |
| An LLM audit of the tuning sites used as the quality signal | Invoro |
| Tests named after sites; regression suites pinned to one run's defects | Both |
| LOC or complexity gates driving file splits | Both (v2 keeps one complexity limit and a non-failing file-length warning, C11) |

## 21. Build order (core only)

Labeling is deferred until the crawler works end to end (Appendix A #29). Layers L0–L4 are built and accepted on
**functional** criteria: tests, property tests, replays of stored captures, and spec acceptance criteria. Every
claim about accuracy waits for milestone **M**. The measurement machinery itself is still built first, so M only
needs labels, not code.

| Layer | Builds | Done when |
|---|---|---|
| **L0 Foundations and measurement machinery** | Repo foundations (SPEC-00); persistence and storage including the private eval store; eval splits with custodian access; labeling tool; replay; metric report and protected job (a placeholder until M); CI checks; HTTP fetch | Replay is deterministic on stored captures; the labeling tool works; the private store is unreadable with app credentials |
| **L1 Extraction** | Schema registry and presets; type normalizers for preset types; Patchright browser on evidence; Greenhouse + Lever adapters; structured collectors; resolver with evidence buckets; role C cold extraction; role S; `scrape` endpoint with records and markdown | Spec acceptance criteria pass on synthetic fixtures and unlabeled dev captures; every published field carries evidence and `calibrated=false` |
| **L2 Configs and progressive mode** | Config IR and executors; induction; role A synthesis; validation and corroboration status; progressive state; drift suspension; API-backed pages with role D; `json` and `platform_draft` exporters | A dev-capture site reaches `active` with a validated config; release check passes |
| **L3 API and MCP** | `map`, `crawl`, `extract`, batch, jobs, SSE, webhooks; MCP server | Every endpoint works through REST and MCP on dev captures; SSRF tests pass |
| **L4 Recurring** | Conditional GET, content and record fingerprints, listing diff | Unchanged pages skip extraction; record versions carry `changed_fields` |
| **M Measurement** (owner-led, once the crawler is usable) | Dev labels from the owner's review of crawler output; hidden and fresh drawn under the rule below; first calibration and `source_precedence` fit on dev; protected gate switched on | Precision and coverage per field type, evidence bucket and config status published for dev, hidden and the first fresh sample; wrong-product = 0 |

**Keeping a hidden set possible (C1).** Every site that development touches (in the main DB `site` table, in dev
captures, or in debugging) is dev. When M starts, hidden and fresh sites are drawn only from hosts in none of
those places. Sites the owner reviews and corrects while building dev labels are dev too, never hidden. This is
the one rule that stops the deferral from repeating §2.1.

**Before M:**
- confidence is `calibrated=false` everywhere (§10);
- precedence uses the spec's initial order;
- drift margins use their defaults;
- the protected job passes as `no_baseline`.

The engine works, but accuracy is unknown. Nothing claims otherwise, in docs, PRs or UI.

There are no pre-planned hardening layers. After M, work comes from §22 candidates admitted by evidence. The specs
in `specs/` follow this order.

## 22. Candidates register

These are not designed and not built. Each is admitted (C13) only when the stated evidence appears, and its effect
is measured after it is added.

| Candidate | Would address | Admitted when |
|---|---|---|
| **Learned, calibrated ranker** (gradient boosting, Platt/isotonic, conformal routing) | Wrong choices among valid, disagreeing candidates | Precedence or `conflict` decisions cause a material share of hidden errors or lost coverage. |
| **LLM adjudication** among conflicting candidates | `conflict` abstentions on resolvable cases | The `conflict` rate on hidden required fields is material, and labels show one candidate was right. |
| **Independent verifier** for configs | Wrong selectors that validate against themselves | Hidden precision of `uncorroborated` config fields is below τ, and they are a material share of fields. |
| **Self-consistency sampling** for role C | LLM value errors | Hidden precision of the `llm_grounded` bucket is below τ. |
| **Generic structural DOM collectors** (repeated structure, label–value pairs, typed value spotting) | Cold-mode cost or coverage on DOM-only sites | Role C cost or coverage on DOM-only fresh sites misses target, and dev shows the collector would help. **Label–value pairs and the main image admitted 2026-10-16** by the owner from the reference eval (Appendix A #42); repeated structure for listing row item URLs only (§8.6, Appendix A #47); other repeated structure and typed value spotting are not. |
| **More platform adapters** (iCIMS, ADP, UKG, Paycom; Shopify admitted, Appendix A #46; Workday, Oracle Recruiting, Ashby, SmartRecruiters, Recruitee, Workable and Rippling admitted, #57) | Coverage or cost on those platforms | Results for the platform fall short through the generic path, or volume justifies it (OPEN_QUESTIONS #2). |
| **Variant-matrix handling** | Per-variant price and availability; the multiple-Offer `conflict` | **Admitted 2026-10-15** by the owner ahead of labels (Appendix A #37); designed in SPEC-13. |
| **Anti-bot measures**: allowlisting program, cookie handoff, vendor strategies, real Chrome with a behaviour layer (Appendix A #20 owner note: no Patchright on real Chrome), residential proxies, unblockers, CAPTCHA handling, detection bench | Blocked pages | The `blocked` or `shell` outcome rate for a category is material. The cheapest measure that fixes the blocked class is admitted first. |
| **Recurring schedule storage** | Callers having to re-submit | Recurring volume makes re-submission a burden. |
| **Review queue UI** beyond labeling and config correction | Operator throughput | Operators correct configs often enough that the API and config view slow them down. |
| **Adaptive recrawl schedule; API delta fetches** | Recurring cost | Recurring volume makes fetch cost material. |
| **GMC feed and job XML exporters** | Feed delivery | A user asks (OPEN_QUESTIONS #4). |
| **Site health dashboard, alerts** | Operations | Production use starts. |
| **WARC capture format** | Interoperability with archive tools | Someone needs pywb or WARC output. |
| **Web search; browser actions; authenticated crawls** | Scope | The owner decides (Appendix A #21). **Browser actions admitted 2026-10-17** for a single-URL listing scrape only, opt-in: scroll and structural paging controls, never typing, forms, logins or CAPTCHA (Appendix A #52). |

## 23. Deferred: page-type gate

Out of scope (Appendix A #5, #10).

- **Risk.** v1 published records from search, terms-and-conditions and advice pages submitted as detail URLs (4 of
  17 runs in a 50-site audit). `crawl` + `extract` raises this risk.
- **What v2 does instead:**
  - page-kind rules per URL pattern;
  - URLs that match no rule are only crawled for links;
  - ownership and intent stages;
  - `no_match` for crawl-discovered pages whose required fields don't resolve;
  - `complete=false` with explicit statuses for caller-supplied pages.
- **Extension point.** One optional stage before the collectors, with outcome `wrong_page_type`.
