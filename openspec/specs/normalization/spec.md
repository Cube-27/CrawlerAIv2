# Normalization Specification

## Purpose

Normalization turns a raw candidate into a typed value for its field type, or declines, with one pure normalizer
per type under `backend/src/crawlerai/normalize/`; it also gives per-type equality to the resolver and eval. Field
types are [schemas](../schemas/spec.md); what publishes is [resolution](../resolution/spec.md).

## Requirements

### Requirement: Result contract
`normalize(raw, spec, ctx)` SHALL be pure and return `Ok`, `Ambiguous(reason, options)` or `Invalid(reason)`,
never raising on bad input; every rule names its standard or structural property in a comment (C2). Refs: §9, D-0254.
#### Scenario: Same input twice
- **WHEN** `normalize` is called twice with the same raw value and context
- **THEN** it returns the same result

### Requirement: Context is page and request evidence only
`Context` (`normalize/base.py`) SHALL hold only evidence from the page and the request; `None` means no evidence,
never a default. Its `hreflang` holds the languages of the alternate links to the page itself (its final URL or
canonical link, HTML §4.6.7.1, RFC 6596; `content/context.py`). (Previously: every alternate link's `hreflang`.)
Refs: §9, D-0256, D-0773, D-1482.
#### Scenario: No context
- **WHEN** a context carries only `captured_at`
- **THEN** no normalizer supplies a locale, currency or country of its own
#### Scenario: Alternates in other territories
- **WHEN** a page tagged `en-US` has alternate links to other pages tagged `en-AU` and `en-CA`
- **THEN** `$10` on it normalizes to USD

### Requirement: Decline rather than guess (INV-06)
A normalizer SHALL NOT return `Ok` for empty or whitespace-only input, map an ambiguous symbol without context, read
a host table, or apply a default (C7). Enforced by: Hypothesis property tests per type; active.
#### Scenario: Empty input
- **WHEN** any type's normalizer gets `"   "`
- **THEN** the result is `Invalid`

### Requirement: One module per type (INV-08)
Exactly one module SHALL handle each field type (see `normalize/dispatch.py`); shared CLDR number reading lives in
`normalize/numbers.py`, and only `normalize.*` imports Babel, price-parser and dateparser. Refs: C8, D-0255, D-0922.
Enforced by: import-linter contracts in `backend/.importlinter`; active.

### Requirement: Derived values marked
A derived value SHALL fill only an empty field, carry `derived_by`, and come from a named function with a standards
justification ([resolution](../resolution/spec.md)). Refs: Appendix A #40, D-0355.

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

### Requirement: enum and the first-clause rule (INV-37)
`normalize/enum.py` SHALL match `schema:` members by IRI or name exactly, and otherwise read only the text's first
clause, which must equal a member phrase as a whole; extra words decline, never substring match. Refs: §9, D-0271–D-0274, D-0882, D-0920.
Enforced by: `tests/property/test_normalize_enum.py` and `tests/replay/test_replay_stock.py`; active.
#### Scenario: Qualified phrase
- **WHEN** availability text is "Not in stock", "In stock soon" or "5 in stock"
- **THEN** the result is `Invalid`; "In stock (5 available)" is `Ok("InStock")`

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

### Requirement: identifier, text and url
`normalize/identifier.py` SHALL check GTIN and ISBN check digits and publish the identifier as a string, the scheme being
the field's (D-1209); `text.py` cleans text and declines templates; `url.py` parses per WHATWG, absolutizes,
canonicalizes and declines non-http(s) or hostless URLs, never repairing. Refs: §9, D-0287–D-0290, D-0257–D-0263, D-1022, D-1209.
#### Scenario: Check digit fails
- **WHEN** one digit of a valid GTIN-13 is changed
- **THEN** the result is `Invalid("check_digit")`

### Requirement: list and object
A list SHALL be `Ok` when at least one item normalizes, reporting dropped items; an object declines when a required
sub-field declines (`normalize/dispatch.py`). Refs: D-0325, D-0326.

### Requirement: Equality per type
`equal(a, b, spec)` SHALL be reflexive and symmetric for any JSON value, comparing each type's normalized form
(GTINs zero-padded to 14 digits). Refs: D-0322–D-0324, D-0960.
#### Scenario: GTIN padding
- **WHEN** a GTIN-13 is compared with the same number zero-padded to 14 digits
- **THEN** they are equal

### Requirement: Versioned vocabulary data
Vocabularies SHALL be language-tagged files under `normalize/vocab/`, each with a `JUSTIFICATION.md`, grown only
under the C10 rule; the schema.org file is a sha256-checked `backend/data/manifest.json` entry. Refs: C4, D-0018.
