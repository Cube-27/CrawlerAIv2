# Owner decisions

The owner's decisions (ARCHITECTURE Appendix A), current and numbered. A new owner decision is appended here with its
date, in the PR that applies it to the capability specs (`CLAUDE.md` §6). Agent decisions go in the decision logs
(`../decisions/README.md`), not here. #1–#46 are verbatim from ARCHITECTURE rev 25, where §N references point
([archived](../changes/archive/2026-10-16-architecture-rev25/ARCHITECTURE.md)).

Original decisions are dated 2026-10-08. Later amendments override them.

| # | Topic | Decision |
|---|---|---|
| 1 | Users | Data users (records/CSV) and config users (XPath/regex + params for an existing crawler platform, plus code hints). |
| 2 | Hosting and cost | No billing, invoicing or multi-tenant auth. Usage stays visible. |
| 3 | Scale | ~5k–10k pages/day, mostly the same sites with different URLs. |
| 4 | API-backed sites | Pages backed by XHR/JSON APIs are a first-class path. |
| 5 | Listing vs detail | The user decides; no automatic page-type routing. |
| 6 | Candidate resolution | The most critical area (§10). |
| 7 | Schema | Schemas are data; commerce and jobs are presets. |
| 8 | LLM role | "Never on the main path" is not a constraint; choose on accuracy and cost. |
| 9 | LLM cost | No abstract cap; usage stays visible. |
| 10 | Page-type gate | Out of scope. |
| 11 | Target sites | Mostly customer-owned sites (allowlisting possible); some competitor sites. |
| 12 | Fetching | HTTP first; browser only on evidence. |
| 13 | Recurring crawls | Change detection from day one. |
| 14 | Raw capture | Compressed captures for replay: 30 days in production, forever for eval. |
| 15 | Scope | An MCP server and a public API are required. Enrichment, intelligence and knowledge graphs are not. |
| 16 | Language | Python backend, TypeScript frontend. |
| 17 | Jobs | ATS adapters first, HTML second. |
| 18 | Location | GitHub `Cube-27/CrawlerAIv2`. |
| 19 | Fallback use | Internal use or open source. |
| 20 | Browser | **Patchright headless** is the browser; the owner tested it and it works. Owner notes for any future anti-bot candidate: Patchright makes real Chrome worse; real Chrome needs human-like behaviour, not Patchright. Camoufox was rejected. |
| 21 | API and MCP | Scrape, map, crawl, and extract with a schema or prompt. Our own API shapes. No web search, no browser actions. |
| 22 | Generalization | The target is clean, normalized data from any site, for any schema; §2 is binding. |
| 23 | Ad-hoc extraction | Progressive mode (§8.4). |
| 24 | Codebase | Build from scratch. No porting from v1, including acquisition. |
| 25 | Scope discipline | Acquisition is not the main concern. Only core is designed; everything else is a candidate admitted by evidence (C13). |
| 26 | License and visibility (2026-10-12) | The repo is **public**, licensed **AGPL-3.0**. Documents name no customer or prospective buyer and contain no business terms. |
| 27 | Frontend (2026-10-12) | Vite + React + TypeScript + HeroUI (open source, React Aria based). |
| 28 | Autonomous implementation (2026-10-12) | Implementation runs through orchestrated coding agents with minimal owner involvement. Agents record their decisions in `DECISIONS.md` and state in `plans/ACTIVE.md`. Changes to this document are escalated to the owner. |
| 29 | Labeling deferred (2026-10-12) | No labeled sets before the crawler works. L0–L4 are accepted on functional criteria; measurement is milestone M (§21), started by the owner from reviewing crawler output. Hidden and fresh are later drawn only from sites development never touched. |
| 30 | Hidden/fresh privacy answers (2026-10-13) | Hidden and fresh aggregates use complementary suppression as well as the 10-field minimum cell (§16.3). Hidden and fresh pages are labeled only through an instance of the app on the custodian machine with a private backend, never deployed. |
| 31 | Parse once (2026-10-13) | A capture body is parsed at most once per parser per pipeline run; every consumer reads one shared `ParsedPage` (§8). The release executor is the only exception. |
| 32 | Operational invariants (2026-10-13) | No layer after resolution changes a published value; a job pins its settings at submit; cookies stay inside one fetch; untrusted bodies are bounded; one task's failure never fails another; forwarded headers only from trusted proxies and no API keys created at startup (INV-27–INV-32). |
| 33 | Complexity and file length (2026-10-13) | Cognitive complexity of at most 15 per function is a hard check in CI and `make check`, for backend, tools and frontend code. 800 lines per file is a soft limit: CI warns, never fails, and a file past it is split by meaning, not to meet the number. Coverage gates and ratchets stay forbidden (C11). |
| 34 | Embedded-state admission (2026-10-14) | A visible `js_state` or `xhr` value with no other candidate to equal is admitted only for field types with a checkable syntax (§8.1); opaque types such as text and sku admit by equality only. Accuracy Q2, option (a). |
| 35 | `brand` optional (2026-10-14) | "Brand is not that important": preset `commerce_detail` version 2 makes `brand` optional (§5.3). A page without a brand is complete, and the gap rule no longer asks role C for it. |
| 36 | Variants are members (2026-10-15) | A primary entity's `hasVariant` variants are members of it, not candidates for the target, and their Offers are the target's under the atomic-offer rule (§8.2 rule 3, §10). Step A of the variants proposal; variant-matrix handling itself (§22) is admitted separately and specified in SPEC-13. |
| 37 | Variant matrix (2026-10-15) | Variant-matrix handling (§22) is admitted now, ahead of labels. `commerce_detail` version 3 adds an optional `variants` list from structured data; sub-fields of a `list` of `object` map by their own `schema_org` paths; the single price, availability, sku and gtin publish only when every variant agrees (amended 2026-10-16, #44: no URL-named default variant). No platform JSON adapter (superseded for Shopify by #46). Variant labels and their scoring are specified, not built (SPEC-13). |
| 38 | Playground UI (2026-10-15) | The UI is one playground: a mode switch (Scrape, Batch, Crawl, Map, Extract), a command bar with the primary action at the top, settings in an inline options panel with Advanced collapsed, and output on the same page. No pop-up windows for runs. Clean JSON is the main output: schema fields only, metadata only when asked for. Batch and crawl show a running table with each page's JSON in a side drawer, and plain-language live activity. The UI never asks for an API key; the server that serves it attaches one (§18). `/` opens the playground. SPEC-14. |
| 39 | Availability and stock quantity (2026-10-16) | Availability and stock quantity are separate fields. Availability stated in words or codes ("in stock", "instock", "In stock (5 available)") normalizes to the schema.org `ItemAvailability` member, the one availability convention in the repo; the stock quantity is its own `count` field (5). `commerce_detail` version 4 adds the optional `stock_quantity`; variants carry availability and stock quantity when the page states them per variant, otherwise the page's values publish. D-0782. |
| 40 | Derived page URL; unchanged pages (2026-10-16) | A detail page's `url` derived from the canonical link or the final URL publishes with source kind `derived`, a `derived:` locator and its own `derived` evidence bucket, calibrated like any other (§6, §8.1, §10). INV-22 holds as written. D-0355, option (a). Only an equal content fingerprint (Hamming 0) means a page is unchanged (§14); D-0665, option (b). An opt-in `csv_safe=true` results parameter quotes formula-like CSV cells, and the UI's Export CSV sends it; default output is unchanged (§12.2). D-0879, option (a). |
| 41 | Additional fields (2026-10-16) | Field names typed in the UI become a `fields` request member on every run type (scrape, batch, crawl, extract). The server drafts a typed schema from the names with role S, for the request's page kind; the UI shows the draft for editing before the run (D-0810, option a). |
| 42 | Reference-eval coverage (2026-10-16) | Label–value pairs and the main image, from the §22 structural DOM candidate, are admitted: source kind `dom`, a `dom:` locator and a `dom` evidence bucket (§6, §8.1, §10). `commerce_detail` gains optional schema.org-mapped fields the page states, edited in place, and a `number` field type for `rating` (§5.1, §5.3, §9). Extract, never enrich. D-0955–D-0957. |
| 43 | Greenfield: no versioning; extract, not enrich (2026-10-16) | "Nobody asked for [schema versioning] and there are no users"; "migration and versioning all should be greenfield always for now; if there is a use case we will implement later." One schema per name, edited in place; an edit sends its learned configs back to learning (§5.2). One baseline migration; the database is recreated, never migrated with data steps. Record versions, draft and active configs and `engine_version` stay: they are features. GeoNames is dropped: "our job is to extract page data, not change it"; a location publishes what the page states (§9). |
| 44 | Owner answers (2026-10-16) | **Variants:** "no default — all variant schema goes into variants and common schema stays out of variants, simple." A multi-variant product's values that vary (price, availability, stock quantity, sku, gtin, variant attributes) publish only in `variants` rows; a top-level field publishes only a value every variant shares. No variant the page URL names is selected (§10; D-0945). **Job location:** "just display whatever is written in jobs location." The location text publishes as written, whitespace collapsed, with no macro-region parsing or "or" split; structured parts only where the page states them structurally (§9; D-0946 class 11). **Provider refusal:** a provider's refusal of a request has its own reason and problem type, `llm_refused` (502), distinct from `llm_unavailable` (D-1009, option a). |
| 45 | Playground options popover (2026-10-16) | Owner, after #214: the playground's settings open from the command bar's Options button in a popover, with every setting shown at once in a compact grid and no nested Advanced section; the command bar sits centred under a centred mode switch. This replaces #38's "inline options panel with Advanced collapsed"; the rest of #38 stands. Opening the popover moves nothing on the page. SPEC-14 §4.2. |
| 46 | Shopify adapter (2026-10-16) | The Shopify platform adapter is admitted from §22 "More platform adapters". It reads storefront product and collection pages through the documented Storefront API (tokenless, MoneyV2 prices with their currency), confirms the platform by the documented `X-Shopify-API-Version` response header, and maps the answer to schema.org shapes, so variants give rows under the variant rules (#44). Every adapter's unserved page falls back to the page rungs. Adapters are off until `CRAWLERAI_ADAPTERS` names them. SPEC-15. |
