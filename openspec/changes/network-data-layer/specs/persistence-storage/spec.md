## MODIFIED Requirements

### Requirement: Capture bundle format
Each capture SHALL be one deterministic zstd tar (manifest, body as received, browser network bodies as received) as
defined in the bundle codec; `decode(encode(b)) == b`, and an inconsistent bundle raises `CorruptBundle`. A network
entry's response headers, resource type and action index decode as None in bundles written before they were kept.
Replay reads only the bundle, never the `capture` row. Refs: §15, Appendix A #58, D-0097, D-0098, D-1311.
(Previously: no response headers, resource type or action index per network entry.)
#### Scenario: Round trip
- **WHEN** any valid bundle is encoded and decoded (Hypothesis property test)
- **THEN** the result equals the original and re-encoding gives the same bytes
