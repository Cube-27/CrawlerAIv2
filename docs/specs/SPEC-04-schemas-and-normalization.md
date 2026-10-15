# SPEC-04 — Schemas as data and type normalization

Layer: L1. Architecture refs: §5 (all), §9 (all), §6 (`schema_def`), C2, C4, C7, C8, §19 (normalization row).

## 1. Summary

Schemas are rows; code knows field types only (§5). Each field type has exactly one normalizer module, a pure
function that returns `Ok`, `Ambiguous` or `Invalid` and never guesses (§9, C7). This spec defines the schema
document format (the §5.2 rules made concrete, including `scope` for listings and `required_groups` for "sku
or gtin"), the preset documents, the normalizer interface and per-type rules, the type-equality functions used
by the resolver and the eval metrics, and the versioned external data they depend on (C4).

## 2. Scope

Core:
- Field type registry for the §5.1 types: `text`, `long_text`, `money`, `enum`, `url`, `image_url`,
  `identifier`, `date`, `datetime`, `location`, `range`, `list<T>`, `object{…}`.
- `SchemaDef` document model, validation, versioning, `origin`, `status`.
- Presets `commerce_detail`, `commerce_listing`, `job_detail`, `job_listing` (§5.3) as JSON files + sync command.
- Normalizers per type with `Context`, declines per §9, property tests.
- `equal(a, b)` per type.
- Data manifest entries: GeoNames snapshot; CLDR via Babel package (no file).

Out of scope:
- Types not in §5.1 (quantity, rating, duration) until a schema needs them (§5.1), each a new module + contract
  entry.
- Variant matrices: SPEC-13 (admitted, ARCHITECTURE Appendix A #37), which extends the §4.2 path grammar.
- Role S schema drafting (SPEC-06) and the `/v1/schemas` API (SPEC-07); this spec provides the registry service.
- Any host, retailer or symbol→currency default table (C7). Any phrase list not tagged by language and justified
  (C4).

## 3. Dependencies

- SPEC-01 (`schema_def` table).
- OPEN_QUESTIONS #3: core fields as in §5.3; no optional preset fields until asked.

## 4. Design

### 4.1 Modules

- `crawlerai.schemas.types` — `FieldType` enum, `FieldSpec`, `SchemaDef` pydantic models.
- `crawlerai.schemas.registry` — `get(name, version)`, `get_by_id`, `create`, `new_version`, `list`,
  `sync_presets()`.
- `crawlerai.schemas.presets/*.json`.
- `crawlerai.normalize.base` — `NormalizeResult`, `Context`, `Normalizer` protocol, `normalize(raw, spec, ctx)`
  dispatcher, `equal(a, b, spec)` dispatcher.
- `crawlerai.normalize.{text,money,enum,url,identifier,date,location,range}` — one module each (C8). `long_text`
  is handled by `text` (same module, flag `long=True`); `image_url` by `url` (flag `image=True`); `datetime` by
  `date`. `list` and `object` are handled in `base` by recursion, not by their own modules (they have no values
  of their own).
- `crawlerai.normalize.vocab/` — language-tagged vocabularies with a `JUSTIFICATION.md` per file (C4).

### 4.2 Schema document

```jsonc
{
  "name": "commerce_detail", "version": 1, "page_kind": "detail",
  "required_groups": [["sku", "gtin"]],            // at least one field of each group must publish (§5.2)
  "fields": {
    "title":  { "type": "text", "required": true, "description": "...", "schema_org": "Product.name", "scope": "row" },
    "price":  { "type": "money", "required": true, "schema_org": "Offer.price+priceCurrency" },
    "availability": { "type": "enum", "vocab": "schema:ItemAvailability", "required": true, "schema_org": "Offer.availability" },
    "gtin":   { "type": "identifier", "scheme": "gtin", "schema_org": "Product.gtin" },
    "sku":    { "type": "identifier", "scheme": "sku",  "schema_org": "Product.sku" },
    "locations": { "type": "list", "item": { "type": "location" }, "schema_org": "JobPosting.jobLocation" },
    "next_page_url": { "type": "url", "scope": "page" }
  }
}
```

Rules:
- `required` defaults false; `scope` ∈ {`row`, `page`}, default `row`; on `detail` pages every field is `row`
  (the one entity). "Core fields" in the architecture = `required: true` fields plus `required_groups`.
- `schema_org` is a dotted path from a schema.org type; `+` joins two properties into one atomic value
  (`Offer.price+priceCurrency`). Validated against a pinned schema.org vocabulary file (manifest).
- `vocab` references a vocabulary: `schema:<Enumeration>` (members from the pinned schema.org file) or
  `type:<name>` (a language-tagged vocabulary in `normalize/vocab/`).
- `identifier.scheme` ∈ {`gtin`, `isbn`, `mpn`, `sku`, `custom`}.
- `list.item` and `object.fields` nest; depth ≤ 3.
- `description` is required for every field (role C reads it; §5.2). Presets carry descriptions.
- Versioning: `schema_def` rows are immutable per (name, version). `new_version(name, changes)` inserts
  version+1; records and configs reference (schema_id, schema_version).
- `origin` ∈ {`preset`, `user`, `prompt_draft`}; `status` ∈ {`active`, `retired`}.

Presets (§5.3), exactly these core fields, each with `schema_org` mapping:
- `commerce_detail`: title (text, req), price (money, req), availability (enum ItemAvailability, req), url (url,
  req), image_url (image_url, req), brand (text), sku (identifier sku), gtin (identifier gtin);
  `required_groups: [["sku","gtin"]]`. Version 2: `brand` optional (ARCHITECTURE Appendix A #35); version 1 had
  it required.
- `commerce_listing`: row: title (req), url (req), price; page: next_page_url (url).
- `job_detail`: title (req), company (text, req, `JobPosting.hiringOrganization.name`), locations (list<location>,
  req), description (long_text, req), apply_url (url, req, `JobPosting.url` — see Open issues), date_posted
  (date, req).
- `job_listing`: row: title (req), url (req), location; page: next_page_url.

`sync_presets()` inserts missing (name, version) rows at startup/migration; changing a preset file requires a
version bump (test: file version == max DB version or file is new).

### 4.3 Normalizer interface

```python
class Context(BaseModel, frozen=True):      # evidence from page and request only (§9); never host tables
    html_lang: str | None          # <html lang>
    og_locale: str | None
    hreflang: tuple[str, ...]
    page_currencies: tuple[str, ...]   # ISO 4217 codes stated in the page's structured data
    cctld_territory: str | None    # from the URL's ccTLD through CLDR territory data (Babel), e.g. "DE"; None for gTLDs
    request_locale: str | None     # caller hint
    captured_at: datetime          # for relative dates

NormalizeResult = Ok(value) | Ambiguous(reason: str, options: list[value]) | Invalid(reason: str)

def normalize(raw: str | dict | list, spec: FieldSpec, ctx: Context) -> NormalizeResult
def equal(a, b, spec: FieldSpec) -> bool
```

`raw` may be a string (DOM/LLM) or a JSON value (structured sources: e.g. `{"price": "19.90", "priceCurrency":
"EUR"}` for money). Every normalizer accepts both forms and documents them.

Every rule in a normalizer carries a comment naming its justification (C2): standard, type property, or
structural property.

### 4.4 Per-type rules (§9 table, made concrete)

**money** → `{amount: Decimal, currency: ISO 4217}`.
- Structured input: `price` + `priceCurrency` → validate code against Babel's currency list; amount via `Decimal`.
- Text input: `price-parser` locates the number and symbol; the symbol is resolved through CLDR currency symbol
  data (Babel) for the locale set built from `ctx` (`html_lang`, `og_locale`, `hreflang`, `cctld_territory`,
  `request_locale`): a symbol that maps to exactly one currency across those locales → `Ok`; several →
  `Ambiguous(options)`; `page_currencies` with exactly one code that the symbol is valid for → `Ok`.
- Decimal separator: resolved from CLDR number symbols for the same locale set; if the locales disagree and the
  text is ambiguous (e.g. `1.234`) → `Ambiguous`.
- `amount <= 0` → `Invalid`. Ranges ("from 10 to 20") → `Invalid("range")` (the `range` type handles those).
- Never: `$`→USD without context, host tables, defaults (INV-06).

**enum** → member code.
- `schema:` vocab: match the input as a schema.org IRI or member name (`https://schema.org/InStock`,
  `http://schema.org/InStock`, `InStock`, `schema:InStock`) — standard.
- `type:` vocab: tokenize input (NFKC, casefold, split on non-letters); a vocabulary entry matches when its token
  sequence equals a contiguous token subsequence of the input; the longest match wins; two different members
  matching → `Ambiguous`; no match → `Invalid`. Never substring order (§9).
- Initial `type:availability` vocabulary (language `en`) is the de-camel-cased schema.org `ItemAvailability`
  member names only ("in stock", "out of stock", "pre order", "back order", "sold out", "discontinued", "limited
  availability", "in store only", "online only", "pre sale", "reserved", "made to order"), justification:
  schema.org. Any other phrase or language is added only under the C10 acceptance rule (dev improvement and
  hidden non-regression in the PR report; C4), with the justification recorded in `JUSTIFICATION.md`.

**date / datetime** → ISO 8601 string (`YYYY-MM-DD` / RFC 3339 with offset).
- ISO/RFC 3339 input parses directly.
- Else `dateparser` with `languages` from `ctx.html_lang` (and `og_locale`), `DATE_ORDER` from CLDR for the
  locale; if the locale set yields different `DATE_ORDER`s and the text is numeric-ambiguous (`03/04/2026`) →
  `Ambiguous`. Relative dates ("2 days ago") need `ctx.captured_at`; otherwise `Invalid`.
- Years outside 1970–2100 → `Invalid`.

**location** → `{locality, region, country, remote_flag}`.
- Structured (`Place`/`PostalAddress`): `addressCountry` to ISO 3166-1 alpha-2 (names via Babel territory
  names + codes), `addressRegion`, `addressLocality` as given.
- Text: tokenized match against GeoNames `cities15000` + `admin1` + `countryInfo` (pinned snapshot in manifest,
  CC BY 4.0, attribution in `NOTICE`): country name/code match sets `country`; a city name that exists in exactly
  one country among the matched/implied ones → `Ok`; the same city name in several countries with no country
  given → `Ambiguous(options)`; nothing → `Invalid`.
- `remote_flag` only from `jobLocationType == TELECOMMUTE` or the `type:remote` vocabulary (`en`: "remote",
  justification: the schema.org `TELECOMMUTE` definition text) — never inferred from a missing location.

**range** → `{min, max, currency|unit, period}`.
- Structured `MonetaryAmount`/`QuantitativeValue` (`minValue`, `maxValue`, `value`, `currency`, `unitText`,
  `unitCode`) — standard. `period` from `QuantitativeValue.unitText` in {`HOUR`,`DAY`,`WEEK`,`MONTH`,`YEAR`}.
- Text: two money/number parses around a separator (`-`, `–`, "to"); currency through the money rules; period only
  from an explicit "per X"/"/X" token matching the five period units (`type:period` vocabulary, `en`,
  justification: schema.org unitText for salary). Missing period or currency → `Ambiguous`; `min > max` →
  `Invalid`.

**identifier** → `{scheme, value}`.
- `gtin`: digits only, length 8/12/13/14, GS1 mod-10 check digit must pass (standard). `isbn`: ISBN-10/13
  checksum. `mpn`, `sku`, `custom`: trimmed, non-empty, ≤ 64 chars, opaque. Scheme is the field's declared scheme;
  a `gtin` candidate failing the check digit → `Invalid`. (Structured `Product.gtin13` etc. map to scheme `gtin`.)

**text / long_text** → string.
- HTML entity decoding, NFC, whitespace collapse, trim. `long_text` is built from trafilatura main-content
  extraction over the element the locator points to (or the page) and keeps paragraph breaks.
- `Invalid` when empty, longer than `max_len` (text 512, long_text 100k), or matches a template placeholder
  (`{{…}}`, `${…}`, `%s`-style) — structural.

**url / image_url** → absolute http(s) URL string.
- WHATWG parsing (`urllib.parse` + the `url` crate is not needed; use `rfc3986`-free stdlib with explicit
  canonicalization: lowercase scheme/host, remove default port, strip fragment, percent-normalize), absolutized
  against the document base (`<base href>` or final URL). Non-http(s) or unparsable → `Invalid`. `image_url`
  additionally requires a path or `content-type` evidence that it is an image — content-type is not available
  without a fetch, so the only check is "not a data: URL and not the page URL itself"; nothing else (no extension
  list; C4).

**list<T>**: normalize each item; `Ok` if ≥ 1 item `Ok`; items that decline are dropped and reported in
`reasons`. **object{…}**: normalize each sub-field; `Ok` if all required sub-fields `Ok`.

### 4.5 Equality (`equal`)

money: `amount` equal as Decimal (no rounding) and `currency` equal. enum/identifier/date: exact. text: equal
after the text normalization (case-sensitive). url: equal after canonicalization. location: `country` equal and
`casefold(locality)` equal (region ignored unless both present). range: all four parts equal. list: multiset of
item equality. These functions are used by the resolver's agreement rule (SPEC-05) and by eval (SPEC-03).

### 4.6 Data (C4, INV-05)

`backend/data/manifest.json` entries: `schemaorg-all-https.jsonld` (schema.org release, CC BY-SA 3.0 — used as
a vocabulary file only; attribution in NOTICE), `cities15000.zip`, `admin1CodesASCII.txt`, `countryInfo.txt`
(GeoNames, CC BY 4.0), IANA TLD list (SPEC-00). `crawlerai data fetch` downloads and verifies sha256; the files
are not committed. CLDR comes with Babel (BSD-3), no file.

### 4.7 Error handling

Normalizers never raise on bad input; every failure is `Invalid(reason)`. Programming errors (wrong `spec`) raise
`TypeError`. The dispatcher returns `Invalid("unknown_type")` for unknown types so a schema with a future type
cannot crash a job.

## 5. Invariants

INV-05, INV-06, INV-08 (`.importlinter` contracts updated: each new module in the independence list), INV-09.
Property tests are the enforcement for INV-06.

## 6. Testing strategy

Hypothesis property tests per type (`tests/property/test_normalize_<type>.py`), minimum set:
- Idempotence: `normalize(render(Ok.value)) == Ok(value)` for generated values.
- Decline on empty/whitespace input, always.
- money: for every currency symbol shared by ≥ 2 currencies in CLDR, with empty context → `Ambiguous`; with a
  single `page_currencies` code valid for the symbol → `Ok` with that code; never `Ok` with a currency not in the
  locale set or `page_currencies`; amount ≤ 0 → `Invalid`.
- enum: substring order never matters (generate inputs where a shorter member is a substring of a longer phrase:
  "unavailable" must not match "available"); two members in one input → `Ambiguous`.
- date: numeric `a/b/c` with both orders valid and no locale → `Ambiguous`; ISO round-trips.
- identifier: random 13-digit strings with a correct check digit → `Ok`; one digit perturbed → `Invalid`.
- location: a generated city with homonyms in two countries and no country → `Ambiguous`.
- url: any output starts with `http(s)://` and has no fragment.
- Context purity: `normalize` called twice with the same input and context returns the same result (no I/O).
- Schema: generated schema documents round-trip through the model; invalid `schema_org` paths rejected.
- No test uses a hostname or retailer (C9); money tests use ISO codes and CLDR symbols only.

CI gates: `backend` job (property tests run with a fixed Hypothesis profile, `max_examples=200` in CI).

## 7. Acceptance criteria

- All four presets load; `GET` through the registry returns them with every field described.
- Every §9 "declines when" row has a passing property test.
- `lint-imports` passes with all eight normalizer modules in the independence contract.
- `crawlerai data fetch` populates GeoNames and schema.org files; `data_manifest_check` passes.

## 8. PR plan

| # | Title | Scope | Checks | Done when |
|---|---|---|---|---|
| 1 | Schema models, registry, presets, sync | `schemas/*`, preset JSON, migration data | unit | Presets in DB. |
| 2 | Normalizer base, dispatcher, text, url | `normalize/base,text,url` | property | INV-06 tests pass. |
| 3 | money (CLDR via Babel + price-parser) | `normalize/money` | property | Symbol ambiguity tests pass. |
| 4 | enum + vocab framework + availability `en` | `normalize/enum`, `vocab/` | property | Token matching tests pass. |
| 5 | date/datetime | `normalize/date` | property | Order ambiguity tests pass. |
| 6 | identifier | `normalize/identifier` | property | Check-digit tests pass. |
| 7 | Data manifest + GeoNames fetch + location | `data/manifest.json`, `normalize/location` | property, data-manifest job | Homonym tests pass. |
| 8 | range | `normalize/range` | property | Period/currency decline tests pass. |
| 9 | `equal` per type + list/object recursion | `normalize/base` | property | Eval and resolver can import. |

## 9. Open issues

- **Review finding ("sku or gtin" vs `required`).** Resolved in ARCHITECTURE rev 5 §5.2–5.3: `required_groups`.
- **Review finding (required vs core).** Resolved in ARCHITECTURE rev 5 §5.2: "core fields" means `required: true`
  fields plus `required_groups`.
- **`apply_url` mapping.** §5.3 leaves the mapping to this spec. schema.org `JobPosting` has no `applyUrl`;
  Google's Job posting guidance uses the page URL / `url`. Mapped to `JobPosting.url` here; the adapters map
  their own apply links. Owner to confirm.
- **Listing schema shape.** Resolved in ARCHITECTURE rev 5 §5.2: `scope` ∈ {`row`, `page`}.
- **schema.org vocabulary file license** is CC BY-SA 3.0 — used as data, not code; attribution in NOTICE. If the
  owner wants no SA-licensed data at all, the enumeration members can be typed by hand from the standard
  (justification remains schema.org).
