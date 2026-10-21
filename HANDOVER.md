# Handover

The state of CrawlerAI v2 at handover (2026-10-21), after the last plan (`docs/agents/plan.md`) merged. The rules are
in `CLAUDE.md` and `openspec/project.md` (the contract C1–C13); current behaviour is in `openspec/specs/`; the
architecture as built is `openspec/design/architecture-v3.md`; the owner's rulings are
`openspec/design/owner-decisions.md`.

## What the system is

- A schema-driven extraction engine behind a REST API, an MCP server, a web playground and Python and TypeScript
  SDKs: scrape, batch, crawl, map, search and extract, with any schema (commerce and jobs are presets).
- HTTP first (curl_cffi with a browser TLS profile); a headless Patchright browser only when a page is blocked, is a
  challenge-free JavaScript shell, or the request asks for render (`render.mode`).
- Every published value is stated by the page, carries its evidence, confidence and locator, and is normalized by its
  field type's one normalizer. A value the engine is not sure of is left out or marked a conflict, never guessed.
- Structured data (JSON-LD, microdata, RDFa, Open Graph, inline state), documented platform data (the adapters in
  `backend/src/crawlerai/adapters/`) and the DOM are read first; the LLM fills only what they lack, and its values
  must be grounded verbatim in the page.
- Learned per-site configs (XPath, JSONPath, API recipes) run repeat crawls deterministically; they keep selectors and
  cookies, never values. Every record can be replayed from its stored capture.
- One Docker image with three roles (api, worker, scheduler); PostgreSQL is the store and the job queue.

## What it is not

- Not a proxy network or CAPTCHA solver: no proxies by default, no paid CAPTCHA service. Vendor bot blocks and rate
  limits end as `blocked`; an operator may configure proxy pools (`CRAWLERAI_PROXY_POOLS`) per request.
