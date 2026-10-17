## MODIFIED Requirements

### Requirement: Activation and active-mode extraction
A validated config with at least one field SHALL become version max+1 and the one `active` config (the previous one
`suspended`), unless the project's `require_config_approval` is on: then it is stored `pending_approval`, what served
before goes on serving, no run starts while it waits (a forced run may, and replaces it), and
`POST /v1/configs/{id}/approve` activates it. In `active` mode a field the config runs SHALL NOT be asked of role C,
even when its step misses. (Previously: no approval.) Refs: §8.3, §8.4, D-0569, D-0615, D-0783, D-1342.
#### Scenario: Covered field missing
- **WHEN** a covered field's steps match nothing on a page
- **THEN** it stays `missing` and no LLM call is made for it
#### Scenario: Approval required
- **WHEN** a run validates a config while `require_config_approval` is on
- **THEN** the config is `pending_approval`, pages are served as before, and it serves only once approved

## ADDED Requirements

### Requirement: Absent fields
On a detail schema, learning SHALL list in the config's `absent` (field status `absent`) each required field or
required-group member that no page of the run published or gave a valid candidate for from any source while role C was
asked on every page (`config_ir/absent.py`). Role C is not asked for it in config mode, where it stays `missing` with
reason `absent`; a config page that publishes it removes it and starts a forced re-learn. Refs: D-0784, D-1341, D-1347.
#### Scenario: A field no page states
- **WHEN** a required sku is stated by no source on any of the 8 pages a run reads, and role C was asked on each
- **THEN** the config lists `sku` as absent and a config-mode page asks role C nothing for it
