# Delta: normalization

## MODIFIED Requirements

### Requirement: range, count and number
`normalize/range.py`, `count.py` and `number.py` SHALL each accept one stated value and decline otherwise: a
monetary range without a period is `Ambiguous`; count and number decline on two numbers; number keeps digits as
written, and a schema.org `ratingValue` joined to a `reviewCount` of 0 is `Invalid("no_ratings")`. All numbers are
read in the CLDR locale set of the page and request language tags (`numbers.py`), and locales that read a number
differently give `Ambiguous`. (Previously: a rating of nothing published.) Refs: §9, D-0275–D-0279, D-0302, D-0921,
D-0922, D-0960, D-1184.
#### Scenario: Rating with its scale
- **WHEN** a `number` text is "4.5 out of 5"
- **THEN** the result is `Invalid("several_numbers")`
#### Scenario: No reviews
- **WHEN** a `number` value is `{"ratingValue": 0, "reviewCount": 0}`
- **THEN** the result is `Invalid("no_ratings")`
