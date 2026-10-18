# Design: plan phase 4a, induction over block alignment

Learning reads its sample pages (`SamplePage`: the parsed page, its context, the published page values and rows, each
value with its locator). Induction proposes steps per field from the locators, and `listing_induction` proposes a
listing (`ListingSpec`: row selector, row fields relative to it) from the item layer's blocks (`collect.items.align`)
paired with the published rows by their item URLs. Every proposal is kept only if the engine executor gives the
published value from it on every sample page. Role A sees what is left.

## Decisions

### D-1680 — Learning's oracle holds role C's grounded values
- Date: 2026-10-18 · Change/PR: plan-phase-4a (#285) · Status: decided (owner-delegated 2026-10-17)
- Decision: A value role C grounded as a verbatim span of the cleaned text (`text:<start>-<end>`) is induced through
  the innermost element whose text holds the span (the common node path of the overlapping text runs), by the same
  anchored paths as a DOM value; `meta` values through their `property` or `name`, embedded-state and captured-call
  values by their JSONPath. Held-out validation is unchanged.
- Why: the owner's oracle is engine values ∪ role-C-grounded values; a grounded span names the element, so no LLM is
  needed to find it. Validation still compares with what the engine published.
- Reversible: yes

### D-1681 — A listing's row selector is induced from the item layer's group that holds the published rows
- Date: 2026-10-18 · Change/PR: plan-phase-4a (#285) · Status: decided (owner-delegated 2026-10-17)
- Decision: On each sample page the item layer's group whose block links match the most published row URLs is taken;
  its blocks are paired with those rows. The row selector is the first anchored path of the blocks (then a positional
  tag path) that, on every page, selects every paired block and nothing outside the group.
- Why: the blocks are the items the page shows (DEPTA-style alignment, already built in phase 2); the item URL is
  the row's identity as row matching uses it.
- Reversible: yes

### D-1682 — Row fields are read relative to the block and must reproduce the paired rows
- Date: 2026-10-18 · Change/PR: plan-phase-4a (#285) · Status: decided (owner-delegated 2026-10-17)
- Decision: A row field's steps are proposed from the block elements whose text or attribute gives the published value
  (an attribute resolved against the base URL, RFC 3986 §5, for a URL field): anchored relative paths first, then
  plain, then positional. A step is kept when it gives a valid value on every row and the published value on every
  paired row, rows aligned as validation aligns them. Published rows no block holds are left to validation.
- Why: a source can list more items than the page shows (embedded state with every result); demanding those rows
  would refuse every selector, while validation still counts them against the field's yield.
- Reversible: yes

### D-1683 — Role A runs only for a required field induction left that some sample page published
- Date: 2026-10-18 · Change/PR: plan-phase-4a (#285) · Status: decided (owner-delegated 2026-10-17)
- Decision: Role A runs when, after induction, a required field (or every member of a required group) has no steps, is
  not mapped, not absent and was published on some sample page; once it runs it is asked for every field induction
  left, as before. An optional field alone never makes it run.
- Why: role A is the expensive call (§10); a field no page published has no value to verify a selector against, so
  asking for it cannot succeed.
- Reversible: yes

### D-1684 — A composite value is read from the object holding it
- Date: 2026-10-18 · Change/PR: plan-phase-4a (#285) · Status: decided (owner-delegated 2026-10-17)
- Decision: For a JSON-LD, embedded-state or captured-call value, induction also proposes the path of the object the
  value is a member of, after the value's own path. A money field located at `offers.price` is read from the offer,
  which holds the price and its currency.
- Why: the engine publishes a composite (`Offer.price+priceCurrency`) from one object while its locator names one
  member; the member alone normalizes to `no_currency`.
- Reversible: yes

### D-1685 — The learning simulation validates in-sample and estimates role A's cost
- Date: 2026-10-18 · Change/PR: plan-phase-4a (#285) · Status: decided (owner-delegated 2026-10-17)
- Decision: `eval learn-sim` groups the dev split by final-URL host and schema, takes each group's first `--pages`
  pages in capture order, replays them cold (role C from recordings), and validates on the same pages (repeated to
  three). Role A abstains by default and only its first call per host is counted; its cost is its request characters
  / 4 at the strong model's input price. Production learning keeps its own split.
- Why: the golden dev split holds one page per host, too few for a held-out set; the measure is what induction and role
  A cover, not how a config generalizes. Abstaining keeps the measure free and repeatable.
- Reversible: yes
