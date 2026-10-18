## MODIFIED Requirements

### Requirement: Labeling API and eval capture
With `CRAWLERAI_EVAL_UI=true` the API SHALL mount `/v1/eval/*` for the `dev` split, API key and ETag guarded,
serving sanitized HTML. `crawlerai eval capture`/`import-sites` fetch through acquisition, obey robots.txt and store
every page whatever its outcome. `crawlerai eval import-pages --split dev --file <site list> --pages-per-site N` SHALL
capture the list's pages through the worker's acquisition path (a render when the schema needs one; a page not reached
fetched again up to 3 times in all, the best capture kept) and store each as an unlabeled page, skipping a page
already in the split; unlabeled pages are never scored. (Previously: no import of unlabeled pages through the worker's
path.) Refs: §16.1, §16.2, D-0207, D-0222, D-1760.
#### Scenario: Unlabeled page not scored
- **WHEN** a page is imported with `import-pages`
- **THEN** it has no label status and no run with `--labels all` scores it

### Requirement: Learning simulation
`crawlerai eval learn-sim` SHALL run learning on each dev host's first pages (per schema), replayed cold, validate the
config on the host's later pages (the learning pages when it has none, or with `--validate same-page`), and report
aggregates only by category: the zero-touch share (configs activated with no role A call), the activated share, the
hosts validated on later pages, config fields per host, the config fields in each executability class, and role A's
calls and cost; role A abstains unless asked to run, with a bound on its calls, and a live role A's tokens, cache read
and write tokens and cost at the model's prices are reported. (Previously: validated on the learning pages.) Refs:
D-1685, D-1726, D-1761.
