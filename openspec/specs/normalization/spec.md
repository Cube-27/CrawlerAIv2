# Normalization Specification

## Purpose

Normalization turns a raw candidate value (a string from the DOM or an LLM, or a JSON value from structured data)
into a typed value for its field type, or declines. There is one pure normalizer per field type, and the only
evidence it reads is the page and the request. It also provides per-type equality for the resolver and eval. Field
types and schema rules are [schemas](../schemas/spec.md); what publishes is [resolution](../resolution/spec.md).
Design rationale: [ARCHITECTURE §9](../../design/normalization.md). History: [SPEC-04](../../changes/archive/2026-10-16-spec-04-schemas-and-normalization/SPEC-04-schemas-and-normalization.md) and its [decisions](../../changes/archive/2026-10-16-spec-04-schemas-and-normalization/decisions.md).

## Requirements

### Requirement: Result contract
`normalize(raw, spec, ctx)` SHALL return `Ok(value)`, `Ambiguous(reason, options)` or `Invalid(reason)`, and SHALL
be pure (no I/O, no clock). It SHALL NOT raise on bad input; a spec of the wrong type raises `TypeError`, and an
unknown type returns `Invalid("unknown_type")`. Every rule SHALL carry a comment naming its standard or structural
property (C2).
Refs: §9, SPEC-04 §4.3, §4.7, D-0254.

#### Scenario: Same input twice
- **WHEN** `normalize` is called twice with the same raw value and context
- **THEN** it returns the same result

### Requirement: Context is page and request evidence only
`Context` SHALL hold only `html_lang`, `og_locale`, `hreflang`, `page_currencies` (ISO 4217 codes the page writes
in schema.org `priceCurrency` or OGP `product:price:currency`), `cctld_territory` (via CLDR territory data),
`request_locale`, `captured_at`, `base_url` and `page_url`. `None` SHALL mean no evidence, never a default.
Refs: §9, SPEC-04 §4.3, D-0256, D-0773.

#### Scenario: No context
- **WHEN** a context carries only `captured_at`
- **THEN** no normalizer supplies a locale, currency or country of its own

### Requirement: Decline rather than guess (INV-06)
A normalizer SHALL NOT return `Ok` for empty or whitespace-only input, map an ambiguous symbol without context,
read a host table, or apply a default (C7). Enforced by: Hypothesis property tests per type; status: SPEC-04.
Refs: §9, C7, SPEC-04 §5, §6.

#### Scenario: Empty input
- **WHEN** any type's normalizer gets `"   "`
- **THEN** the result is `Invalid`

### Requirement: One module per type (INV-08)
Exactly one module SHALL handle each field type (`long_text` in `text`, `image_url` in `url`, `datetime` in
`date`; `list` and `object` by recursion in the dispatcher); CLDR number reading is shared in `normalize.numbers`.
Only `normalize.*` SHALL import Babel, price-parser and dateparser. Enforced by: import-linter contracts
(`backend/.importlinter`); status: active (CI `backend`, `lint-imports`).
Refs: C8, SPEC-04 §4.1, D-0016, D-0255, D-0922.

#### Scenario: Range needs money rules
- **WHEN** `range` resolves a currency
- **THEN** it calls the money rules through the dispatcher, never by importing `money`

### Requirement: No defaults; derived values marked
Normalizers SHALL apply no defaults. A derived value SHALL fill only an empty field, carry `derived_by`, and come
from a named function with a standards justification (see [resolution](../resolution/spec.md)).
Refs: §9, Appendix A #40, D-0355.

#### Scenario: Field already filled
- **WHEN** a field has a published value
- **THEN** no derivation replaces it

### Requirement: money
Money SHALL normalize to `{amount, currency}` from text, schema.org `price` + `priceCurrency`, or `amount` +
`currency`; a structured currency must be an uppercase ISO 4217 code Babel lists. In text, the amount is the one
digit run under CLDR separators and the sign is resolved through CLDR symbols: an ISO code names itself; else
`page_currencies` the sign stands for; else the locale set's currencies; one is `Ok`, several `Ambiguous`. Text
without a sign SHALL be `Invalid("no_currency")` even with one page currency. Signs on both sides must agree
(`currency_conflict`). The amount SHALL be positive, below 10^12 with at most 6 fraction digits, digits kept as
written; two amounts are `Invalid("range")`.
Refs: §9, SPEC-04 §4.4, D-0300–D-0306.

#### Scenario: Ambiguous dollar
- **WHEN** the text is `$10` with `html_lang="en"` and no page currency
- **THEN** the result is `Ambiguous` with options including USD, CAD, AUD

#### Scenario: Page currency settles the sign
- **WHEN** the text is `$10` and `page_currencies` is `("CAD",)`
- **THEN** the result is `Ok({amount: "10", currency: "CAD"})`

#### Scenario: Not positive
- **WHEN** the text is `-5 €` or `0 EUR`
- **THEN** the result is `Invalid`

