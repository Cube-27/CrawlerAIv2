# Design: normalizer, schema and worker cleanups

## Decisions

### D-1370 — Money reads its number through `numbers.stated`
- Date: 2026-10-17 · Change/PR: normalize-schemas-cleanup (#255) · Status: decided (owner-delegated 2026-10-17)
- Decision: `numbers.Stated` also holds the text after the number and the whole NFKC text; money's text reader takes
  them from it and maps `no_number` to `no_amount` and `several_numbers` to `range`. Money's own copy of the
  surrogate, NFKC and one-run steps is gone.
- Alternatives: leave the copy; give money its own reason names in `numbers`.
- Why: count, number and money read a written number one way (C8); the reasons money reports keep their names.
- Reversible: yes

### D-1371 — Intervals and zone names written as text
- Date: 2026-10-17 · Change/PR: normalize-schemas-cleanup (#255) · Status: decided (owner-delegated 2026-10-17)
- Decision: a monetary range's period is read from `unitText`, else `unitCode`, in these forms only: a schema.org unit
  word, a count of one and a unit word (`1 YEAR`, ISO 80000-1), an ISO 8601-1 duration of exactly one unit (`P1Y`,
  `PT1H`), a UN/CEFACT Recommendation 20 code (`ANN`, `MON`, `WEE`, `DAY`, `HUR`), or a `type:period` phrase of the
  page's languages. Any other count (`2 YEAR`, `P1Y6M`) names no period. The date normalizer reads `UTC` and `GMT`
  after the time, with or without a space, as zero offset; no other abbreviation names one.
- Alternatives: read every duration as a period (`P6M`, "every 2 weeks" are not salary periods); accept any zone
  abbreviation (one abbreviation names several offsets).
- Why: each form is a published standard's; a period is one unit, and a decline is the safe reading of the rest (C7).
- Reversible: yes

### D-1372 — `remote_flag` is `true` or `null`
- Date: 2026-10-17 · Change/PR: normalize-schemas-cleanup (#255) · Status: decided (owner-delegated 2026-10-17)
- Decision: a location's `remote_flag` is `true` when `TELECOMMUTE` or a `type:remote` clause states it, else `null`;
  the normalizer never writes `false`, since no standard states "not remote" as a flag. `equal` is unchanged: the flags
  must be equal, so a stated remote location and an unstated one do not agree. A stored `false` stays a legal input.
- Alternatives: treat `null` as missing in `equal` (a remote and an unstated place would then agree).
- Why: "not stated" and "not remote" must not read alike (#240); the smallest change to the value shape (greenfield).
- Reversible: yes

### D-1373 — ISO 3166-1 exceptional reservations are not country codes
- Date: 2026-10-17 · Change/PR: normalize-schemas-cleanup (#255) · Status: decided (owner-delegated 2026-10-17)
- Decision: `iso_3166_alpha2` excludes AC, CP, CQ, DG, EA, EU, EZ, FX, IC, SU, TA, UK and UN, which ISO 3166-1
  reserves at a body's request, beside the user-assigned ranges it already excludes.
- Alternatives: read the CLDR validity data (Babel does not ship it).
- Why: the standard lists them; CLDR names regions by several of them (EU, EZ, UN, ...).
- Reversible: yes

### D-1374 — Schema references are checked where the vocabulary is loaded
- Date: 2026-10-17 · Change/PR: normalize-schemas-cleanup (#255) · Status: decided (owner-delegated 2026-10-17)
- Decision: `services.schemas` (create, inline, edit) refuses a `schema_org` path whose root is not a schema.org type or
  whose step or `+` join is not a property, and a `schema:` reference that is not an enumeration, against the pinned
  vocabulary (`collect.schema_org_map.reference_errors`, errors at `fields.<name>.schema_org` and `.vocab`). A process
  without the vocabulary file checks syntax only, as it extracts no records. `type:` references are not checked: the
  enum normalizer declines on an unknown one (`unknown_vocab`). The presets are checked by a test against the file.
- Alternatives: check inside `SchemaDocument` (every test document would need the fetched file); thread the vocabulary
  through every caller; refuse every schema write without the file.
- Why: the check lives where the vocabulary and the services are (above `schemas` in the layering); it supersedes D-0240.
- Reversible: yes

### D-1375 — `SchemaRef` carries the schema document's digest
- Date: 2026-10-17 · Change/PR: normalize-schemas-cleanup (#255) · Status: decided (owner-delegated 2026-10-17)
- Decision: `SchemaRef` is `{name, digest}`, the digest `document_digest` of the schema when the config was learned. An
  activation or an operator correction of a config whose digest is not the stored document's is refused
  (`ConfigMismatch`; the correction endpoint answers 409). The engine executor does not check it (a job's pinned config
  runs with the document it was pinned with).
- Alternatives: check on every page in the executor (a hash per page); a schema version column.
- Why: a schema is edited in place (D-0950), so only the document says what a config was learned for.
- Reversible: yes

### D-1376 — `fetch_failed` is dropped; page handlers require their LLM client
- Date: 2026-10-17 · Change/PR: normalize-schemas-cleanup (#255) · Status: decided (owner-delegated 2026-10-17)
- Decision: no `fetch_failed` problem type: fetch errors are task and record outcomes, and the live REST spec lists the
  types in `api/problems.py`, which never had it. The page handlers (`scrape_handler`, `crawl_handler`, `fetch_page`,
  `extract_records`) take `llm: LLMClient`, not `None`; a worker without a provider passes `NO_LLM`.
- Alternatives: raise `fetch_failed` for a request-level fetch failure.
- Why: nothing raises it; production already passes a client, so `None` was only a test shortcut.
- Reversible: yes

### D-1377 — INV-28 does not pin LLM settings
- Date: 2026-10-17 · Change/PR: normalize-schemas-cleanup (#255) · Status: decided (owner-delegated 2026-10-17)
- Decision: INV-28 is amended: a job pins its schema, config versions, calibration and precedence. LLM providers, model
  ids and the role A character cap are the worker process's settings; each usage row records the provider and model of
  its call, and the job's `llm_calls` budget is part of its request.
- Alternatives: pin the model ids in `JobPins` and build a per-job client.
- Why: a pinned model id that a provider retires would fail every later call of a long job, and keys and failover order
  are deployment state; the usage rows already show what ran.
- Reversible: yes

### D-1378 — One first backoff and one transient-status rule, in `core`
- Date: 2026-10-17 · Change/PR: normalize-schemas-cleanup (#255) · Status: decided (owner-delegated 2026-10-17)
- Decision: `core/retry.py` holds `FIRST_BACKOFF` (30 s, SPEC-02 §4.6; the queue's `BACKOFF_BASE` and politeness's
  `BACKOFF_MIN` become it) and `is_transient` (408, 429, 5xx: RFC 9110, RFC 6585), used by the LLM providers and the
  Shopify adapter. The Shopify adapter now also treats 408 as transient.
- Alternatives: put both in `acquire/politeness`, as the follow-up said: `db` sits below `acquire` in the layering and
  cannot import it.
- Why: C8, and the layering contract.
- Reversible: yes

### D-1379 — Identity and intent are their own capability
- Date: 2026-10-17 · Change/PR: normalize-schemas-cleanup (#255) · Status: decided (owner-delegated 2026-10-17)
- Decision: `specs/identity-and-intent/spec.md` holds entity identity, intent, ownership and the entity key; `resolution`
  keeps a short "Candidate validity" requirement for the normalizer gate, and falls under ~100 lines.
- Alternatives: split off preference and evidence instead.
- Why: the requirement mixed three concerns; identity and intent are the part other capabilities cite by name.
- Reversible: yes
