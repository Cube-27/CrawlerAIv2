# `type:period`

Phrases that state the period of a salary range, by language, each mapped to the schema.org `unitText` value it
names. The range normalizer reads a period only from one of these phrases, or from the solidus form
`/<unit>`, where `<unit>` is the phrase's last word (the SI Brochure and ISO 80000-1 write a quotient of units, "per", with a solidus).

| File | Language | Source | Content |
|---|---|---|---|
| `en.json` | `en` | schema.org `unitText` for a salary period (`HOUR`, `DAY`, `WEEK`, `MONTH`, `YEAR`, the `baseSalary` guidance on `JobPosting`), lowercased after "per" | One phrase per unit, nothing else. Moved here from `range.py`. |

Any other phrase or language is added only under the C10 acceptance rule: an e2e improvement
with no precision drop, shown in the PR's evaluation report. Record each addition here, with its
justification and the PR.
