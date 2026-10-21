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
canonical link, HTML §4.6.7.1, RFC 6596; `content/context.py`); `page_url` and `request_url` are the final and the
requested URL. (Previously: every alternate link's `hreflang`.)
Refs: §9, D-0256, D-0773, D-1482.
#### Scenario: No context
- **WHEN** a context carries only `captured_at`
- **THEN** no normalizer supplies a locale, currency or country of its own
#### Scenario: Declared locale settles a separator
- **WHEN** a number text is `1.250` and the page declares `de` (or `de-AT`) it is 1250; declaring `en-GB` it is 1.250;
  declaring nothing it is `Ambiguous`; `1.250,5` is 1250.5 under any declaration
#### Scenario: Alternates in other territories
- **WHEN** a page tagged `en-US` has alternate links to other pages tagged `en-AU` and `en-CA`
- **THEN** `$10` on it normalizes to USD

### Requirement: Decline rather than guess (INV-06)
A normalizer SHALL NOT return `Ok` for empty or whitespace-only input, map an ambiguous symbol without context, read
a host table, or apply a default (C7). Money is the one exception to declining: a grounded amount publishes with its
currency unknown (`null`) rather than decline, and never with a currency nothing on the page or its URL names (owner
#68, owner 2026-10-19).
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
`currency`, `currencyCode` or `activeCurrency` holding an ISO 4217 code, and, on a page showing its platform's
signal, the platform's documented currency global: Shopify `Shopify.currency.active`, Shopware
`window.currencyIsoCode` (`adapters/platforms.py` `currency_members`); `collect/currencies.py`); (4) the CLDR
currency symbols of the locales the page's language tags, Content-Language (RFC 9110 §8.5, its HTML pragma) and ccTLD
(RFC 1591, a CLDR territory or its CLDR alias: `uk` is GB) name, when they narrow a shared sign to one currency; (5)
the territory the URL names (owner 2026-10-19, `url_currency`): of the final URL, then the requested one, a locale
path segment (`/en-gb/`: language then region, the language used in the region per CLDR territory languages), else a
country subdomain (`in.`: a first label of two letters that is a CLDR territory, two more labels following), else the
ccTLD (a CLDR alias counts in each: `uk` is GB); the first URL and step that names a territory decides, and it names a currency only when it names one territory,
one of the page's stated languages (if any) is used there, and CLDR gives it one tender currency on the capture date;
(6) else `null`. A shared sign is narrowed by (2), then (3), then (4), then (5), each step keeping what the last
left; an amount written without any sign takes the page's currency when (2) and (3) together name exactly one, else
the URL's (5), else `null`. A generic TLD, several locale segments, and a URL territory the page's language
contradicts name none. No host table. `Ok.basis` notes the evidence of a currency below (2): `page`, `locale`, `url`
or `unknown`; `Ok.checked` is false for a text without a sign, which only a
grounded source may publish (extraction spec). Two signs that share no currency, or a sign that cannot denote the
structured `priceCurrency`, contradict each other and are `Invalid`; amounts the locales read differently are
`Ambiguous`, and the amount must be positive. A text's one amount is read through `numbers.stated`, as count and
number read theirs: none is `no_amount`, two are `range`; a number written with a CLDR percent sign is a ratio (a
discount), never the amount: a ratio's digits are not grouped by white space (`12.99 20%` is a price and a ratio) and
a percent sign followed by digits opens the next number (`12.99 %20`). A CLDR compact decimal unit of the page's locales written right after the digits
multiplies them (`decimalFormats-short`: `3.5万円` is 35000), and a currency's one-word CLDR count name (`円`) is a
sign like its symbol. A sign written with a trailing full stop is also the CLDR symbol without it (an abbreviation's
full stop: CLDR itself writes `kr` and `kr.`), so it denotes both symbols' currencies for (2)–(4) to narrow; the
symbol table and the written sign both take each symbol's forms with and without the bidi controls CLDR writes in it
(U+200E, U+200F, U+061C) and without its trailing full stop (`ر.س.‏` and `ر.س` are SAR), the longest form written
winning. A text reading with more decimal places than the ISO 4217 minor unit of the currency it resolves to (Babel
`get_currency_precision`, trailing zeros counted) is no amount of it: such readings are dropped, and a text left with
none is `Invalid("minor_unit")` (`$10.999` with USD is not 10.999; `¥1,234` in JPY is 1234). A
monetary range keeps declining on a `null` currency, and on one only the URL names (`currency_unknown`: a range has
no basis to flag it). A label whose currency only the URL names is declined, as one whose currency is `null`. An
amount followed by a CLDR per pattern and a unit of the page's or the root locale's CLDR unit data
(`normalize/units.py`: a unit's own per pattern, `{0}/kg`, or the compound per pattern, `{0}/{1}`, `{0} per {1}`,
with a unit name, a count before it allowed: `per 100 ml`; a form of two letters or more in any case, a one-letter
symbol only as CLDR writes it and right after the separator or a count, `$40/M` but not `$40 / M`, a size) prices a
unit or a period: for a field whose path gives it
the active-price role (schemas spec, "Presets") it is `Invalid("per_unit")` (mass, volume, length, area, item) or
`Invalid("per_period")` (duration); any other money field reads the amount before the pattern (`unit_price`: `€25/kg`
is 25). A sign written as an ISO 4217 code or a CLDR currency symbol that is also a unit name or symbol of the
CLDR unit data of the root locale or a locale the page or the request states (`CUP`, the volume `cup`; `L`, the litre
and a symbol of the lempira and the leu; a one-letter sign in either case, CLDR writing the litre `l` and `L` by
locale) is a currency only where the page names a currency it denotes (its structured, declared or URL currency, or
the tender currency of a territory its own locales, not the request's, leave possible); else the text states a
measure, not an amount: `Invalid("measure")` (`3.5 CUP FOOD CHOPPER`, `Kettle 1,7 L`). Refs: §9, owner #68, owner 2026-10-19, D-1240, D-1370, D-1782, architecture-v3 d.2, d.4, d.7.
(Previously: a sign several currencies share was `Ambiguous`, no sign was `Invalid`, a page currency never supplied a
missing sign, the locale settled a sign at full confidence, and a sign with a full stop denoted only its own symbol's
currencies, and the URL never supplied a currency; an amount per unit or per period read as the price; a symbol
written without CLDR's bidi controls was not that symbol, no platform global declared a currency, and a reading was
kept whatever its currency's minor unit; a code that is also a unit name read as a currency, and a CLDR symbol that is
also a unit symbol, `L`, still did.)
#### Scenario: Per unit and per period
- **WHEN** the text is `€25/kg` or `$25/mo` for the `commerce_detail` `price` with `html_lang="en"`
- **THEN** the results are `Invalid("per_unit")` and `Invalid("per_period")`; for a `unit_price` field mapped to
  `Offer.priceSpecification{referenceQuantity}.price+priceCurrency`, `€25/kg` is `Ok({amount: "25", currency: "EUR"})`
#### Scenario: A volume in a name
- **WHEN** the text is `Kettle 1,7 L` with `html_lang="pt-BR"`
- **THEN** the result is `Invalid("measure")`; on a page whose locale is `es-HN`, `L 120` is `Ok({amount: "120", currency: "HNL"})`
#### Scenario: Ambiguous dollar
- **WHEN** the text is `$10` with `html_lang="en"` and no page currency
- **THEN** the result is `Ok({amount: "10", currency: null})` with basis `unknown`; with `page_currencies=("CAD",)` it
  is `Ok({amount: "10", currency: "CAD"})`; with `html_lang="en-AU"` it is AUD with basis `locale`
#### Scenario: A price without a sign
- **WHEN** the text is `12` and the page declares only `og:price:currency` SEK
- **THEN** the result is `Ok({amount: "12", currency: "SEK"})` with basis `page`, not `checked`; with a second
  currency stated elsewhere on the page the currency is `null`
#### Scenario: A currency from the URL
- **WHEN** a structured value is `{price: "12"}` with no currency on the page, at `https://shop.example.com/en-gb/p`
  (or `gb.example.com`, or a `.uk` host)
- **THEN** the result is `Ok({amount: "12", currency: "GBP"})` with basis `url`; with `priceCurrency: "EUR"` it is EUR,
  and at `https://shop.example.com/p` the currency is `null`
#### Scenario: Structured price with its sign
- **WHEN** a structured value is `{price: "$1,295.99", priceCurrency: "USD"}`
- **THEN** the result is `Ok({amount: "1295.99", currency: "USD"})`; with `price: "€12"` it is `Invalid`
#### Scenario: An abbreviation's full stop
- **WHEN** the text is `kr. 12` and the page's structured data states NOK
- **THEN** the result is `Ok({amount: "12", currency: "NOK"})`, `kr.` also being the symbol `kr`
#### Scenario: Bidi controls and minor units
- **WHEN** the text is `ر.س 120` or `ر.س.‏120` with `html_lang="ar-SA"`; or `¥1,234` with `page_currencies=("JPY",)`;
  or `$10.999` with no page evidence, then with `html_lang="en-US"`
- **THEN** the results are `Ok({amount: "120", currency: "SAR"})`, `Ok({amount: "1234", currency: "JPY"})`,
  `Ambiguous` (10.999 or 10999, currency `null`), then `Invalid("minor_unit")`
#### Scenario: CJK units and a discount beside the price
- **WHEN** the text is `3.5万円` with `html_lang="ja"`, or `$12.99 -20%` with `html_lang="en-US"`
- **THEN** the results are `Ok({amount: "35000", currency: "JPY"})` and `Ok({amount: "12.99", currency: "USD"})`

### Requirement: enum and the first-clause rule (INV-37)
`normalize/enum.py` SHALL match `schema:` members by IRI or name exactly, and otherwise read only the text's first
clause, which must equal a member phrase as a whole; extra words decline, never substring match. An IRI on the
schema.org host names its term also as a network-path reference (`//schema.org/InStock`, RFC 3986 §4.2) and with its
scheme or host in any case (RFC 3986 §3.1, §3.2.2); its term names a member in another case (`instock`) when exactly one
member has that name. (Previously: only `https://schema.org/`, `http://schema.org/` and `schema:` exactly, the member
name exactly.) Refs: §9, D-0271–D-0274, D-0882, D-0920.
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
monetary range without a period is `Ambiguous`, except a schema.org AggregateOffer's `lowPrice` and `highPrice`
(a price range: no period), each bound read as an Offer's `price` with its `priceCurrency`; count and number decline on two numbers; number keeps digits as
written, and a schema.org `ratingValue` joined to a `reviewCount` of 0 is `Invalid("no_ratings")`. A count with
`unitCode` `C62` declines a `unitText` that names a CLDR measurement unit. All numbers (money, count, number) are read by the one path in `numbers.py`: a written number that only one CLDR number
convention can read (`1.234,56`, `12.50`) has that one value whatever the page says; one that conventions read
differently (`1.234`, `1,234`) takes the value its declared locales give it (none when no declared locale reads it),
then, of those locales' conventions (every convention when it declares none), the value of the ones whose decimal
symbol is the page's own (`Context.page_convention`: the one decimal symbol every structured `price` the page
writes with a fraction uses where one CLDR convention alone reads it, a JSON number's being `.`;
`collect/currencies.py`), and is `Ambiguous` when those still read it differently or the page states neither. A
locale's conventions are its `latn` symbols and, when its default or native CLDR numbering system is `arab` or
`arabext`, that system's (U+066B decimal, U+066C group separator); any Unicode decimal digits read as their values
(`١٬٢٣٤٫٥٠` in `ar-EG` is 1234.50). A group symbol is also read in the forms pages write for it: U+2019 and the ASCII
apostrophe for each other (`1'234.50` in `de-CH`), any space separator for a space symbol (U+00A0, U+202F). The declared locales are `<html lang>`, `og:locale`, JSON-LD `inLanguage`
(`Context.in_language`), Content-Language (RFC 9110 §8.5, its HTML pragma), the page's own `hreflang` and the request's
locale; a tag with a territory is that CLDR locale, a tag with a language only is the language's own CLDR locale (`de`
writes `1.234,5`), and the ccTLD narrows a language-only tag only where money reads it (the currency step 4).
A minus negates a money or count text only when it touches the number. A monetary range's period is read from
`unitText`, else `unitCode`: a unit word, an interval of one unit (`1 YEAR`), an ISO 8601 duration of one unit (`P1Y`), a
UN/CEFACT code (`ANN`) or a `type:period` phrase. Refs: §9, D-0275–D-0279, D-0302, D-0921, D-0922, D-0960, D-1184,
D-1270, D-1271, D-1371, architecture-v3 d.1, d.4. (Previously: only a unit word or a `type:period` phrase; an
AggregateOffer was not a range value; only `latn` symbols and digits, the CLDR group symbol only as written, and no
page convention.)
#### Scenario: Page convention
- **WHEN** a page's JSON-LD writes `price` `"19.99"` and its text writes `1.234` with no declared locale
- **THEN** the text reads 1.234; with the JSON-LD prices `"19.99"` and `"1.234,56"` it is `Ambiguous`
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
size statement holds (the path's size parts, and decimal values of query parameters every rendition states that differ
between them), ranked only when every rendition states one, else the first. A `%3F` written into the path ends the
file's name (`same_file`). (Previously: renditions of one file were kept as separate items.)
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
