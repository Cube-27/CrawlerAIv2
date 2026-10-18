## MODIFIED Requirements

### Requirement: Induction, then role A synthesis
Learning's oracle SHALL be the engine's published values, role C's grounded ones (a verbatim span, a DOM claim)
included: fields published on all sample pages are first induced without an LLM from their locators, anchoring only on
stable attributes (`induction.py`), and a listing's row selector and row fields from the item layer's blocks paired with
the published rows, verified by the engine executor (`listing_induction.py`). Role A (`strong`) SHALL run only when
induction leaves a required field, or a whole required group, that some sample page published; it is then asked for
every field left, returns selectors only, verified on the sample with up to 3 repair rounds; a field still failing gets
no steps. Role A's requests SHALL share one system prompt and cache the field definitions and sample pages; a repair
SHALL send the first sample page only, in the first request's output schema, and a sample page's input SHALL be at most
60,000 characters. Refs: §8.3, D-0031, D-0551, D-0585, D-1680, D-1683, D-1720, D-1722, D-1723.
(Previously: a repair sent every sample page again, a page's input was up to 120,000 characters, and nothing was
cached.)

## ADDED Requirements

### Requirement: Executability classes
Each field of a config, each row field and a listing's `next` SHALL have an executability class from its steps alone:
`static-html` (the page's HTML, its JSON-LD or the JSON of its inline scripts), `needs-browser` (a captured response),
`api-call` (the response of the config's API recipe) or `unexecutable` (a suspended field, or an `api` source without a
recipe); a field with several steps takes the most demanding. The config release check SHALL report each field's class
and the count of fields per class. Refs: D-1724, D-1725.
