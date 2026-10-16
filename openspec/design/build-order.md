# Build order, candidates register, page-type gate

Design rationale, split from the former `docs/ARCHITECTURE.md` with its section numbers kept (code and history cite `ARCHITECTURE §N`). Index: [README.md](README.md).

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

---

## 22. Candidates register

These are not designed and not built. Each is admitted (C13) only when the stated evidence appears, and its effect
is measured after it is added.

| Candidate | Would address | Admitted when |
|---|---|---|
| **Learned, calibrated ranker** (gradient boosting, Platt/isotonic, conformal routing) | Wrong choices among valid, disagreeing candidates | Precedence or `conflict` decisions cause a material share of hidden errors or lost coverage. |
| **LLM adjudication** among conflicting candidates | `conflict` abstentions on resolvable cases | The `conflict` rate on hidden required fields is material, and labels show one candidate was right. |
| **Independent verifier** for configs | Wrong selectors that validate against themselves | Hidden precision of `uncorroborated` config fields is below τ, and they are a material share of fields. |
| **Self-consistency sampling** for role C | LLM value errors | Hidden precision of the `llm_grounded` bucket is below τ. |
| **Generic structural DOM collectors** (repeated structure, label–value pairs, typed value spotting) | Cold-mode cost or coverage on DOM-only sites | Role C cost or coverage on DOM-only fresh sites misses target, and dev shows the collector would help. **Label–value pairs and the main image admitted 2026-10-16** by the owner from the reference eval (Appendix A #42); repeated structure and typed value spotting are not. |
| **More platform adapters** (Workday CXS, iCIMS, ADP, Oracle CX; Shopify admitted, Appendix A #46) | Coverage or cost on those platforms | Results for the platform fall short through the generic path, or volume justifies it (OPEN_QUESTIONS #2). |
| **Variant-matrix handling** | Per-variant price and availability; the multiple-Offer `conflict` | **Admitted 2026-10-15** by the owner ahead of labels (Appendix A #37); designed in SPEC-13. |
| **Anti-bot measures**: allowlisting program, cookie handoff, vendor strategies, real Chrome with a behaviour layer (Appendix A #20 owner note: no Patchright on real Chrome), residential proxies, unblockers, CAPTCHA handling, detection bench | Blocked pages | The `blocked` or `shell` outcome rate for a category is material. The cheapest measure that fixes the blocked class is admitted first. |
| **Recurring schedule storage** | Callers having to re-submit | Recurring volume makes re-submission a burden. |
| **Review queue UI** beyond labeling and config correction | Operator throughput | Operators correct configs often enough that the API and config view slow them down. |
| **Adaptive recrawl schedule; API delta fetches** | Recurring cost | Recurring volume makes fetch cost material. |
| **GMC feed and job XML exporters** | Feed delivery | A user asks (OPEN_QUESTIONS #4). |
| **Site health dashboard, alerts** | Operations | Production use starts. |
| **WARC capture format** | Interoperability with archive tools | Someone needs pywb or WARC output. |
| **Web search; browser actions; authenticated crawls** | Scope | The owner decides (Appendix A #21). |

---

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
