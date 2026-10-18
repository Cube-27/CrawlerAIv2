## MODIFIED Requirements

### Requirement: Fitting on the golden set
`eval fit-calibration` and `eval fit-precedence` SHALL fit on a dev report of an engine without a calibration, scored
on the labeled rows, refuse any other, and stamp what they write `source_split: dev`; the files hold bucket and
source-kind names and numbers only. (Previously: `eval calibrate` and `eval fit-precedence` fitted on a stored dev
run.) Refs: owner (2026-10-18, master plan decision 10).
#### Scenario: Report of a calibrated engine
- **WHEN** a fit reads a report whose engine version names a calibration
- **THEN** it exits non-zero and writes nothing
