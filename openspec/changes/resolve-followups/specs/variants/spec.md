## ADDED Requirements

### Requirement: Standalone variants
A root Product whose `inProductGroupWithID` is the `productGroupID` of exactly one standalone ProductGroup SHALL be
that group's `hasVariant` member; a standalone Product sharing an identifier or item URL with a group's member is
that member (`resolve/identity.py`). Neither `variesBy` nor identifier prefixes relate them.
Refs: SPEC-13 §9, D-0966, D-1293.
#### Scenario: Variants naming their group
- **WHEN** a ProductGroup with `productGroupID` G-1 and `color` Blue sits beside two Products stating
  `inProductGroupWithID` G-1
- **THEN** the group is the target, `color` publishes Blue, and `variants` holds both Products' rows
