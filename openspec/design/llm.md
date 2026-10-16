# LLM roles

Design rationale, split from the former `docs/ARCHITECTURE.md` with its section numbers kept (code and history cite `ARCHITECTURE §N`). Index: [README.md](README.md).

## 11. LLM roles

Every call uses JSON-schema constrained output, has a per-job budget, and is recorded in `usage_event` with a
`prompt_kind`. **Grounding** applies to role C, the only role that outputs values: each value must be a verbatim
substring of the page, with offsets. Roles A, D and S output selectors, request specs and schemas, which are
accepted only through validation by execution (§8.3, §7.2) or by the caller (§5.4).

| Role | When | Output | Model class |
|---|---|---|---|
| **C. Grounded extraction** | Cold-mode gaps (§8.4) | Field values with char offsets from cleaned page text. Ungrounded or type-invalid values are dropped. | Haiku / Flash-Lite-class (≈ $0.0006/page **[verified prices, 2026-10-08]**) |
| **A. Selector synthesis** | §8.3 step 2 | Selector or JSONPath map, never values. ≤ 3 repair rounds. | Sonnet-class (≈ $0.17–0.33/site) |
| **D. API-recipe binding** | §7.2, when templating is ambiguous | A typed request spec, never code | Sonnet-class |
| **S. Schema drafting** | Prompt-only extract; field names (§5.4) | A draft schema | Sonnet-class |

**Why per-page LLM output is not the path for repeat sites:**
- values can be wrong inside valid JSON (83% best value accuracy across 21 models **[verified abstract]**);
- results vary between runs even at temperature 0 **[verified]**;
- there is no exportable config.

Generated selectors came within 1.6 points of per-page extraction with 96% fewer calls **[verified, Brosch et
al.]**. So role C is used only while a site is cold.

**Controls:** flat, cleaned inputs (never raw HTML); acceptance by re-execution; no `exec` of generated code. Page
content is untrusted input to every role.

Candidate roles (adjudication, independent verifier, self-consistency) are in §22.
