## MODIFIED Requirements

### Requirement: Standalone variants
A root Product whose `inProductGroupWithID` is the `productGroupID` of exactly one standalone ProductGroup, or whose
`isVariantOf` holds a ProductGroup or names one by its IRI, SHALL be that group's `hasVariant` member; a standalone
Product sharing an identifier or item URL with a group's member is that member (`resolve/identity.py`). Neither
`variesBy` nor identifier prefixes relate them. (Previously: `isVariantOf` left the group the Product's child.)
Refs: SPEC-13 §9, D-0966, D-1293, D-1344.
#### Scenario: Variants naming their group
- **WHEN** a ProductGroup with `productGroupID` G-1 and `color` Blue sits beside two Products stating
  `inProductGroupWithID` G-1
- **THEN** the group is the target, `color` publishes Blue, and `variants` holds both Products' rows
#### Scenario: Group held by isVariantOf
- **WHEN** the page's Product holds its ProductGroup in `isVariantOf`, and the group lists two variants
- **THEN** the group is the target and `variants` holds the two variants' rows, the Product joining the one it states
