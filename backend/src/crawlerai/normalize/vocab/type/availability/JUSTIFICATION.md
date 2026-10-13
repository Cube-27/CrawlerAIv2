# `type:availability`

Phrases that state an offer's availability, by language, each mapped to its schema.org `ItemAvailability` member.

| File | Language | Source | Content |
|---|---|---|---|
| `en.json` | `en` | schema.org `ItemAvailability` member names, de-camel-cased (SPEC-04 §4.4) | One phrase per member, nothing else. |

Any other phrase or language is added only under the C10 acceptance rule: a dev improvement and hidden
non-regression shown in the PR's evaluation report (ARCHITECTURE C4, C10). Record each addition here, with its
justification and the PR.
