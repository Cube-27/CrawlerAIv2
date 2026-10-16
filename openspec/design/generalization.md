# Generalization: evidence and prior versions

Design rationale, split from the former `docs/ARCHITECTURE.md` with its section numbers kept (code and history cite `ARCHITECTURE §N`). Index: [README.md](README.md).

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

The rules C1–C13 are binding and are kept verbatim in [../project.md](../project.md#generalization-contract-c1c13).

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
