# `type:availability`

Phrases that state an offer's availability, by language, each mapped to its schema.org `ItemAvailability` member.

| File | Language | Source | Content |
|---|---|---|---|
| `en.json` | `en` | schema.org `ItemAvailability` member names, de-camel-cased (normalization spec) | One phrase per member, nothing else. |

Any other phrase or language is added only under the C10 acceptance rule: an e2e improvement
with no precision drop, shown in the PR's evaluation report. Record each addition here, with its
justification and the PR.
