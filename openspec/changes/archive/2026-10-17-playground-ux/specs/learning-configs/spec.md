## MODIFIED Requirements

### Requirement: Activation and active-mode extraction
A validated config with at least one field SHALL become version max+1 and the one `active` config (the previous one
`suspended`), unless the project's `require_config_approval` is on: then it is stored `pending_approval`, what served
before goes on serving, no run starts while it waits (a forced run may, and replaces it), `POST /v1/configs/{id}/approve`
activates it and `POST /v1/configs/{id}/reject` suspends it, the state then waiting for 8 more pages before it learns
again. In `active` mode a field the config runs SHALL NOT be asked of role C, even when its step misses.
(Previously: no reject.) Refs: §8.3, §8.4, D-0569, D-0615, D-0783, D-1342, D-1391.
#### Scenario: Covered field missing
- **WHEN** a covered field's steps match nothing on a page
- **THEN** it stays `missing` and no LLM call is made for it
#### Scenario: Approval required
- **WHEN** a run validates a config while `require_config_approval` is on
- **THEN** the config is `pending_approval`, pages are served as before, and it serves only once approved
#### Scenario: Rejected
- **WHEN** a `pending_approval` config is rejected
- **THEN** it is `suspended`, the config serving before stays active, and no run starts until 8 more pages are extracted
