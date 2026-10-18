## MODIFIED Requirements

### Requirement: Role C input, claims and candidates
Role C SHALL read cleaned text, never raw HTML. On a detail page it reads the flat text cut at 40,000 characters and
replies one `{shown, value, start, end}` claim per asked field; a value under `shown: false` is not taken (C7). On a
listing it reads one line per block of the bound item group (`collect/items/lines.py`, [listings](../listings/spec.md)),
`[n]` its position in the group, the block's span of the cleaned text with each line break shown as a space, and
replies claims `{block, field, value}`: a claim fills that block's row only for a field its row was asked for, the
first per block and field wins, its value is grounded in that block's text only (INV-12) and located at its offset in
the cleaned text. A listing reads at most 200 blocks across its calls, each call within 80,000 characters and as many
blocks as their claims fit the reply. Grounded values are normalized into
`Candidate(source_kind='llm', independent=True)`. (Previously: a listing read the items' text view and claimed whole
rows, placed on a block by its links.) Refs: §8.4, D-0025, D-0521, D-1097, D-1600, D-1601, D-1602, D-1606.
#### Scenario: Field not shown
- **WHEN** a claim is `{shown: false, value: "x"}`
- **THEN** no candidate is made and the field stays `missing`
#### Scenario: Value of another block
- **WHEN** a claim for block 0 names a value only block 1 shows
- **THEN** it is dropped as `role C: block 0 <field> ungrounded`
#### Scenario: Long listing
- **WHEN** a listing asks 210 blocks
- **THEN** role C reads the first 200 in calls that fit the reply, and records that it read 200 of 210 blocks

### Requirement: When role C is asked
In cold mode role C SHALL be asked on a detail page only when a required field or group is `missing` (with every
missing optional field in the same call); in `active` mode only for fields the config neither runs nor lists as absent.
A listing asks it as [listings](../listings/spec.md) "Role C rows" states: the blocks' calls, and one call for the page
fields. Not in captures replay. The `c_prefill` variant stores grounded `Ok` values only as a `draft` label, never
ground truth ([evaluation](../evaluation/spec.md)); on a listing it asks the first aligned group's blocks for every
row field but the item URL, and the page fields in their own call. (Previously: a listing called it once, page fields
in its first call.) Refs: §8.4, D-0520, D-1006, D-0538, D-1341, D-1604, D-1607, owner #67.
