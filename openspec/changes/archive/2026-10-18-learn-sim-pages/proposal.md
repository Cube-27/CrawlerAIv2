# learn-sim-pages: learning validated on pages it did not read

## Why

`eval learn-sim` validates a learned config on the same pages it learned from, because the golden dev split holds one
page per host (D-1685; backlog, "Learning induction"). That measures what induction and role A cover, not how a
config generalizes. The split needs several unlabeled pages per host, and the simulation needs to hold some out.

## What Changes

- `crawlerai eval import-pages --split dev --file <site list> --pages-per-site N` captures a site list's pages
  (`<category> <schema> <url>` per line) through the worker's acquisition path (HTTP, then the browser when the schema
  needs a render; robots.txt, politeness, up to 3 fetches per page) and stores each as an unlabeled page. A page
  already in the split is skipped. Unlabeled pages take no part in a scored run.
- `eval learn-sim` learns on each host's first `--pages` pages and validates on its later pages (`--validate
  held-out`, the default); `--validate same-page` is the previous behaviour. A host with no later page validates on
  its sample. The summary reports the hosts validated on later pages (`held_out_hosts`).

## Impact

- Specs: `evaluation` (Labeling API and eval capture; Learning simulation).
- Code: `crawlerai.cli`, `crawlerai.eval.page_import`, `crawlerai.eval.learn_sim`.
