# LLM Specification

## Purpose

One provider-agnostic LLM client with constrained JSON output, per-job budgets, usage and estimated cost, plus roles C
(grounded values) and S (schema drafts); roles A and D use the client but live in
[learning-configs](../learning-configs/spec.md) and [adapters](../adapters/spec.md).

## Requirements

### Requirement: Four roles, core only
The system SHALL use the LLM only in roles C (grounded values), A (selectors or JSONPath), D (a typed request spec)
and S (a draft schema); only role C outputs values. Adjudication, a verifier and self-consistency SHALL NOT be built
(§22, C13). Refs: §11, §22.

### Requirement: Providers, model classes and setup check
The system SHALL call providers in `CRAWLERAI_LLM_PROVIDERS` order, mapping model class `fast` (role C) and `strong`
(A, D, S) to model ids as defined in `core/settings.py`; a listed provider without a key is refused. API, MCP and
worker SHALL check model ids at start (no tokens) and `/healthz` reports `llm: checking | ok | unavailable`, staying
200. Refs: D-0023, D-0374, D-0935.

### Requirement: Constrained JSON output inside provider subsets
Every call SHALL request JSON-schema constrained output with a closed object root, kept inside each provider's subset
in `backend/data/llm/<provider>-structured-output.json` (checked by `llm/schema_subset.py`). Gemini sends
`temperature: 0`; Anthropic sends no sampling parameters, `fast` calls ask low effort. Refs: D-0349, D-0370, D-1008.
#### Scenario: Open root refused
- **WHEN** a request's output schema omits `additionalProperties: false` at the root
- **THEN** it is refused before any call

### Requirement: Validation, retry, failover and error reasons
The client SHALL validate each reply (JSON Schema 2020-12 plus an optional role check) and retry once with the error;
a second invalid or a cut reply is `llm_output_invalid`. It SHALL fail over once, only when no answer came (408, 429,
5xx, timeout, connection error); other statuses are `llm_refused`, no answer is `llm_unavailable`, and asked fields
stay `missing`, never guessed. Refs: D-0351, D-0371, D-0767, D-1009.
#### Scenario: Provider 503
- **WHEN** the first provider answers 503
- **THEN** the same request goes once to the next provider, and a 400 instead gives `llm_refused` with no failover

### Requirement: Per-job budgets
Before each call and retry the client SHALL check the job's `llm_calls` budget, else the project's `llm_call_cap`
(none by default), and raise `BudgetExhausted` (`budget_exhausted`) when spent; a call with no job (pre-fill, eval
recording, field-names draft) skips the budget. Refs: §17, D-0348, D-0723, D-1121.

### Requirement: Usage event per call (INV-23)
Every answered LLM call SHALL write a `usage_event` with its `prompt_kind` and tokens, in its own transaction, charged
to the job budget (a retried call counts twice), and be listed in `extraction.llm_calls` without prompt text.
Enforced by: `tests/db/test_llm_client.py`; active. Refs: §17, D-0346, D-0768.
#### Scenario: Retried call
- **WHEN** a reply is invalid and the retry answers validly
- **THEN** two calls are charged, each with its `prompt_kind` and tokens

### Requirement: Deterministic request hash
`request_hash` SHALL be sha256 of canonical JSON of (prompt_kind, model_class, system, user, output_schema and, when the
request has any, its cached parts), so `RecordedLLM` replays hit their cache (INV-10, owned by
[evaluation](../evaluation/spec.md)). Refs: D-0350, D-1721.

### Requirement: Estimated cost from versioned prices
The system SHALL estimate cost for visibility, not billing, from `backend/data/llm/<provider>-pricing.json`
(`llm/pricing.py`), cache read and write tokens at the file's cache prices; tokens no price covers are
`unpriced_tokens` and make the sum's `estimated_usd` null (C7). `GET /v1/usage/llm` and `/v1/usage/llm/jobs` serve it by
UTC day. Refs: §17, D-0719, D-0724, D-1721.

