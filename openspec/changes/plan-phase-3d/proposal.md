# Plan phase 3d: fit calibration and precedence on the golden set

## Why

Every field is `calibrated=false` and the precedence is the spec's initial order. The owner approved fitting both on
the golden set (master plan decision 10), so confidence and τ come from measurements and the order follows data.

## What Changes

- `crawlerai eval fit-calibration --report FILE` (replaces `eval calibrate`) writes `backend/data/calibration.json`:
  per `field_type|evidence` bucket measured on at least 20 labelled values, `n` and a Beta(1, 1) posterior-mean
  confidence. Those buckets are `calibrated=true` and τ applies to them; every other bucket stays uncalibrated.
- `eval fit-precedence --report FILE` moves a source kind ahead of another only when their precision intervals
  separate (n >= 20 each).
- Both fit on a dev report (`eval run --out`) of an uncalibrated engine, not on a stored run; the files carry no site.
- The checked-in `calibration.json` and `source_precedence.yaml` are the first fit.

## Impact

`resolve/calibrate.py`, `resolve/evidence.py`, `eval/calibrate.py`, `cli.py`, `backend/data/`; capabilities
`evaluation`, `resolution`.
