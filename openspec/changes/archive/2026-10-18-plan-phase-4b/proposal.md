# Plan phase 4b: role A at a fifth of the cost, and the executability class of every learned field

## Why

Role A (the `strong` config writer and repairer) runs now only for the required fields induction leaves (#285), but a
live learning run still cost about USD 1.9 of role A per host: each request carried up to 5 sample pages of 120,000
characters, and every repair round sent all of them again. A learned config also says nothing of what running it
takes: a field that reads a captured response needs a browser, and one an API call needs the recipe's request.

## What Changes

- Role A's requests use the provider's prompt cache: one system prompt for every round, the field definitions with the
  first sample page and then the other pages as cached prefixes, the repair rules and the failures in an uncached
  tail. A repair sends the first page only (a cache hit on the first request's prefix) in the first request's output
  schema. Page input is capped at 60,000 characters (`CRAWLERAI_LLM_A_MAX_CHARS`, down from 120,000, and no longer
  raisable).
- The LLM client reports and records cache read and write tokens; prices carry cache prices; the cost history prices
  them. `learn-sim --role-a live` reports the tokens (cache read and write included) and the cost.
- Each learned field has an executability class (`static-html`, `needs-browser`, `api-call`, `unexecutable`) from its
  steps; the config release check and `learn-sim` report them.

## Impact

- Capabilities: `learning-configs` (role A cost, executability classes), `llm` (prompt cache, usage, cost),
  `evaluation` (Learning simulation).
- Code: `config_ir/synthesis.py`, `config_ir/executability.py` (new), `config_ir/release_check.py`, `llm/client.py`,
  `llm/pricing.py`, `llm/providers/`, `services/llm_costs.py`, `eval/learn_sim.py`, `core/settings.py`; data:
  `data/llm/anthropic-pricing.json`; the API document and the clients generated from it (`ReleaseReport`).
