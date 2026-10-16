# Normalization by type

Design rationale, split from the former `docs/ARCHITECTURE.md` with its section numbers kept (code and history cite `ARCHITECTURE §N`). Index: [README.md](README.md).

## 9. Normalization by type

One module per type. Each is a pure function, and the only place its type is handled (C8):

```
normalize(raw, type, context) → Ok(value) | Ambiguous(reason, options) | Invalid(reason)
```

`context` contains only evidence from the page and request: `<html lang>`, `og:locale`, hreflang, currency stated
elsewhere in the page's structured data, the ccTLD resolved through CLDR territory data, and the request's locale
hint. Never host tables (C7).

| Type | Source | Declines when |
|---|---|---|
| money | Unicode CLDR via Babel **[verified: BSD-3]**; `price-parser` (BSD-3) to locate the number | The symbol maps to several currencies (`$` → USD, CAD, AUD, MXN, ARS, …) and context doesn't settle it. The decimal separator is ambiguous. The value isn't positive. |
| enum | schema.org enumerations; language-tagged type vocabularies (C4) | No match. Matching is token-level, never by substring order. Text states a member only when its whole first clause is the member's phrase or name ("Not in stock" declines). |
| date | ISO 8601; `dateparser` (BSD-3) with the page language | Day and month order is ambiguous for the locale. A relative date arrives without a capture time. |
| location | schema.org `Place` / `PostalAddress`; ISO 3166-1 alpha-2 codes as CLDR lists them | Nothing stated, or an `addressCountry` of two letters that is no ISO 3166-1 code. The text and address parts publish as written, whitespace collapsed; a text naming several places or alternatives ("A or B") is one text, never split or parsed into regions (Appendix A #44). A country code only when the page states one, never derived from a name. Remote only from `jobLocationType=TELECOMMUTE` or an explicit remote phrase. |
| range | schema.org `MonetaryAmount` / `QuantitativeValue`; parsed text | Period or currency unresolved. Min > max. |
| count | JSON numbers; schema.org `QuantitativeValue` (`inventoryLevel`); the one number in a text, read by CLDR number symbols | A fraction, a negative number, a range, a unit other than one, no number or two numbers in the text. |
| number | JSON numbers; the one number in a text, read by CLDR number symbols; digits kept as written | No number or two numbers in the text; a minus sign set apart from the digits. |
| identifier | GS1 check digit (GTIN-8/12/13/14), ISBN; `sku`/`custom` stay opaque | Checksum fails. |
| text | Entity and whitespace normalization; trafilatura for long text | Empty, out of length bounds, or a template placeholder (`{{ … }}`). |
| url | WHATWG URL parsing, absolutization | Unparseable, or not http(s). |

- No defaults.
- Derived values fill only empty fields and carry `derived_by`. Each derivation is a named function with a
  standards justification.
- Each type has property-based tests (Hypothesis, test-only).
