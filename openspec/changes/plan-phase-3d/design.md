# Design: plan phase 3d, calibration and precedence fitted on the golden set

- Shape: `fit_buckets(cells) -> dict[str, Bucket]` and `fit_order(current, measured)` in `resolve/calibrate.py`;
  `eval.calibrate` reads a `Report` and writes the two files; the engine's loaders are unchanged.
- Overfitting: the fit and the measurement use the same 79 pages, so the after numbers are optimistic. The floor of 20
  and the prior keep thin buckets uncalibrated, and the order moves only on separated intervals.

## Decisions

### D-1740 — Floor of 20 labelled values; confidence is the Beta(1, 1) posterior mean
- Date: 2026-10-18 · Change/PR: plan-phase-3d · Status: decided (owner-delegated 2026-10-17)
- Decision: A bucket is calibrated from 20 labelled values (ARCHITECTURE §10 said 30). Its confidence is
  `(tp + 1) / (n + 2)`, rounded to four places; only such buckets are written, so a missing one is uncalibrated.
- Why: the owner set the floor of 20; the prior stops a small bucket from reading as certainty (20 of 20 gives 0.955).
- Reversible: yes (`MIN_CALIBRATED_N`, `fit_buckets`)

### D-1741 — A kind moves ahead only past a separated interval
- Date: 2026-10-18 · Change/PR: plan-phase-3d · Status: decided (owner-delegated 2026-10-17)
- Decision: Among kinds measured on at least 20 values, a kind moves to just before the next measured kind when the
  95% Wilson interval of its precision lies wholly above that kind's. Nothing else moves (no slot swapping with
  unmeasured kinds).
- Why: a point-estimate sort reorders on noise (url: two kinds 0.04 apart) and drags measured kinds past unmeasured ones.
- Reversible: yes

### D-1742 — Fits read a report of an uncalibrated engine, not a stored run
- Date: 2026-10-18 · Change/PR: plan-phase-3d · Status: decided (owner-delegated 2026-10-17)
- Decision: Both fit commands take `--report` (the `eval run --out` file, labeled rows) and refuse a report whose engine
  version carries a calibration; the stored-run path and the `eval_run_id` stamp are removed.
- Why: a stored run keeps only checked pages and every engine row; the golden set's drafts are not stored (D-1461). A
  run under τ measures only what τ let through.
- Reversible: yes

### D-1743 — τ is applied live as specified, though it abstains most page-level fields
- Date: 2026-10-18 · Change/PR: plan-phase-3d · Status: decided (owner-delegated 2026-10-17)
- Decision: A calibrated bucket below τ abstains, unchanged. On the golden set the calibrated text, url and money
  buckets sit at 0.57-0.97, below τ, so those fields abstain almost wholly. τ is not lowered.
- Why: the owner asked for τ live; lowering τ is the owner's call. The PR reports the coverage cost.
- Reversible: yes (drop buckets from `calibration.json`, or refit after precision improves)

### D-1744 — Two order changes, no measured effect
- Date: 2026-10-18 · Change/PR: plan-phase-3d · Status: decided (owner-delegated 2026-10-17)
- Decision: `long_text`: dom before og (0.74 over 23 against 0.18 over 33). `url`: xhr before jsonld (0.98 over 46
  against 0.80 over 182). `text` and `image_url` unchanged. The golden-set P/C per field type is identical with and
  without them.
- Why: separated intervals; the change is kept because it costs nothing and follows the data.
- Reversible: yes
