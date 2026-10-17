## MODIFIED Requirements

### Requirement: When role C is asked
In cold mode role C SHALL be asked only when a required field or group is `missing` (with every missing optional field
in the same call); in `active` mode only for fields the config neither runs nor lists as absent. A cold listing calls it
once only when structured data gives no rows. Not in captures replay. The `c_prefill` variant stores grounded `Ok`
values only as a `draft` label, never ground truth ([evaluation](../../../../../specs/evaluation/spec.md)). (Previously: absent fields
were asked too.) Refs: §8.4, D-0520, D-1006, D-0538, D-1341.
