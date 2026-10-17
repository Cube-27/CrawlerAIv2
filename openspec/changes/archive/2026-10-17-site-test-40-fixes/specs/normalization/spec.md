# Delta: normalization

## MODIFIED Requirements

### Requirement: money
`normalize/money.py` SHALL return `{amount, currency}` only when the currency is stated (ISO code, or a sign resolved
through CLDR and page currencies); a sign several currencies share is `Ambiguous`, no sign is `Invalid`, and the
amount must be positive. A structured `price` written as display text is read as text under its `priceCurrency`, and
a sign it writes must denote that currency. (Previously: a structured `price` other than schema.org's digits was
`Invalid`.) Refs: §9, D-0300–D-0306, D-1240.
#### Scenario: Ambiguous dollar
- **WHEN** the text is `$10` with `html_lang="en"` and no page currency
- **THEN** the result is `Ambiguous`; with `page_currencies=("CAD",)` it is `Ok({amount: "10", currency: "CAD"})`
#### Scenario: Structured price with its sign
- **WHEN** a structured value is `{price: "$1,295.99", priceCurrency: "USD"}`
- **THEN** the result is `Ok({amount: "1295.99", currency: "USD"})`; with `price: "€12"` it is `Invalid`
