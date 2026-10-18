# Plan phase 4a: induction over block alignment, role A only for what induction cannot cover

## Why

Learning asks role A (`strong`) on most hosts: induction reads structured locators only, a listing's row selector and
row fields always come from role A, and role A runs whenever any field is left. On the dev split's first pages per
host about one host in seven got a config with no role A call (the zero-touch share).

## What Changes

- Learning's oracle is the engine's published values including role C's grounded ones: a verbatim text span is induced
  through the element holding it; `meta` content, embedded-state and captured-call paths, and the object holding a
  composite value (an offer's price and currency) are induced too.
- A listing's row selector and row-field steps are induced from the item layer's blocks paired with the published rows,
  verified by the engine executor; role A extends an induced listing instead of replacing it.
- Role A runs only when induction leaves a required field (or a whole required group) that some sample page published.
- `crawlerai eval learn-sim` replays each dev host's first pages through learning and reports aggregates by category:
  zero-touch share, activated share, config fields per host, role A calls and estimated cost.
- Deleted: the listing branch that sent every row field to role A, synthesis's refusal of an existing listing.
  `progressive.next_mode` was already deleted (#271).

## Impact

- Capabilities: `learning-configs` (Induction, then role A synthesis), `evaluation` (Learning simulation).
- Code: `config_ir/induction.py`, `config_ir/listing_induction.py` (new), `config_ir/learning.py`,
  `config_ir/synthesis.py`, `config_ir/held_out.py`, `eval/learn_sim.py` (new), `cli.py`.
