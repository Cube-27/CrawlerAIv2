## MODIFIED Requirements

### Requirement: Induction, then role A synthesis
Learning's oracle SHALL be the engine's published values, role C's grounded ones (a verbatim span, a DOM claim)
included: fields published on all sample pages are first induced without an LLM from their locators, anchoring only on
stable attributes (`induction.py`), and a listing's row selector and row fields from the item layer's blocks paired with
the published rows, verified by the engine executor (`listing_induction.py`). Role A (`strong`) SHALL run only when
induction leaves a required field, or a whole required group, that some sample page published; it is then asked for
every field left, returns selectors only, verified on the sample with up to 3 repair rounds; a field still failing gets
no steps. Refs: §8.3, D-0031, D-0551, D-0585, D-1680, D-1683.
(Previously: only structured locators were induced, a listing's row selector and row fields came from role A only, and
role A ran whenever induction left a field.)
