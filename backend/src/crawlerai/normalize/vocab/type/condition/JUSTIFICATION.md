# `type:condition`

Phrases that state an offered item's condition, by language, each mapped to its schema.org `OfferItemCondition`
member.

| File | Language | Source | Content |
|---|---|---|---|
| `en.json` | `en` | schema.org `OfferItemCondition` member names, de-camel-cased, with and without the word "condition" every member's name shares with the enumeration's | Two phrases per member, nothing else. |

Any other phrase or language is added only under the C10 acceptance rule: an e2e improvement
with no precision drop, shown in the PR's evaluation report. Record each addition here, with its
justification and the PR.
