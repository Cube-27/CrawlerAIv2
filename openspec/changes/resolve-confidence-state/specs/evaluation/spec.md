## MODIFIED Requirements

### Requirement: Claims before and after milestone M
A bucket SHALL be `calibrated=true` only when `calibration.json` (fitted on dev) holds it; improvement claims come only
from golden-set results (a change's dev delta, a fresh batch's first score), and no doc, PR or UI claims accuracy
beyond them. (Previously: until calibration was fitted confidence was `calibrated=false`.) Refs: owner (2026-10-18,
master plan decision 2), D-1772.

## ADDED Requirements

### Requirement: Gated eval run
`eval run --min-confidence` SHALL replay the split with that minimum confidence and store no run, so a fit never reads
what a gate let through. Refs: D-1771.
