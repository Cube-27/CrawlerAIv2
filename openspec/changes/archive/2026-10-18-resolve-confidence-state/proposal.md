# Calibrated confidence is reported, not a publish gate; state JSON values have an evidence bucket

## Why

The first calibration fit (`eval fit-calibration`) puts every fitted text, url and money bucket (dev precision
0.57-0.97) below the fixed thresholds (0.97 required, 0.95 optional), so shipping it with the gate on would drop
coverage to about zero. Confidence is information for the caller, so it ships with every value, and a caller who
wants a floor asks for one. Separately, a value read from page state JSON at a key the item blocks proved has no
evidence bucket and no text precedence rank, so it never publishes alone.

## What Changes

- `min_confidence` (0 to 1, no default) on the scrape, batch, crawl and extract requests (REST, MCP), in the
  playground's Options, and as `crawlerai eval run --min-confidence`. Unset, every chosen value publishes with the
  confidence of its bucket; set, a calibrated bucket below it abstains `below_min_confidence`. The fixed thresholds
  and the reason `below_tau` are deleted.
- `backend/data/calibration.json` ships, fitted from an uncalibrated dev report: its nine buckets report
  `calibrated=true`.
- A value of the page's state JSON (`js_state`) has the evidence bucket `state` and ranks after every other source
  kind in the text, long_text, url and image_url orders.

## Impact

- Specs: resolution (evidence and confidence, source precedence), rest-api, evaluation, frontend.
- Public shapes: a new optional request member; a new `evidence` value `state`; the abstain reason `below_tau` is
  renamed `below_min_confidence` (it is now only ever the request's).
- Dev eval: coverage and precision per field type unchanged with the default.
