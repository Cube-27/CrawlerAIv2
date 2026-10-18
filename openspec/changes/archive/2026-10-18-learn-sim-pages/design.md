# Design: learn-sim-pages

## Decisions

### D-1760 — Unlabeled pages are imported by a command of their own, through the worker's acquisition path
- Status: decided (owner-delegated 2026-10-17)
- Why: `import-sites` fetches over HTTP only, so a page that needs a render is stored as a shell; `import-labels`
  reads a label file and stores drafts. `import-pages` takes the site-list format of `import-sites` and the fetch of
  `import-labels`, and stores no label, so a page can be added to a host without being scored.
- Reversible: yes

### D-1761 — learn-sim validates on later pages by default; a host with none falls back to its sample
- Status: decided (owner-delegated 2026-10-17)
- Why: a held-out page is one learning never read (D-1685 measured only coverage). The sample is the first `--pages`
  pages in capture order and the rest are held out, repeated to the validation minimum when fewer; a host with no later
  page validates on its sample as before, so a split of one page per host reports as it did and `held_out_hosts` says
  how many were held out. The pages are split at the sample before any is dropped for a missing recording, so a dropped
  page never moves a later one into the sample. `--validate same-page` keeps the old measure for comparison.
- Reversible: yes
