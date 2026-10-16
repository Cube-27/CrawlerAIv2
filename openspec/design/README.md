# Design rationale (the former ARCHITECTURE.md)

Status: architecture rev 25, 2026-10-16. Split into this folder by the OpenSpec conversion (D-1136), with every
section number kept. Code comments and history cite `ARCHITECTURE §N`; the table below says which file holds §N.

**Role.** These files hold the *why*: goals, the evidence behind the generalization contract, design rationale,
alternatives, the owner's decisions (Appendix A) and the candidates register (§22). The *what* (the current
behaviour, as requirements) is in [`../specs/`](../specs/); the binding generalization contract C1–C13 is in
[`../project.md`](../project.md). Agents read a design section only when a capability spec or change links it.

Changing a file here, or a requirement so that it contradicts a file here, needs owner approval (`CLAUDE.md` §4).
With approval, add a row to [revision-log.md](revision-log.md) and keep the capability specs consistent in the same
change. Numbers are starting points to confirm on the evaluation sets (§16), not commitments.

**Core and candidates.** The design covers only **core**: what is needed to produce the first honest measurement or
to meet an owner decision. Every other mechanism is a **candidate** (§22). A candidate is listed with the failure
class it would address and the evidence that would admit it, and gets no design until then (C13).

Evidence labels:
- **[verified]**: read in a primary source.
- **[self-reported]**: vendor or author claim.
- **[unverified]**: not checked.
- **[v1]**: observed in the CrawlerAI v1 repo at `08430ca5`.
- **[Invoro]**: observed in the Invoro repo at `e00501a`.

## Section index

| § | Section | File |
|---|---|---|
| 1 | Goals and non-goals | [overview.md](overview.md) |
| 2 | Generalization contract: 2.1 evidence, 2.3 unseen sites (2.2 rules: [project.md](../project.md#generalization-contract-c1c13)) | [generalization.md](generalization.md) |
| 3 | System context | [overview.md](overview.md) |
| 4 | Components | [overview.md](overview.md) |
| 5 | Schemas as data (5.1 field types – 5.5 page kind) | [schemas.md](schemas.md) |
| 6 | Data model | [data-model.md](data-model.md) |
| 7 | Acquisition (7.1 fetch, 7.2 API-backed pages) | [acquisition.md](acquisition.md) |
| 8 | Extraction (8.1 collectors – 8.6 listings and pagination) | [extraction.md](extraction.md) |
| 9 | Normalization by type | [normalization.md](normalization.md) |
| 10 | Resolution and confidence | [resolution.md](resolution.md) |
| 11 | LLM roles | [llm.md](llm.md) |
| 12 | Config IR and exporters (12.1 IR, 12.2 exporters, 12.3 release check) | [config-ir.md](config-ir.md) |
| 13 | API and MCP server (13.1 REST, 13.2 crawl frontier, 13.3 MCP) | [api.md](api.md) |
| 14 | Recurring crawls | [recurring-and-storage.md](recurring-and-storage.md) |
| 15 | Storage and replay | [recurring-and-storage.md](recurring-and-storage.md) |
| 16 | Evaluation (16.1 splits – 16.4 harness and gate) | [evaluation.md](evaluation.md) |
| 17 | Observability | [operations.md](operations.md) |
| 18 | Security | [operations.md](operations.md) |
| 19 | Tech stack | [operations.md](operations.md) |
| 20 | Prior versions | [generalization.md](generalization.md) |
| 21 | Build order (core only), milestone M | [build-order.md](build-order.md) |
| 22 | Candidates register | [build-order.md](build-order.md) |
| 23 | Deferred: page-type gate | [build-order.md](build-order.md) |
| App. A | Owner decisions (#1–#46) | [owner-decisions.md](owner-decisions.md) |
| App. B | User requirements | [appendices.md](appendices.md) |
| App. C | Evidence base | [appendices.md](appendices.md) |
| — | Revision log (rev 1–25) | [revision-log.md](revision-log.md) |

Other references that code and history use:
- `SPEC-NN §x`: the archived spec in [`../changes/archive/`](../changes/archive/README.md).
- `D-NNNN`: a decision entry; `grep -rn "### D-NNNN" openspec`.
- `INV-NN`: an invariant, kept as a requirement in its capability spec; `grep -rn "INV-NN" openspec/specs`.
- `OPEN_QUESTIONS #N`: [`../OPEN_QUESTIONS.md`](../OPEN_QUESTIONS.md).
- `DESIGN.md`, `ENGINEERING.md`, `RECURRING.md`: [`../conventions/`](../conventions/).
