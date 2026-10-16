# Normalization Specification

## Purpose

Normalization turns a raw candidate into a typed value for its field type, or declines, with one pure normalizer
per type under `backend/src/crawlerai/normalize/`; it also gives per-type equality to the resolver and eval. Field
types are [schemas](../schemas/spec.md); what publishes is [resolution](../resolution/spec.md). Rationale: ARCHITECTURE §9 ([archived](../../changes/archive/2026-10-16-architecture-rev25/ARCHITECTURE.md)); history: SPEC-04.

## Requirements

### Requirement: Result contract
`normalize(raw, spec, ctx)` SHALL be pure and return `Ok`, `Ambiguous(reason, options)` or `Invalid(reason)`,
never raising on bad input; every rule names its standard or structural property in a comment (C2). Refs: §9, D-0254.
#### Scenario: Same input twice
- **WHEN** `normalize` is called twice with the same raw value and context
- **THEN** it returns the same result

### Requirement: Context is page and request evidence only
`Context` (`normalize/base.py`) SHALL hold only evidence from the page and the request; `None` means no evidence,
never a default. Refs: §9, D-0256, D-0773.
#### Scenario: No context
- **WHEN** a context carries only `captured_at`
- **THEN** no normalizer supplies a locale, currency or country of its own

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
amount must be positive. Refs: §9, D-0300–D-0306.
#### Scenario: Ambiguous dollar
- **WHEN** the text is `$10` with `html_lang="en"` and no page currency
- **THEN** the result is `Ambiguous`; with `page_currencies=("CAD",)` it is `Ok({amount: "10", currency: "CAD"})`

### Requirement: enum and the first-clause rule (INV-37)
`normalize/enum.py` SHALL match `schema:` members by IRI or name exactly, and otherwise read only the text's first
clause, which must equal a member phrase as a whole; extra words decline, never substring match. Refs: §9, D-0271–D-0274, D-0882, D-0920.
Enforced by: `tests/property/test_normalize_enum.py` and `tests/replay/test_replay_stock.py`; active.
#### Scenario: Qualified phrase
- **WHEN** availability text is "Not in stock", "In stock soon" or "5 in stock"
- **THEN** the result is `Invalid`; "In stock (5 available)" is `Ok("InStock")`

### Requirement: date and datetime
`normalize/date.py` SHALL read ISO 8601 directly and other dates in every order the page locales allow, returning
`Ambiguous` when readings differ; a `datetime` needs a time and offset and outputs UTC. Refs: §9, D-0293–D-0299.
#### Scenario: Day-month order unknown
- **WHEN** the text is `03/04/2026` with `html_lang="en"`
- **THEN** the result is `Ambiguous`

### Requirement: location as stated
`normalize/location.py` SHALL publish only what the page states: text as written (never split), structured parts as
written, a country only from a valid ISO 3166-1 code, `remote_flag` only when stated; no gazetteer. Refs: §9, D-0953, D-1058.
#### Scenario: Unknown country code
- **WHEN** `addressCountry` is `"QZ"`
- **THEN** the result is `Invalid("unknown_country")`

### Requirement: range, count and number
`normalize/range.py`, `count.py` and `number.py` SHALL each accept one stated value and decline otherwise: a
monetary range without a period is `Ambiguous`; count and number decline on two numbers; number keeps digits as
written. All numbers are read in the CLDR locale set of the page and request language tags (`numbers.py`), and
locales that read a number differently give `Ambiguous`. Refs: §9, D-0275–D-0279, D-0302, D-0921, D-0922, D-0960.
#### Scenario: Rating with its scale
- **WHEN** a `number` text is "4.5 out of 5"
- **THEN** the result is `Invalid("several_numbers")`

### Requirement: identifier, text and url
`normalize/identifier.py` SHALL check GTIN and ISBN check digits; `text.py` cleans text and declines templates;
`url.py` parses per WHATWG, absolutizes, canonicalizes and declines non-http(s) or hostless URLs, never repairing. Refs: §9, D-0287–D-0290, D-0257–D-0263, D-1022.
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
