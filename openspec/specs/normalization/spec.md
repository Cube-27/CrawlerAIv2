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
a host table, or apply a default (C7). Money is the one exception to declining: a grounded amount publishes with its
currency unknown (`null`) rather than decline, and never with a currency nothing on the page names (owner #68).
(Previously: an ambiguous currency sign declined.) Enforced by: Hypothesis property tests per type; active.
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
`normalize/money.py` SHALL return `{amount, currency}` for every grounded positive amount (owner #68: a price is never
skipped for its currency), the currency from the best evidence, in order: (1) an ISO 4217 code or a sign written with
the amount that denotes one currency (CLDR symbols), or the value's own structured `priceCurrency`/`currency`;
(2) the page's structured data (schema.org `priceCurrency`, `page_currencies`); (3) a page-level declaration
(`declared_currencies`: OGP `og:price:currency` and `product:price:currency`, and a state JSON member named
`currency`, `currencyCode` or `activeCurrency` holding an ISO 4217 code; `collect/currencies.py`); (4) the CLDR
currency symbols of the locales the page's language tags, Content-Language (RFC 9110 §8.5, its HTML pragma) and ccTLD
(RFC 1591, a CLDR territory) name, when they narrow a shared sign to one currency; (5) else `null`. A shared sign is
narrowed by (2), then (3), then (4), each step keeping what the last left; an amount written without any sign takes
the page's currency only when (2) and (3) together name exactly one, else `null`. `Ok.basis` notes the evidence of a
currency below (2): `page`, `locale` or `unknown`; `Ok.checked` is false for a text without a sign, which only a
grounded source may publish (extraction spec). Two signs that share no currency, or a sign that cannot denote the
structured `priceCurrency`, contradict each other and are `Invalid`; amounts the locales read differently are
`Ambiguous`, and the amount must be positive. A text's one amount is read through `numbers.stated`, as count and
number read theirs: none is `no_amount`, two are `range`; a number written with a CLDR percent sign is a ratio (a
discount), never the amount. A CLDR compact decimal unit of the page's locales written right after the digits
multiplies them (`decimalFormats-short`: `3.5万円` is 35000), and a currency's one-word CLDR count name (`円`) is a
sign like its symbol. A monetary range keeps declining on a `null` currency
(`currency_unknown`). Refs: §9, owner #68, D-1240, D-1370.
(Previously: a sign several currencies share was `Ambiguous`, no sign was `Invalid`, a page currency never supplied a
missing sign, and the locale settled a sign at full confidence.)
#### Scenario: Ambiguous dollar
- **WHEN** the text is `$10` with `html_lang="en"` and no page currency
- **THEN** the result is `Ok({amount: "10", currency: null})` with basis `unknown`; with `page_currencies=("CAD",)` it
  is `Ok({amount: "10", currency: "CAD"})`; with `html_lang="en-AU"` it is AUD with basis `locale`
#### Scenario: A price without a sign
- **WHEN** the text is `12` and the page declares only `og:price:currency` SEK
- **THEN** the result is `Ok({amount: "12", currency: "SEK"})` with basis `page`, not `checked`; with a second
  currency stated elsewhere on the page the currency is `null`
#### Scenario: Structured price with its sign
- **WHEN** a structured value is `{price: "$1,295.99", priceCurrency: "USD"}`
- **THEN** the result is `Ok({amount: "1295.99", currency: "USD"})`; with `price: "€12"` it is `Invalid`
#### Scenario: CJK units and a discount beside the price
- **WHEN** the text is `3.5万円` with `html_lang="ja"`, or `$12.99 -20%` with `html_lang="en-US"`
- **THEN** the results are `Ok({amount: "35000", currency: "JPY"})` and `Ok({amount: "12.99", currency: "USD"})`

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
written, a structured place's text being its `name` and `streetAddress` lines then its locality, region, country name
and postal code (the HTML Standard's autofill order), each part once and a country code never in it, a country only from an ISO 3166-1 alpha-2 code that the standard assigns (not its user-assigned ranges or
exceptional reservations such as `EU`), `remote_flag` `true` only when stated (`TELECOMMUTE`, or a `type:remote` phrase
that is a whole clause of the text) and `null` otherwise; no gazetteer. Refs: §9, D-0920, D-0953, D-1058, D-1272,
D-1372, D-1373. (Previously: `remote_flag` was `false` when unstated; CLDR's `EU`, `EZ` and `UN` were codes.)
#### Scenario: Structured place text
- **WHEN** a `Place` named "Old Hall" has `streetAddress` "1 Mill Lane, Alderton, UF 12345", `addressLocality`
  "Alderton", `addressRegion` "UF" and `addressCountry` "US"
- **THEN** its text is "Old Hall, 1 Mill Lane, Alderton, UF 12345" and its country `US`
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
canonicalizes and declines non-http(s) or hostless URLs, never repairing; an `image_url` whose path names a file of a
registered media type other than an image by its extension (RFC 6838: an HTML page, a video, a script) is
`Invalid("not_an_image")`, and a path with no registered extension says nothing. (Previously: any http(s) URL but the
page's was an image.) Refs: §9, D-0287–D-0290, D-0257–D-0263, D-1022, D-1209.
#### Scenario: Check digit fails
- **WHEN** one digit of a valid GTIN-13 is changed
- **THEN** the result is `Invalid("check_digit")`

### Requirement: list and object
A list SHALL be `Ok` when at least one item normalizes, reporting dropped items; an object declines when a required
sub-field declines (`normalize/dispatch.py`). A list of `image_url` items names each file (`resource_key`) once, at its
first rendition's place, as its largest rendition over `https` (`url.distinct_files`): the largest number a rendition's
size statement holds (the path's size parts, and decimal query values that differ between the renditions), ranked only
when every rendition states one, else the first. (Previously: renditions of one file were kept as separate items.)
Refs: D-0325, D-0326, D-1665.
#### Scenario: One image in four widths
- **WHEN** a list states one image file at widths 100, 300, 600 and 900
- **THEN** it normalizes to the one width-900 URL

### Requirement: Equality per type
`equal(a, b, spec)` SHALL be reflexive and symmetric for any JSON value, comparing each type's normalized form
(GTINs zero-padded to 14 digits). Refs: D-0322–D-0324, D-0960.
#### Scenario: GTIN padding
- **WHEN** a GTIN-13 is compared with the same number zero-padded to 14 digits
- **THEN** they are equal

### Requirement: Versioned vocabulary data
Vocabularies SHALL be language-tagged files under `normalize/vocab/`, each with a `JUSTIFICATION.md`, grown only
under the C10 rule; the schema.org file is a sha256-checked `backend/data/manifest.json` entry. Refs: C4, D-0018.