- Not a renderer of everything: a field lacking over HTTP does not trigger a render (owner #70); `render.mode` is the
  user's switch.
- Not an LLM fill-all: the LLM never invents a value, and its output is data, never code.
- Not tuned per site: generic code holds standards and structure only (C2, C3); site knowledge lives in adapters,
  configs and database rows.
- Not self-measuring: the repository holds no eval set, labels, scorer or calibration fitter (owner #79).

## Running it

Needs Docker, [uv](https://github.com/astral-sh/uv), [pnpm](https://github.com/pnpm/pnpm) and GNU make. From the repo
root:

| Command | What it does |
|---|---|
| `make dev` | Copies `.env.example` to `.env` if missing, starts Postgres, migrates, runs the API on :8000 (`GET /healthz`) |
| `make up` | Postgres and migrations, then the API, a worker, the scheduler and the frontend on :5173 in one terminal (`tools/dev_up.sh`); creates the UI key when unset |
| `make db` / `make db-down` | Start / stop Postgres only (`infra/docker-compose.yml`) |
| `make migrate` | `alembic upgrade head` (recreates a local database built from an older baseline), then `crawlerai schemas sync` |
| `make api-client` | Regenerate `frontend/openapi.json` and `frontend/src/api/schema.d.ts` (commit both) |
| `make sdk` | Regenerate the Python and TypeScript SDKs from `frontend/openapi.json` |
| `make check` | Every CI check locally; per job: `check-data`, `check-size-gates`, `check-complexity`, `check-theme`, `check-tools`, `check-backend`, `check-frontend`, `check-api-client`, `check-sdk`, `check-licenses` |
| `make verify-worker-queue` | Model-check the worker/queue concurrency with TLC |

The `crawlerai` CLI (in `backend/`, `uv run crawlerai ...`): `worker`, `scheduler`, `fetch` (one URL into a capture
bundle), `schemas sync`, `data fetch`, `apikey create --label <label>` / `apikey revoke`, `schedules list|pause|resume`,
`openapi`. The API never creates a key: make one with `apikey create` and send it as a bearer token.

Settings are environment variables, all listed with their meaning in `.env.example`; an empty value is unset. The
ones a run needs:

- `CRAWLERAI_DATABASE_URL` (matches `infra/docker-compose.yml`) and `CRAWLERAI_OBJECT_STORE` (`fs:///...` or
  `s3://...`; `make` uses `<repo>/.data/objects`).
- `CRAWLERAI_BROWSER_PROFILES`: the profiles directory, one Chromium profile per site across jobs and processes,
  holding that site's cookies (clearance cookies too) in plaintext. `make` uses `<repo>/.data/browser-profiles`;
  unset outside make, a profile lasts only while its browser is open. Keep it private to the service user; delete it
  to reset every profile (there is no retention job).
- `CRAWLERAI_COOKIE_KEY`: the Fernet key that encrypts the stored cookie state temporary profiles use.
- `CRAWLERAI_LLM_PROVIDERS` and `CRAWLERAI_LLM_API_KEY_ANTHROPIC` / `_GEMINI`; model ids per class are optional.
- `CRAWLERAI_UI_API_KEY` for the playground (`make up` sets it), `CRAWLERAI_API_KEY` for the MCP stdio server.
- `CRAWLERAI_EGRESS_COUNTRY`, `CRAWLERAI_PROXY_POOLS`, `CRAWLERAI_DISABLED_ADAPTERS`, `CRAWLERAI_IMPERSONATE`: optional.

robots.txt is off by default; a request opts in with `respect_robots: true` (owner #75). Browser tests need
`uv run patchright install --no-shell chromium` once.

## Running the e2e

The e2e run is the only measure (C1, `openspec/specs/evaluation/spec.md`). The eval set (243 pages at handover, one
page per site and page type) and its scorer live outside this repo, with the run reports; ask the owner for them.
Never commit them, their URLs, values or captures.

1. Final code, fresh database: `make db`, then `make migrate` on an empty database.
2. Start the API (`make api`, or `make dev`) and one worker (`cd backend && uv run crawlerai worker`), with the
   profiles directory set and an LLM key.
3. Send every page of the set through the API as a user would (`POST /v1/scrape` or `POST /v1/batch/scrape`, with
   the page's schema and `page_kind`, robots off, a `budget` with `llm_calls` stating the LLM call budget).
4. Pull the results, stop the API and the worker by PID, and score with the one scorer: per field `agree`,
   `disagree` or one side only; per page the outcome; listing rows by item URL (recall).
5. Adjudicate every disagreement and every one-sided value against the run's capture; a wrong expected value is
   corrected in the set. Compare page by page with the previous round outside the repo, classifying each regression
   (engine change, LLM variance, bot block, live drift).
6. A PR reports only the aggregate per field type, before and after (C10). A fresh batch (20–30 pages on new hosts)
   is scored once before any change is made on it; only that first score supports a generalization claim.

**Matcher caveat.** The scorer matches listing rows to the set by item URL. On listings whose items differ only by a
query parameter (query-keyed item URLs), a matcher that drops or reorders the query merges distinct items or misses
matches, so listing recall on such pages is read against the capture before it is counted.

### Final e2e (E2), on main after every plan PR

243/243 pages, 0 failed tasks, about 6 minutes and about $0.10 of LLM calls.

| Measure | Result |
|---|---|
| `commerce_detail` agree, the 194 earlier pages | 620 (previous round 638; −9 of the drop is one page bot-blocked in this run) |
| `commerce_detail` agree, the 49 newest pages | 322 (from 315) |
| `job_detail` agree | 156 |
| Listing recall, commerce / job | 81.1% / 90.5%; the drops are live drift (collections changed, postings closed) |

Fixed after E2: #424, a variant's own ids no longer override the sku and GTIN the page states, and variant rows
are restored.

## What is frozen

- `backend/data/calibration.json`, `backend/data/source_precedence.yaml` and `backend/data/drift_margins.json`, as
  fitted on 2026-10-18. No code in the repo refits them; a refit needs the owner. Confidence is `calibrated=true`
  only for the buckets `calibration.json` holds.
- The external vocabularies (CLDR, schema.org, IANA and the rest), pinned with sha256 in `backend/data/manifest.json`
  (`make check-data`).
- The contract C1–C13 and the evaluation procedure; changing either is the owner's call.

## Open owner decisions

Each is a working rule today; the owner may change it (`openspec/design/owner-decisions.md` records the answer).

- **Canonical link to a multi-seller listing.** The canonical link wins for the page URL (owner #77), also when it
  names a multi-seller listing page rather than the offer page.
- **Single-variant sku/GTIN.** On a single-variant page, the page's own sku/GTIN wins over the variant's (the
  variant-fill rule); the owner may prefer a conflict (unpublished).
- **Inline-state rating and count.** Admitted only when another source agrees (the documented admission rule).
- **Client-side review widgets.** Decided: they count as "render needed"; no engine change.
- **Role S label language tags.** Would change the public labels API; deferred.

## Open items (known, not fixed)

- A platform image list can hold other colourways' images. A fix by builder r2 was in flight at handover; check
  `git log` on `main` for it before relying on image lists from platform data.
- UI microcopy can become the description on pages whose only description candidate is widget text (pre-existing).
- On some pages the main image is a smaller rendition of the same file (the https-first rendition choice is kept).
- Availability is a conflict (unpublished) on pages where offers split after #421.
- A was-price struck only by an external stylesheet is not seen over HTTP (the HTML states no strike).

## Not done, and why

- JSON-LD `mainEntity` naming another product than the page's title: a one-site exception, no class rule.
- `url` derived from the final address when the page states none: owner #40 specifies it.
- Hub/SPA listings, card price ranges, variant-dependent prices, og lead text from entity-escaped JSON-LD, galleries
  whose names exist only in inline state: no bounded class fix found.
- Client-rendered product data over HTTP: owner #70, no render for a lacking field; `render.mode: locate` is the
  design.
- LLM run-to-run variance in span choice: accepted; the verbatim and grounding checks hold.
- Vendor bot blocks and 429s: out of scope (no proxies, no CAPTCHA).
- curl session pool per host: SSRF pinning makes pooling non-trivial; the gain is unmeasured.
- Browser profile pruning: the operator deletes the profiles directory; a retention job is deferred.
- `ng-cloak`/`v-cloak`/`x-cloak` content over HTTP: no change; the page stays `partial` with the render hint.
- The e2e scorer stays outside the repo with the eval set.

## Machine constraints

The development VM is small (8 GB, no swap, `/tmp` in RAM): at most two builders and one headless browser at once,
more than 2 GB free (`free -m`) before starting a builder, a browser or a local app, and `TMPDIR` on disk
(a scratch folder per agent). Never real Chrome; Patchright headless only. Stop every app you start by PID.

## Agent workflow

The code was built by Claude agents, each in its own herdr tab: one orchestrator
(`docs/agents/orchestrator.md`, started with `/crawlerai-orchestrator`) and at most two builders
(`docs/agents/builder-protocol.md`, whose hard rules override the rest). The orchestrator briefs builders, runs the
merge queue and the e2e runs; each builder takes one plan PR in its own worktree
(`tools/orchestrator/new_worktree.sh <id> change/<id>`) to green CI, every review thread resolved
(`tools/orchestrator/unresolved.sh <n>` prints 0), and reports `READY TO MERGE #<n> <sha>`. The last plan and its
status are in `docs/agents/plan.md`; a new plan replaces it.
