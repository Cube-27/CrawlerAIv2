# Observability, security, tech stack

Design rationale, split from the former `docs/ARCHITECTURE.md` with its section numbers kept (code and history cite `ARCHITECTURE §N`). Index: [README.md](README.md).

## 17. Observability

- **Usage counters** per job; per-job budgets stop runaway jobs. LLM usage is also shown with an estimated cost
  (§1): tokens priced from versioned price data, unknown where no price applies (C7).
- **Run events** per job (fetch outcomes, mode, LLM calls, abstentions, task failures with their reason, drift
  suspensions) are stored in Postgres and streamed over SSE.
- **Metrics** (OpenTelemetry): pages/min, fetch outcome mix, mode mix, abstain rate, queue depth.

---

## 18. Security

- **Access.** API keys: hashed, revocable, rate limited before any DB lookup. The web UI never asks for a key: whatever serves
  it (today the dev proxy) attaches the bearer key from its own environment (`CRAWLERAI_UI_API_KEY`), so the key never
  reaches the browser. Anyone who can reach the UI can use the API through it, so the UI is served on localhost or a
  private network only (Appendix A #38). No cookies, no sessions, no CSRF surface.
- **SSRF** (§7.1): fails closed and is re-checked on every redirect hop.
- **Secrets** come from environment or a secret store, never the repo, and are redacted in logs.
- **Generated artifacts are data.** Selectors, recipes and schemas run in our interpreter. We never `exec` LLM
  output.
- **MCP.** Page content is untrusted, and prompt injection is expected (§13.3).
- **Supply chain.** Lockfiles, an SBOM, and a dependency license scan denying AGPL, GPL, SSPL and non-commercial
  licenses. The project itself is AGPL-3.0. Keeping dependencies permissive preserves the owner's option to
  license it differently later (Appendix A #26).

---

## 19. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.12, TypeScript | Appendix A #16 |
| API / MCP | FastAPI + pydantic v2; official MCP Python SDK | — |
| DB / queue | PostgreSQL 16; a thin `FOR UPDATE SKIP LOCKED` loop | 10k pages/day ≈ 0.1 tasks/s |
| HTTP | `curl_cffi` **[verified: MIT]**; `httpx` | — |
| Browser | Patchright **[verified: Apache-2.0]**, headless | Owner-tested |
| HTML | `selectolax` **[verified: MIT]**; `lxml` (BSD) for XPath 1.0 | lxml matches PHP DOMXPath |
| Normalization | Babel / CLDR (BSD-3), `price-parser` (BSD-3), `dateparser` (BSD-3), `trafilatura` **[verified: Apache-2.0]** | Standards over lists (C4) |
| LLM | Provider-agnostic thin client with JSON-schema outputs | Two providers (OPEN_QUESTIONS #5) |
| Frontend | Vite + React + TypeScript + **HeroUI** (built on React Aria) | Appendix A #27; version in SPEC-00 |
| Tests | pytest, Hypothesis (test-only), import-linter; Vitest | C8, C9 |
| Deploy | Docker, one image with three roles; Postgres; object storage | — |

Tooling details (package managers, linters, type checker, migrations) are in SPEC-00, and the choices are recorded
in `DECISIONS.md`.

**Rejected as the engine:**
- Scrapy (lock-in);
- Crawl4AI / ScrapeGraphAI (would own our pipeline);
- Stagehand (per-page LLM extraction);
- Zyte / Diffbot extraction (closed, per-page, no exportable config);
- pretrained DOM transformers (GPU, no calibration).

Also excluded by license: nodriver and zendriver (AGPL **[verified]**), selenium-driverless (non-commercial),
MinIO (AGPL).
