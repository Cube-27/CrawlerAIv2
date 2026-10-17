## MODIFIED Requirements

### Requirement: range, count and number
`normalize/range.py`, `count.py` and `number.py` SHALL each accept one stated value and decline otherwise: a
monetary range without a period is `Ambiguous`; count and number decline on two numbers; number keeps digits as
written, and a schema.org `ratingValue` joined to a `reviewCount` of 0 is `Invalid("no_ratings")`. A count with
`unitCode` `C62` declines a `unitText` that names a CLDR measurement unit. All numbers are read in the CLDR locale set
of the page and request language tags (`numbers.py`), and locales that read a number differently give `Ambiguous`.
A minus negates a money or count text only when it touches the number. Refs: §9, D-0275–D-0279, D-0302, D-0921, D-0922, D-0960, D-1184, D-1270, D-1271.
(Previously: a minus anywhere before the number negated it, and any `unitText` beside `C62` passed.)
#### Scenario: Spaced dash
- **WHEN** a `count` text is "In stock - 5 left"
- **THEN** the result is `Ok(5)`; "Stock: -5" is `Invalid("negative")`
#### Scenario: Unit beside one
- **WHEN** a `count` value is `{value: 5, unitCode: "C62", unitText: "kg"}`
- **THEN** the result is `Invalid("unit")`

### Requirement: location as stated
`normalize/location.py` SHALL publish only what the page states: text as written (never split), structured parts as
written, a country only from a valid ISO 3166-1 code, `remote_flag` only when stated (`TELECOMMUTE`, or a `type:remote`
phrase that is a whole clause of the text); no gazetteer. Refs: §9, D-0920, D-0953, D-1058, D-1272.
(Previously: the phrase counted anywhere in the text, so "not remote" was remote.)
#### Scenario: Unknown country code
- **WHEN** `addressCountry` is `"QZ"`
- **THEN** the result is `Invalid("unknown_country")`
#### Scenario: Negated remote
- **WHEN** a location text is "Not remote"
- **THEN** `remote_flag` is false; "Lakeside, Remote" is true
