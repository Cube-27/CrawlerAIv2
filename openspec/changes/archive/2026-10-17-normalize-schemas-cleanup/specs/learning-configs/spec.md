## MODIFIED Requirements

### Requirement: Config IR
A config SHALL be an `ExtractionConfigIR` (`config_ir/model.py`) with extra keys refused; it may hold site strings
because it is per-site data (C3), the package holds none. Its `schema` reference SHALL hold the schema's name and the
digest of its document at learning; a config whose digest is not the stored document's is neither activated nor
corrected (a schema is edited in place). Refs: §12.1, D-0462, D-0465, D-0950, D-1375. (Previously: the reference held
the name only.)
#### Scenario: Config learned before a schema edit
- **WHEN** a schema's field description is edited after a config was learned for it
- **THEN** activating that config raises `ConfigMismatch`, and correcting it is a 409
