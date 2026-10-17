## MODIFIED Requirements

### Requirement: money
`normalize/money.py` SHALL return `{amount, currency}` only when the currency is stated (ISO code, or a sign resolved
through CLDR and page currencies); a sign several currencies share is `Ambiguous`, no sign is `Invalid`, and the
amount must be positive. A structured `price` written as display text is read as text under its `priceCurrency`, and
a sign it writes must denote that currency. A text's one amount is read through `numbers.stated`, as count and number
read theirs: none is `no_amount`, two are `range`. Refs: §9, D-0300–D-0306, D-1240, D-1370.
(Previously: money kept its own copy of the surrogate, NFKC and one-run steps.)
#### Scenario: Ambiguous dollar
- **WHEN** the text is `$10` with `html_lang="en"` and no page currency
- **THEN** the result is `Ambiguous`; with `page_currencies=("CAD",)` it is `Ok({amount: "10", currency: "CAD"})`
#### Scenario: Structured price with its sign
- **WHEN** a structured value is `{price: "$1,295.99", priceCurrency: "USD"}`
- **THEN** the result is `Ok({amount: "1295.99", currency: "USD"})`; with `price: "€12"` it is `Invalid`

### Requirement: date and datetime
`normalize/date.py` SHALL read ISO 8601 directly and other dates in every order the page locales allow, returning
`Ambiguous` when readings differ; a `datetime` needs a time and offset and outputs UTC. A zone named `UTC` or `GMT`
after the time, with or without a space, is zero offset; no other abbreviation is an offset. Refs: §9, D-0293–D-0299,
D-1371. (Previously: only a numeric offset or `Z`.)
#### Scenario: Day-month order unknown
- **WHEN** the text is `03/04/2026` with `html_lang="en"`
- **THEN** the result is `Ambiguous`
#### Scenario: Zone name
- **WHEN** a datetime text is `2026-10-15 09:31:36 UTC`; with `IST` in its place
- **THEN** the result is `Ok("2026-10-15T09:31:36Z")`; with `IST` it is `Invalid("no_offset")`

### Requirement: location as stated
`normalize/location.py` SHALL publish only what the page states: text as written (never split), structured parts as
written, a country only from an ISO 3166-1 alpha-2 code that the standard assigns (not its user-assigned ranges or
exceptional reservations such as `EU`), `remote_flag` `true` only when stated (`TELECOMMUTE`, or a `type:remote` phrase
that is a whole clause of the text) and `null` otherwise; no gazetteer. Refs: §9, D-0920, D-0953, D-1058, D-1272,
D-1372, D-1373. (Previously: `remote_flag` was `false` when unstated; CLDR's `EU`, `EZ` and `UN` were codes.)
#### Scenario: Unknown country code
- **WHEN** `addressCountry` is `"QZ"` or `"EU"`
- **THEN** the result is `Invalid("unknown_country")`
#### Scenario: Negated remote
- **WHEN** a location text is "Not remote"
- **THEN** `remote_flag` is null; "Lakeside, Remote" is true

### Requirement: range, count and number
`normalize/range.py`, `count.py` and `number.py` SHALL each accept one stated value and decline otherwise: a
monetary range without a period is `Ambiguous`; count and number decline on two numbers; number keeps digits as
written, and a schema.org `ratingValue` joined to a `reviewCount` of 0 is `Invalid("no_ratings")`. A count with
`unitCode` `C62` declines a `unitText` that names a CLDR measurement unit. All numbers are read in the CLDR locale set
of the page and request language tags (`numbers.py`), and locales that read a number differently give `Ambiguous`.
A minus negates a money or count text only when it touches the number. A monetary range's period is read from
`unitText`, else `unitCode`: a unit word, an interval of one unit (`1 YEAR`), an ISO 8601 duration of one unit (`P1Y`), a
UN/CEFACT code (`ANN`) or a `type:period` phrase. Refs: §9, D-0275–D-0279, D-0302, D-0921, D-0922, D-0960, D-1184,
D-1270, D-1271, D-1371. (Previously: only a unit word or a `type:period` phrase.)
#### Scenario: Rating with its scale
- **WHEN** a `number` text is "4.5 out of 5"
- **THEN** the result is `Invalid("several_numbers")`
#### Scenario: No reviews
- **WHEN** a `number` value is `{"ratingValue": 0, "reviewCount": 0}`
- **THEN** the result is `Invalid("no_ratings")`
#### Scenario: Spaced dash
- **WHEN** a `count` text is "In stock - 5 left"
- **THEN** the result is `Ok(5)`; "Stock: -5" is `Invalid("negative")`
#### Scenario: Unit beside one
- **WHEN** a `count` value is `{value: 5, unitCode: "C62", unitText: "kg"}`
- **THEN** the result is `Invalid("unit")`
#### Scenario: Interval as text
- **WHEN** a salary has `currency: "EUR"`, bounds `60000` to `80000` and `unitText: "1 YEAR"` (or `unitCode: "ANN"`)
- **THEN** the period is `YEAR`; with `unitText: "2 YEAR"` the range is `Ambiguous("period_missing")`
