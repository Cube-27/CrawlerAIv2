# Tasks

## 1. Role A cost

- [x] 1.1 Prompt caching: `LLMRequest.cached` parts, cache breakpoints in the Anthropic provider, cache tokens in the
      reply, the call record, the usage metadata, prices and the cost history. (#287)
- [x] 1.2 Role A sends one system prompt, caches the field definitions and pages, and repairs with the first page in
      the first round's output schema; page input capped at 60,000 characters. (#287)
- [x] 1.3 `learn-sim` reports a live role A's tokens, cache tokens and cost. (#287)

## 2. Executability classes

- [x] 2.1 Classify each field and locator of a config by how it executes (`config_ir/executability.py`) and report
      the classes in the config release check and in `learn-sim`. (#287)
