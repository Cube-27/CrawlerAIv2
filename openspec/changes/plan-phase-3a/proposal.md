# Plan phase 3a: role C on detail pages asks every missing field and claims links and images

## Why

On the golden set's detail pages, `apply_url` publishes on every job page at precision 0.24: where a posting states
no apply link, the engine publishes the page's own URL (the page-URL derivation reaching `apply_url` through its
`>JobPosting.url` rank), or the posting's own `url`. Role C cannot help: it reads text only, so it can claim no link's
target, and it is asked only when a required field is missing, so optional detail fields (color, product_id,
review_count) that the page shows but no collector reads stay missing (coverage 0.33, 0.11, 0.38 without an LLM).

## What Changes

- **Asked fields**: on a detail page role C is asked for every missing field, optional ones included, in the same one
  call within the job's budget (supersedes the required-only gate). A listing's page-field call keeps its gate.
- **Links and images**: the cleaned text role C reads marks each shown link to another resource with an id after its
  text (`[L3]`, or `[L3: name]` with the name it announces) and each shown image with an id (`[I2: alt]`), for the
  kinds the asked fields take (url: links, image_url: images). A claim may name an id instead of a span; it is grounded
  against the DOM (INV-12 extended): the element must exist on the page and be of the field's kind, and its value is
  the element's `href` or `src` as the page states it, never model text.
- **Deleted**: the page-URL derivation for a field with an alternative other than `T.url` (`apply_url`), and the
  `>JobPosting.url` rank of `job_detail.apply_url`; `apply_url` comes from a stated apply link (structured data,
  adapters) or a grounded role C link claim, otherwise it is absent. Their code, tests and spec text go.

## Impact

- Specs: llm ("Grounded values (INV-12)", "Role C input, claims and candidates", "When role C is asked"), extraction
  ("Cleaned text and visibility index"), resolution ("Derived values (INV-07)"), schemas ("schema.org paths").
- Code: `content/text.py` (marks), `llm/marked.py` (new), `llm/grounding.py`, `llm/roles/c_extract.py` and its prompt,
  `resolve/pipeline.py`, `resolve/derive.py`, `schemas/presets/job_detail.json`; callers in `config_ir/role_c.py` and
  `eval/prefill.py`.
- Role C's detail request changes, so recorded detail calls no longer replay; one call per page as before, with more
  input tokens.
