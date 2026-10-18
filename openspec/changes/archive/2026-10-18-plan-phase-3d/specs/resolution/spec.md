## MODIFIED Requirements

### Requirement: Evidence, confidence and τ
Each published field SHALL carry one evidence bucket (`resolve/evidence.py`; `agreed` needs two independent kinds;
`network` for a value of the page's captured calls, Appendix A #59; a lone `js_state` value has none and abstains
`no_bucket`) and the fitted dev confidence of its `(type, evidence)` bucket from `calibration.json`, which holds only
buckets measured on at least 20 labelled values (the others are uncalibrated); a calibrated bucket below τ (0.97
required, 0.95 otherwise) abstains `below_tau`. (Previously: dev precision, calibrated from 30 labels, none fitted.)
Refs: §10, §16.3, D-0455, D-0456, D-1316, D-1740.
#### Scenario: Calibrated bucket below τ
- **WHEN** a required money field's bucket has n=40 and precision 0.969
- **THEN** the field is `abstained` with reason `below_tau`
#### Scenario: Bucket below the floor
- **WHEN** a bucket has n=19
- **THEN** the field publishes with `calibrated=false`
#### Scenario: Value of a captured call
- **WHEN** a field's only candidate is a visible price read from a captured call
- **THEN** it publishes with evidence `network`, uncalibrated while that bucket is below the floor
