## ADDED Requirements

### Requirement: Candidate validity
Every candidate SHALL pass its type normalizer ([normalization](../../../../../specs/normalization/spec.md)), else it is
rejected `invalid`/`ambiguous`. Which entity a candidate belongs to is
[identity-and-intent](../../../../../specs/identity-and-intent/spec.md). Refs: §8.2, D-1379.

## REMOVED Requirements

### Requirement: Validity, intent and ownership
(Moved to identity-and-intent as "Entity identity, intent and ownership", with the normalizer gate left here.)

### Requirement: Entity key
(Moved to identity-and-intent.)