### Requirement: Locale set for numbers
The locale set SHALL come from `html_lang`, `og_locale`, `request_locale` and `hreflang` (a tag with a territory as
is; a language-only tag as `language_ccTLD` when CLDR has it, else every CLDR locale of the language), then the
ccTLD's territory when no tag is known, else every CLDR locale. A number the locales read differently SHALL be
`Ambiguous`.
Refs: §9, SPEC-04 §4.4, D-0302, D-0922.

#### Scenario: Ambiguous separator
- **WHEN** the text is `1.234 €` and the locale set mixes decimal-point and decimal-comma locales
- **THEN** the result is `Ambiguous`

### Requirement: enum and the first-clause rule (INV-37)
`schema:` enums SHALL match a member IRI (`https://schema.org/InStock`) or member name exactly and case-sensitively.
Other text, and `type:` vocabularies, SHALL be read by its first clause (from the first letter through Unicode L,
M, Zs, Pd, Pc to the first other character; a leading digit leaves it empty): its tokens (NFKC, casefolded) must
equal a member's phrase or, for `schema:`, its name (`instock`). A clause with any other word SHALL NOT normalize to
the member; another member's phrase later is `Ambiguous`; no clause match is `Invalid`. Never substring order.
Vocabularies are language-tagged, read in the page's languages (all when none stated), and the `en` availability
phrases are the de-camel-cased `ItemAvailability` names. Enforced by: property tests
(`tests/property/test_normalize_enum.py`) and replay (`tests/replay/test_replay_stock.py`); status: active.
Refs: §9, Appendix A #39, SPEC-04 §4.4, D-0271–D-0274, D-0882, D-0920.

#### Scenario: Qualified phrase
- **WHEN** availability text is "Not in stock", "In stock soon" or "5 in stock"
- **THEN** the result is `Invalid`, never `InStock`

#### Scenario: Stated with a count
- **WHEN** availability text is "In stock (5 available)" or `instock`
- **THEN** the result is `Ok("InStock")`

### Requirement: date and datetime
ISO 8601 / RFC 3339 input SHALL parse directly; numeric dates are read in each date order the CLDR locales of
`html_lang` and `og_locale` allow, and differing readings are `Ambiguous`; worded dates use `dateparser` in the
page language. Relative dates need `captured_at`. Years outside 1970–2100 are `Invalid`; a two-digit year is read
in every century. A `datetime` SHALL need a time and a numeric offset and output UTC with `Z`. Inputs are strings.
Refs: §9, SPEC-04 §4.4, D-0293–D-0299.

#### Scenario: Day-month order unknown
- **WHEN** the text is `03/04/2026` with `html_lang="en"`
- **THEN** the result is `Ambiguous`

#### Scenario: Naive time
- **WHEN** a `datetime` input has no offset
- **THEN** the result is `Invalid("no_offset")`

### Requirement: location as stated
Location SHALL publish what the page states, with nothing looked up or inferred. Text is kept as written (NFC,
each whitespace run one space, trimmed), never split or parsed ("A or B" stays one text). From `Place` /
`PostalAddress`, `locality` and `region` publish as written; `country` only when `addressCountry` is an ISO 3166-1
alpha-2 code CLDR lists (less user-assigned codes); other two letters are `Invalid("unknown_country")`; a country
name gets no code. `remote_flag` only from `jobLocationType=TELECOMMUTE` or the `type:remote` vocabulary. Nothing
stated and not remote is `Invalid("no_match")`. No gazetteer is used.
Refs: §9, Appendix A #43, #44, SPEC-04 §4.4, D-0318, D-0953, D-1058; superseded: D-0311, D-0313–D-0317.

#### Scenario: Several places
- **WHEN** the text is `"Berlin  or   Remote"`
- **THEN** `text` is `"Berlin or Remote"` and the other parts are null

#### Scenario: Unknown country code
- **WHEN** `addressCountry` is `"QZ"`
- **THEN** the result is `Invalid("unknown_country")`

### Requirement: range
Range SHALL normalize to `{min, max, currency, unit, period}` with exactly one of `currency`/`unit`, from schema.org
`MonetaryAmount` / `QuantitativeValue` or from text with one separator (`-`, `–`, or a `type:range_to` word) and an
amount on each side; a currency written once applies to both bounds. `period` is one of `HOUR`, `DAY`, `WEEK`,
`MONTH`, `YEAR` from `unitText` or a `type:period` phrase. A monetary range without a period is `Ambiguous`; no
currency or unit is `Ambiguous`; `min > max` is `Invalid`; a lone text value is `Invalid("not_a_range")`.
Refs: §9, SPEC-04 §4.4, D-0275–D-0279, D-0328, D-0883.

#### Scenario: Missing period
- **WHEN** the text is `€40 - €50` with no period
- **THEN** the result is `Ambiguous("period_missing")`

