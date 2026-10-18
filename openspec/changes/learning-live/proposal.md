# Change: learning, live

## Why

Per-site learning (induction, role A synthesis, role D, held-out validation, activation, progressive mode, drift) was
code-complete but had never run against an LLM. Run end to end through the API and the worker on dev hosts (commerce
and jobs, detail and listing pages), it failed for whole classes of pages: a listing whose engine rows come from role C
never validated, because role C leaves items out and validation required equal row counts; a description written as
markup in JSON-LD could not be reproduced by any step; role A wrote JSONPath forms the IR accepted and no executor ran.

## What Changes

- Held-out validation and the release check align the engine's listing rows with the config's rows as an
  order-preserving subsequence, so the rows role C did publish are checked and an engine row the config does not find
  still fails the field.
- A `jsonld` or `jsonpath` step's value is read as the structured collectors read it (a text field reads markup as its
  rendered text), in both executors; the release executor gets that read from the caller, as it gets the normalizers.
- The IR accepts JSONPath only in the RFC 9535 subset the engine reads, and role A's prompt states that form.
- A browser tab reads the data responses counted when a read starts (a response arriving meanwhile raised `KeyError`
  in the recipe learner's renders).
- Measured live: LLM calls and cost per learned site, pages until a site served from its config, and config mode
  against cold mode on the hosts' dev pages.

## Impact

- Capabilities: [learning-configs](../../specs/learning-configs/spec.md).
- Code: `backend/src/crawlerai/config_ir/` (`validation.py`, `release_check.py`, new `row_alignment.py`, `executor.py`,
  `release_executor.py`, `release_rules.py`, `model.py`), `backend/src/crawlerai/collect/schema_org_map.py`,
  `backend/src/crawlerai/llm/prompts/a_synth.txt`, `backend/src/crawlerai/acquire/browser_tab.py`.
- Role A's `request_hash` changes with its prompt: recorded role A replies are re-recorded on the next run.
- Cold extraction is unchanged (dev eval before and after are equal on every field type).
