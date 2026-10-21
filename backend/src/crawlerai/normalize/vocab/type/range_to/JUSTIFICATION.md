# `type:range_to`

Words that separate the two bounds of a written range, by language. The one code, `TO`, stands for the separator; the
range normalizer reads it only between two amounts. The hyphen-minus and the en dash (U+2013, the range dash) are no
language's words, so they stay in `range.py`.

| File | Language | Source | Content |
|---|---|---|---|
| `en.json` | `en` | The separator normalization spec names for written ranges ("10 to 20") | One word. Moved here from `range.py`. |

Any other word or language is added only under the C10 acceptance rule: an e2e improvement
with no precision drop, shown in the PR's evaluation report. Record each addition here, with its
justification and the PR.
