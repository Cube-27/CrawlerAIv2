# Tasks

## 1. Normalizers

- [x] 1.1 `normalize/range.py`: a monetary range's period is read from `unitText`, else `unitCode`: a unit word, an
      interval of one unit (`1 YEAR`), an ISO 8601 duration of one unit, a UN/CEFACT code, or a `type:period` phrase. (#255)
- [x] 1.2 `normalize/date.py`: an RFC 3339 datetime with a space and a zone name `UTC` or `GMT` is zero offset. (#255)
- [x] 1.3 `normalize/money.py` reads its amount through `numbers.stated`, mapping its reason codes. (#255)
- [x] 1.4 `normalize/location.py`: `iso_3166_alpha2` excludes the exceptional reservations; `remote_flag` is `true` or
      `null`. (#255)

## 2. Schemas and configs

- [x] 2.1 A created or edited schema's `schema_org` paths and `schema:` references are checked against the pinned
      vocabulary; the presets are tested against it. (#255)
- [x] 2.2 `SchemaRef.digest`: set at learning; activation and operator corrections refuse a config learned for an
      earlier document. (#255)

## 3. API, worker, jobs

- [x] 3.1 Drop `fetch_failed`; the LLM setup docstring names `llm_unavailable` and `llm_refused`. (#255)
- [x] 3.2 The page handlers require `llm`; tests pass `NO_LLM`. (#255)
- [x] 3.3 INV-28 amended (LLM settings are deployment settings, recorded per call). (#255)
- [x] 3.4 `core/retry.py`: one first backoff and one transient-status rule. (#255)

## 4. Specs

- [x] 4.1 Split `specs/resolution/spec.md`: identity and intent into `specs/identity-and-intent/spec.md`; update the
      capability table. (#255)
- [x] 4.2 Apply the deltas to `openspec/specs/` and archive this change. (#255)
