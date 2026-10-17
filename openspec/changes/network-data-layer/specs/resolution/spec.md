## MODIFIED Requirements

### Requirement: Evidence, confidence and τ
Each published field SHALL carry one evidence bucket (`resolve/evidence.py`; `agreed` needs two independent kinds;
`network` for a value of the page's captured calls, Appendix A #57; a lone `js_state` value has none and abstains
`no_bucket`) and the dev precision of its `(type, evidence)` bucket from `calibration.json`; a calibrated bucket below
τ (0.97 required, 0.95 otherwise) abstains `below_tau`. Until the first dev fit every field is uncalibrated.
Refs: §10, §16.3, D-0455, D-0456, D-1316.
(Previously: no bucket for `xhr` values, which abstained `no_bucket` unless they agreed.)
#### Scenario: Calibrated bucket below τ
- **WHEN** a required money field's bucket has n=40 and precision 0.969
- **THEN** the field is `abstained` with reason `below_tau`
#### Scenario: Value of a captured call
- **WHEN** a field's only candidate is a visible price read from a captured call
- **THEN** it publishes with evidence `network`, uncalibrated
