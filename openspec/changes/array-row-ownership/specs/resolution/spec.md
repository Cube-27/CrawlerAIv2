## MODIFIED Requirements

### Requirement: Validity, intent and ownership
Every candidate SHALL pass its type normalizer ([normalization](../normalization/spec.md)), else it is rejected
`invalid`/`ambiguous`. `select_target` picks one primary-type entity (`resolve/intent.py`) or none, which makes every
field `conflict`/`intent_ambiguous`; a detail page's related items and its product's group do not make intent
ambiguous (D-1151); candidates the target does not own are rejected `not_owned`. An `array_row` entity's candidates
are the target's only on a detail page, when that row and every row enclosing it names a page URL or the target's URL
(`resolve/ownership.py`). Refs: §8.2 rule 3, Appendix A #55, D-0413, D-0785, D-1151, D-1254.
(Previously: no rule for `array_row` entities; state values were owned by `page`.)
#### Scenario: Related item's price in state
- **WHEN** a detail page's state holds an array of two items, the related one with its own URL and a visible price
- **THEN** that price is rejected `not_owned`, and a row naming the page URL gives the target's price
