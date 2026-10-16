# Recurring crawls; storage and replay

Design rationale, split from the former `docs/ARCHITECTURE.md` with its section numbers kept (code and history cite `ARCHITECTURE §N`). Index: [README.md](README.md).

## 14. Recurring crawls (Appendix A #13)

| Mechanism | Effect |
|---|---|
| Conditional GET (`ETag` / `Last-Modified`). A 304 means `unchanged`. | No download on unchanged pages. |
| Content fingerprint: SimHash-64 of visible text, with scripts, styles and nonces stripped. Only an equal fingerprint (Hamming 0) means unchanged; extraction is skipped. | Skips pages whose visible text did not change, ignoring nonces and whitespace. A one-token change, such as a new price, runs extraction (Appendix A #40). |
| Record fingerprint over normalized required fields. A change creates a new record `version` with `changed_fields`. | Change feed. |
| Listing diff. New URLs are queued; URLs missing for 2 runs get `gone_at`. | Catalog adds and removes. |

A recurring crawl is the caller re-submitting a job. A scheduler is not core. Config drift is handled in §8.3.
Adaptive scheduling and API delta fetches are candidates (§22).

---

## 15. Storage and replay

- **Captures.** One compressed bundle per capture (zstd): the response body, captured network JSON bodies, and a
  JSON sidecar (headers, method, timings, block class). Stored in S3-compatible object storage, or the local
  filesystem in development. Avoid self-hosted MinIO (AGPL).
- **Two stores.**
  - The main store holds production and dev captures.
  - A private root holds hidden and fresh captures and their recorded LLM responses. Only custodian credentials can
    read it (C1).
- **Retention.** Production captures expire after 30 days. Eval captures never expire.
- **Replay.** A pure function: `(capture, engine_version, config, schema) → record`. Live runs and replays
  share one code path. In eval replay, LLM responses are recorded and replayed, so CI needs no network.
- **Public repo.** The repo is public (Appendix A #26). Evaluation data, captures and secrets never enter it.