### Requirement: count
Count SHALL be a non-negative integer from a JSON whole number, a `QuantitativeValue` `value` with no unit or
`unitCode` `C62`, or the one number in a text read by the CLDR locale set. A fraction, negative, range, other unit,
no number or two numbers (`several_numbers`) SHALL be `Invalid`.
Refs: §9, Appendix A #39, SPEC-04 §4.4, D-0921.

#### Scenario: Stock in text
- **WHEN** the text is "In stock (5 available)"
- **THEN** the result is `Ok(5)`

### Requirement: number
Number SHALL be a decimal as stated, from a JSON number or the one number in a text, as a fixed-point string with
digits as written (`4.50` stays `4.50`), never rescaled. No number or two numbers (`several_numbers`) are `Invalid`;
a minus sign set apart from the digits is `Invalid("sign")`.
Refs: §9, Appendix A #42, SPEC-04 §4.4, D-0960.

#### Scenario: Rating with its scale
- **WHEN** the text is "4.5 out of 5"
- **THEN** the result is `Invalid("several_numbers")`

### Requirement: identifier
`gtin` SHALL be digits only, length 8/12/13/14, with a passing GS1 mod-10 check digit, kept as given; `isbn` passes
the ISBN-10/13 checksum (ISBN-13 with prefix 978/979; ISO 2108 hyphens dropped); `mpn`, `sku`, `custom` are opaque,
trimmed, non-empty, at most 64 characters. Non-negative JSON integers are read as digits.
Refs: §9, SPEC-04 §4.4, D-0287–D-0290.

#### Scenario: Check digit fails
- **WHEN** one digit of a valid GTIN-13 is changed
- **THEN** the result is `Invalid("check_digit")`

### Requirement: text and long_text
Text SHALL decode HTML entities, apply NFC, remove non-whitespace controls, collapse whitespace and trim;
`long_text` keeps line breaks (blank-line runs collapsed to one). `Invalid` when empty, longer than 512 (text) or
100,000 (long_text) characters, a template placeholder (`{{…}}`, `${…}`, `%s`-style), holding a lone surrogate, or
not a JSON string.
Refs: §9, SPEC-04 §4.4, D-0017, D-0257–D-0259, D-0262, D-0263.

#### Scenario: Placeholder
- **WHEN** the text is `{{ product.title }}`
- **THEN** the result is `Invalid("template_placeholder")`

### Requirement: url and image_url
URLs SHALL be parsed per WHATWG, absolutized against `base_url`, and canonicalized (lowercase scheme and host,
default port removed, fragment stripped, percent-normalized, empty query `?` kept). Non-http(s), unparsable, empty
after trimming, or an empty host (`https:////host/x`, RFC 9110 §4.2.1) SHALL be `Invalid`. An `image_url` SHALL NOT
be a `data:` URL or the page URL itself; no extension list.
Refs: §9, SPEC-04 §4.4, D-0260, D-0261, D-0329, D-1022.

#### Scenario: Empty authority
- **WHEN** the input is `https:////example.com/x`
- **THEN** the result is `Invalid("no_host")`, never repaired

### Requirement: list and object
A list SHALL normalize each item (a single value is a list of one) and be `Ok` when at least one item is `Ok`,
reporting dropped items as `<path>: <reason>`; with none `Ok`, `Ambiguous("no_item")` if any item was ambiguous,
else `Invalid("no_item")`. An object SHALL normalize named sub-fields, ignore other keys, treat `null` as missing,
and decline when a required sub-field declines.
Refs: SPEC-04 §4.4, D-0325, D-0326.

#### Scenario: One bad item
- **WHEN** a list of three image URLs has one `data:` URL
- **THEN** the result is `Ok` with two items and one reason

### Requirement: Equality per type
`equal(a, b, spec)` SHALL be reflexive and symmetric for any JSON value. money: Decimal amount and currency equal;
enum, date, count: exact; identifier: exact, GTINs compared zero-padded to 14 digits; number: as decimals; text:
after normalization, case-sensitive; url: after canonicalization; location: `remote_flag`, `country` and casefolded
`locality` equal, region and text (by tokens) only when both present; range: all parts; list: multiset.
Refs: SPEC-04 §4.5, D-0322–D-0324, D-0960.

#### Scenario: GTIN padding
- **WHEN** a GTIN-13 is compared with the same number zero-padded to 14 digits
- **THEN** they are equal

### Requirement: Versioned vocabulary data
Vocabularies SHALL be language-tagged files under `normalize/vocab/`, each with a `JUSTIFICATION.md`; schema.org
enumeration members ship as typed data. A new phrase or language SHALL be added only under the C10 acceptance rule.
The schema.org file is a fetched `backend/data/manifest.json` entry, sha256-checked by `crawlerai data fetch`; CLDR
comes with Babel.
Refs: C4, SPEC-04 §4.6, D-0018, D-0271, D-0312.

#### Scenario: Phrase with no versioned source
- **WHEN** availability text is "available"
- **THEN** it declines: no pinned vocabulary phrase states it