### Requirement: Grounded values (INV-12)
Every `llm` candidate value SHALL be a verbatim substring of the cleaned text at its stated offsets (INV-12): exact
match at the claim, else the single or nearest exact occurrence, else dropped; no fuzzy matching (`llm/grounding.py`).
A money claim grounds only on whole numbers, never the head or tail of a longer, grouped or decimal one (`$4` in
`$4,000`). One the text does not hold verbatim is found with any spacing between its currency sign and its one amount
(CLDR `currencySpacing`: that space is the locale's presentation), and its value is the
text's span, never the model's spelling. (Previously: a money claim spaced otherwise than the text was dropped.)
A span SHALL be whole words (Unicode UAX #29: letters, marks, digits and connector punctuation continue a word, except
in scripts written without spaces, UAX #11 wide and fullwidth characters and UAX #14 class SA); where two text runs of
the page meet, a word ends. An occurrence inside a longer word holds no value (`0` inside `9781400215522`). An
identifier claim SHALL NOT ground inside an address: a URL or path reference (RFC 3986) or a media file's name (a
registered image, audio or video media type's extension) is a resource the page names, not an identifier it states.
(Previously: any occurrence grounded, a part of a word or an address included.)
A claimed link or image SHALL be an element the page has, of the kind its field takes, and its value that element's
`href` or `src` as the DOM states it, never text of the model's. Enforced by: `tests/property/test_grounding.py`,
`tests/unit/test_grounding.py`, `tests/unit/test_role_c.py`; active. (Previously: only text spans.) Refs: §11,
D-0024, D-0379, D-1623.
#### Scenario: Wrong offsets or not in text
- **WHEN** a claimed value occurs once at other offsets, or not at all
- **THEN** it is accepted with corrected offsets, or dropped as `role C: <field> ungrounded` without the value
#### Scenario: Money spaced otherwise
- **WHEN** a price claim is `$19.98` and the text writes `$ 19.98`
- **THEN** it is grounded at `$ 19.98`, which is its value
#### Scenario: Part of a longer number
- **WHEN** a rating claim is `0` and the text's only `0`s are inside `ISBN13: 9781400215522`
- **THEN** it is dropped as `role C: rating ungrounded`
#### Scenario: Identifier in an image path
- **WHEN** an mpn claim is `EKA20X2` and the text writes it only in `.../EKA20X1.EKA20X2-Frontal.jpg`
- **THEN** it is dropped as `role C: mpn ungrounded`
#### Scenario: Claimed id of no such element
- **WHEN** a url field's claim names an id no link on the page has, or an image's
- **THEN** it is dropped as `role C: <field> ungrounded`

### Requirement: Role C input, claims and candidates
Role C SHALL read cleaned text, never raw HTML. On a detail page it reads the product's own flat text: the runs inside
the elements that hold other items' content (`collect/dom.py` `other_item_paths`: related and similar items, reviews,
lists of other documents' cards, and the blocks outside the product container, `product_apart`, such as other items'
priced cards) are left out with their separators, and a grounded span is located back at its offsets in the whole
cleaned text (`llm/marked.py` `scoped`). It reads that text cut at 40,000 characters, with
an id after each shown link to another resource and at each shown image when an asked field is a url or an image_url
(`llm/marked.py`; the page is its final URL, so a link to it is unmarked whatever the base URL; the ids take at most
10,000 characters together, the marks past that unshown), and replies one `{shown, ref, value, start, end}` claim per asked field: a span, or in `ref` the id
of the link or image whose target is the value; a value under `shown: false` is not taken (C7). On a
listing it reads one line per block of the bound item group (`collect/items/lines.py`, [listings](../listings/spec.md)),
`[n]` its position in the group, the block's span of the cleaned text with each line break shown as a space, preceded
by its enclosing item's context when it has one ([listings](../listings/spec.md) "Role C rows"), and replies claims
`{block, field, value}`: a claim fills that block's row only for a field its row was asked for, the first per block and
field wins, its value is grounded in that block's text, else in its context, only (INV-12) and located at its offset in
the cleaned text. A listing reads at most 200 blocks across its calls, each call within 80,000 characters and as many
blocks as their claims fit the reply. Grounded values are normalized into
`Candidate(source_kind='llm', independent=True)`; a field whose claimed value the evidence does not hold stays
`missing` with reason `unverified` (resolution spec "LLM gap hook"). (Previously: a detail page's text carried no ids,
and its claims were spans only; it read the whole page's text, other items' cards included, and an ungrounded field's
reason was `no_candidates`.) Refs: §8.4, D-0521, D-1097, D-1600, D-1601, D-1602, D-1606, D-1621, D-1622, D-1623, D-1627.
#### Scenario: Field not shown
- **WHEN** a claim is `{shown: false, value: "x"}`
- **THEN** no candidate is made and the field stays `missing`
#### Scenario: Claimed link
- **WHEN** an asked url field's claim names `L1`, the id of `<a href="/apply">Apply</a>`
- **THEN** its candidate is `/apply` resolved against the page, with the link's `dom:` locator
#### Scenario: Price of a related product
- **WHEN** a detail page shows its product without a price and a related product's card shows `$12`
- **THEN** role C does not read the card, and `price` stays `missing`
#### Scenario: Value of another block
- **WHEN** a claim for block 0 names a value only block 1 shows
- **THEN** it is dropped as `role C: block 0 <field> ungrounded`
#### Scenario: Long listing
- **WHEN** a listing asks 210 blocks
- **THEN** role C reads the first 200 in calls that fit the reply, and records that it read 200 of 210 blocks

### Requirement: Role C value checks
A grounded role C span SHALL be the field's own fact, as the page's structure states it (`llm/claim_checks.py`): an
identifier's span starts past a label written before it with a colon (`REF.: CLU-1` is `CLU-1`) and past a number sign
(`#123` is `123`); a span the page labels as another field is not taken: the label right before it on its line, ended
by a colon, and for a number or count also the words right after it ("293 Reviews"), read with the schema's label
vocabulary (extraction spec, "Label vocabulary"), name fields of which this one is none. A label that names no field,
or this one, decides nothing. On a listing, a place claimed for a row from its block's heading (HTML `h1`-`h6`, the
item's name) is not taken when a line of the block outside the heading states that the job is remote (the location
normalizer's `type:remote` clause): the block states its place there. A value not taken leaves the field as an
ungrounded one does. (Previously: any grounded span was taken.) Enforced by: `tests/unit/test_role_c.py`; active.
Refs: §11, INV-12.
#### Scenario: Label kept with an identifier
- **WHEN** a product_id claim is `REF.: CLU459_4712_V2`
- **THEN** its candidate is `CLU459_4712_V2`, located past the label
#### Scenario: Another field's label
- **WHEN** a product_id claim is a span after `ISBN:` and `ISBN` is a label of gtin only
- **THEN** it is not taken, and product_id stays `missing` (`unverified`)
#### Scenario: Remote card, city in the title
- **WHEN** a job card's heading is `Sales Rep - Austin, TX` and a line of the card says `Remote`, and the claim for the
  row's locations is `Austin, TX`
- **THEN** it is not taken

### Requirement: When role C is asked
In cold mode role C SHALL be asked on a detail page when any field is `missing`, optional ones included, for every
missing field in one call; in `active` mode only for fields the config neither runs nor lists as absent.
A listing asks it as [listings](../listings/spec.md) "Role C rows" states: the blocks' calls, and one call for the page
fields. Not in captures replay. The `c_prefill` variant stores grounded `Ok` values only as a `draft` label, never
ground truth ([evaluation](../evaluation/spec.md)); on a listing it asks the first aligned group's blocks for every
row field but the item URL, and the page fields in their own call. (Previously: a detail page asked it only when a
required field or group was missing.) Refs: §8.4, D-0520, D-1006, D-0538, D-1341, D-1604, D-1607, D-1620, owner #67.
#### Scenario: Only an optional field missing
- **WHEN** a detail page publishes every required field and an optional field is `missing`
- **THEN** role C is asked once, for that field

### Requirement: Role S schema drafting
Role S SHALL draft a `SchemaDef` from a prompt plus 1–3 sample pages, or from 1–50 field names and a page kind (top
level exactly those names), stored with `origin='prompt_draft'` under a name hashed from the normalized input, so a
repeat returns the stored draft without a call ([schemas](../schemas/spec.md)). Refs: §5.4, D-0026, D-0449, D-0926.
#### Scenario: Input repeated
- **WHEN** the same prompt (up to whitespace) or the same names in another order are sent again
- **THEN** one `schema_def` row exists and no LLM call is made

### Requirement: Role S label synonyms
Role S SHALL draft, once per schema and never per page, the labels pages write next to each labelled field's value, in
English and other languages (`llm/roles/s_labels.py`, `prompt_kind` `s_labels`), from the fields' names, types,
schema.org paths and descriptions; they are stored with the schema (`schema_def.labels`) when a request first uses
it (by id, inline, field names or a prompt with `records`). Labels repeating a field's own words or each other's are
dropped, at most 32 per field. Without a reply (no provider, a failure, the key's draft cap) the schema is used as it
is and the next use asks again. The call is charged to no job.
#### Scenario: Schema used twice
- **WHEN** two scrapes use one schema with a configured provider
- **THEN** one `s_labels` call is made and both extract with the stored synonyms

### Requirement: LLM output is never executed (INV-17)
Page text SHALL sit in a delimited data section, the model gets no tools, and prompts hold no site names (INV-03, see
`openspec/project.md`). LLM output SHALL never be executed (no `exec`, `eval`, `compile` or shell call); selectors,
recipes and schemas run only in our interpreters. Enforced by: ruff `S` rules and `tests/contracts/test_no_exec.py`;
active. Refs: §11, §18.
#### Scenario: New exec call
- **WHEN** a change adds `eval(` to backend code outside the allowlist
- **THEN** CI fails

### Requirement: Per-key cap on uncharged role S calls
A model call no job pays for (a field-names draft: `POST /v1/schemas/draft`, `schema.fields`; label synonyms) SHALL
count against its API key's `draft_calls`, refused or skipped once the key has made `project.draft_call_cap` of them; null is no cap. At
the cap a field-names draft is refused with `draft_cap_reached` (429), and label synonyms are skipped: the request goes
on with the schema as it is. A stored draft needs no call and counts nothing, nor does a process without a provider. Refs: §17, D-0926, D-1282.
#### Scenario: Key at the cap
- **WHEN** a key with a cap of 1 drafts two different sets of field names
- **THEN** the first is drafted and the second is a 429 with no model call; the first set again is returned stored

### Requirement: Prompt caching
A request SHALL be able to name leading parts of its user message that repeat across requests (`cached`); a provider
that caches prompts SHALL cache the prompt up to the end of each part. The client SHALL report each call's tokens read
from and written to the cache, record them in the usage metadata of the call's rows (the call's prompt length counts
them) and price them at the model's cache prices; a call whose cache tokens have no cache price is unpriced (C7).
Refs: D-1720, D-1721.
