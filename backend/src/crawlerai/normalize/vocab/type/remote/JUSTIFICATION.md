# `type:remote`

Phrases that state a job is done away from any work site, by language. A match sets a location's `remote_flag`
(SPEC-04 §4.4); a missing location never does.

| File | Language | Source | Content |
|---|---|---|---|
| `en.json` | `en` | schema.org `jobLocationType`: "A description of the job location (e.g. TELECOMMUTE for telecommute jobs)", and `TELECOMMUTE`'s meaning, remote work (SPEC-04 §4.4) | The one phrase "remote". |

Any other phrase or language is added only under the C10 acceptance rule: a dev improvement and hidden
non-regression shown in the PR's evaluation report (ARCHITECTURE C4, C10). Record each addition here, with its
justification and the PR.
