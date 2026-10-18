# Design: plan phase 4b, role A cost and executability classes

Role A's request is the field definitions and the sample pages, which every repair round sends again. It is now built
for the provider's prompt cache: the system prompt and the output schema are the same in every round, and the parts
that repeat come first (`LLMRequest.cached`, each part ending a cache breakpoint), the repair rules and the failures
last. A config's fields are classed by the input their steps read (`config_ir/executability.py`), from the IR alone.

## Decisions

### D-1720 — A sample page's input is at most 60,000 characters in all
- Date: 2026-10-18 · Change/PR: plan-phase-4b (#287) · Status: decided (owner-delegated 2026-10-17)
- Decision: `CRAWLERAI_LLM_A_MAX_CHARS` defaults to 60,000 and refuses a larger value. It bounds a page's JSON key paths
  and reduced HTML together: the key paths are cut to at most half of it, and the HTML gets what they leave.
- Why: the cap is the cost bound the owner asked for; it must not be raisable by an operator or leave 20,000 more
  characters of key paths beside it.
- Reversible: yes

### D-1721 — Cache tokens are call metadata, priced by cache prices, not new usage resources
- Date: 2026-10-18 · Change/PR: plan-phase-4b (#287) · Status: decided (owner-delegated 2026-10-17)
- Decision: The reply, `AnsweredCall` and `LLMResponse` carry `cache_read_tokens` and `cache_write_tokens`
  (`tokens_in` stays the uncached input). The call's usage rows carry them in their metadata, and the call's prompt
  length (`metadata.tokens_in`) counts them. Price rows have optional `cache_read_usd_per_mtok` and
  `cache_write_usd_per_mtok`; the Anthropic file lists the 5-minute rates (0.1 and 1.25 times the input price), and cache
  tokens with no cache price are unpriced. The request hash includes `cached` only when it is non-empty, so recordings
  of other roles still replay.
- Why: no `usage_event` resource or migration for a number only costing needs; the cost history reads it from the
  input row's metadata.
- Reversible: yes

### D-1722 — One system prompt and one output schema for every round of role A
- Date: 2026-10-18 · Change/PR: plan-phase-4b (#287) · Status: decided (owner-delegated 2026-10-17)
- Decision: The repair rules move from the system prompt to the head of the repair request's uncached tail, and a
  repair asks in the first round's output schema (all first-round targets), naming in the tail the ones still wanted
  and asking an empty `steps` list for the others; the parser reads only the wanted ones.
- Why: a changed system prompt or output schema misses the cache, so a narrowed schema would make every repair pay for
  the whole prefix again.
- Reversible: yes

### D-1723 — A repair shows the first sample page only
- Date: 2026-10-18 · Change/PR: plan-phase-4b (#287) · Status: decided (owner-delegated 2026-10-17)
- Decision: A repair request is the first request's first cached part (field definitions and sample page 1, a cache
  hit) and a tail with the previous steps and every page's diagnostics, which say that pages not shown are covered.
  The steps are still verified on every sample page.
- Why: page 1 keeps the cached prefix; choosing the page that failed would change the prefix. The diagnostics carry
  `want` values for the other pages.
- Reversible: yes

### D-1724 — A step's class is the input its selector reads; a field takes its most demanding step
- Date: 2026-10-18 · Change/PR: plan-phase-4b (#287) · Status: decided (owner-delegated 2026-10-17)
- Decision: `static-html`: xpath, css, regex, attr, jsonld, and jsonpath over `jsonld` or `js_state` (the HTML Standard's
  inline scripts). `needs-browser`: jsonpath over `xhr`, the responses a browser captured. `api-call`: jsonpath over
  `api` when the config has an API recipe. Order from least to most demanding: static-html, needs-browser, api-call,
  unexecutable.
- Why: classes are a property of the IR, no run needed; the most demanding step says what the field may need, which is
  what a planner choosing a fetch method must know.
- Reversible: yes

### D-1725 — Unexecutable fields, and what is classed
- Date: 2026-10-18 · Change/PR: plan-phase-4b (#287) · Status: decided (owner-delegated 2026-10-17)
- Decision: A suspended field (no executor runs it) and an `api` source without an API recipe are `unexecutable`. The
  classes cover the config's fields (page fields, `listing:<name>` row fields and `listing:next`), not role C's
  published locators (`text:` spans), which are not config steps. The release report carries the class per field
  and the counts per class; the API document and the generated clients change with it.
- Why: the release check is the report of a config; a locator that is not a step is not executed by the config.
- Reversible: yes

### D-1726 — A live role A's cost in `learn-sim` is its tokens at the model's prices
- Date: 2026-10-18 · Change/PR: plan-phase-4b (#287) · Status: decided (owner-delegated 2026-10-17)
- Decision: With `--role-a live` the report adds the live hosts, uncached input, output, cache read and cache write
  tokens, and the cost at the prices (null when a call has none). Abstaining keeps the estimate from characters.
  The calls that answered before a failed host's failure are counted too.
- Why: the characters estimate cannot show what a cache saves.
- Reversible: yes
