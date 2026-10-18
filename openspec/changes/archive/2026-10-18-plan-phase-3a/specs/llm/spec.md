## MODIFIED Requirements

### Requirement: Grounded values (INV-12)
Every `llm` candidate value SHALL be a verbatim substring of the cleaned text at its stated offsets (INV-12): exact
match at the claim, else the single or nearest exact occurrence, else dropped; no fuzzy matching (`llm/grounding.py`).
A claimed link or image SHALL be an element the page has, of the kind its field takes, and its value that element's
`href` or `src` as the DOM states it, never text of the model's. Enforced by: `tests/property/test_grounding.py`,
`tests/unit/test_grounding.py`, `tests/unit/test_role_c.py`; active. (Previously: only text spans.) Refs: §11,
D-0024, D-0379, D-1623.
#### Scenario: Wrong offsets or not in text
- **WHEN** a claimed value occurs once at other offsets, or not at all
- **THEN** it is accepted with corrected offsets, or dropped as `role C: <field> ungrounded` without the value
#### Scenario: Claimed id of no such element
- **WHEN** a url field's claim names an id no link on the page has, or an image's
- **THEN** it is dropped as `role C: <field> ungrounded`

### Requirement: Role C input, claims and candidates
Role C SHALL read cleaned text, never raw HTML. On a detail page it reads the flat text cut at 40,000 characters, with
an id after each shown link to another resource and at each shown image when an asked field is a url or an image_url
(`llm/marked.py`), and replies one `{shown, ref, value, start, end}` claim per asked field: a span, or in `ref` the id
of the link or image whose target is the value; a value under `shown: false` is not taken (C7). On a
listing it reads one line per block of the bound item group (`collect/items/lines.py`, [listings](../listings/spec.md)),
`[n]` its position in the group, the block's span of the cleaned text with each line break shown as a space, and
replies claims `{block, field, value}`: a claim fills that block's row only for a field its row was asked for, the
first per block and field wins, its value is grounded in that block's text only (INV-12) and located at its offset in
the cleaned text. A listing reads at most 200 blocks across its calls, each call within 80,000 characters and as many
blocks as their claims fit the reply. Grounded values are normalized into
`Candidate(source_kind='llm', independent=True)`. (Previously: a detail page's text carried no ids, and its claims
were spans only.) Refs: §8.4, D-0521, D-1097, D-1600, D-1601, D-1602, D-1606, D-1621, D-1622, D-1623.
#### Scenario: Field not shown
- **WHEN** a claim is `{shown: false, value: "x"}`
- **THEN** no candidate is made and the field stays `missing`
#### Scenario: Claimed link
- **WHEN** an asked url field's claim names `L1`, the id of `<a href="/apply">Apply</a>`
- **THEN** its candidate is `/apply` resolved against the page, with the link's `dom:` locator
#### Scenario: Value of another block
- **WHEN** a claim for block 0 names a value only block 1 shows
- **THEN** it is dropped as `role C: block 0 <field> ungrounded`
#### Scenario: Long listing
- **WHEN** a listing asks 210 blocks
- **THEN** role C reads the first 200 in calls that fit the reply, and records that it read 200 of 210 blocks

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
