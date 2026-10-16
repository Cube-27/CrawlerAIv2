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
- `SchemaDef` document model, validation, in-place edits, `origin`, `status`.
- Presets `commerce_detail`, `commerce_listing`, `job_detail`, `job_listing` (§5.3) as JSON files + sync command.
- Normalizers per type with `Context`, declines per §9, property tests.
- `equal(a, b)` per type.
- Data manifest entries: the schema.org vocabulary; CLDR via Babel package (no file).

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
- `crawlerai.schemas.registry` — `get(name)`, `find(name)`, `get_by_id`, `create`, `update_schema`, `retire`, `list_schemas`,
  `sync_presets()`.
- `crawlerai.schemas.presets/*.json`.
- `crawlerai.normalize.base` — `NormalizeResult`, `Context`, `Normalizer` protocol, `normalize(raw, spec, ctx)`
  dispatcher, `equal(a, b, spec)` dispatcher.
- `crawlerai.normalize.{text,money,enum,url,identifier,date,location,range,count}` — one module each (C8). `long_text`
  is handled by `text` (same module, flag `long=True`); `image_url` by `url` (flag `image=True`); `datetime` by
  `date`. `list` and `object` are handled in `base` by recursion, not by their own modules (they have no values
  of their own).
- `crawlerai.normalize.vocab/` — language-tagged vocabularies with a `JUSTIFICATION.md` per file (C4).
- `crawlerai.normalize.numbers` — numbers as pages write them: the page's CLDR locale set and the values a written
  number has under its number symbols. Shared by `money` and `count`, so both read numbers one way (D-0782).

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
  (`Offer.price+priceCurrency`). Validated against a pinned schema.org vocabulary file (manifest). Up to four
  alternatives are separated by `|` (`Product.sku|Offer.sku`); their candidates are pooled, none outranking another
  (SPEC-13 §4.1).
- A `list` whose `item` is an `object` and which has `schema_org` is row-mapped (SPEC-13 §4.2): the path names the
  row entities (no `+`), the item has no `schema_org` of its own, its sub-fields are leaf types each with their own
  path (or none), and `key` names 1–3 distinct `identifier` or `url` sub-fields. `key` is required there and allowed
  nowhere else. A `list` of `object` without `schema_org` keeps literal keys (§4.4).
- `vocab` references a vocabulary: `schema:<Enumeration>` (members from the pinned schema.org file) or
  `type:<name>` (a language-tagged vocabulary in `normalize/vocab/`).
- `identifier.scheme` ∈ {`gtin`, `isbn`, `mpn`, `sku`, `custom`}.
- `list.item` and `object.fields` nest; depth ≤ 3.
- `description` is required for every field (role C reads it; §5.2). Presets carry descriptions.
- No versions (ARCHITECTURE Appendix A #43): one `schema_def` row per name. `update_schema(schema, changes)`
  rewrites its document in place; when the document changed, the edit's caller (`services.schemas`, the preset
  sync) runs `progressive.relearn_schema`: its active configs become `suspended` and its progressive states `cold`
  with no run in flight, so its sites learn again. Records and configs reference `schema_id`; a record carries the
  digest of the document it was extracted with (`record.schema_digest`), and counts for the current document only
  when the digests are equal (SPEC-11 record versions and unchanged pages).
- `origin` ∈ {`preset`, `user`, `prompt_draft`}; `status` ∈ {`active`, `retired`}.

Presets (§5.3), exactly these core fields, each with `schema_org` mapping:
- `commerce_detail`: title (text, req), price (money, req), availability (enum ItemAvailability, req), url (url,
  req), image_url (image_url, req), brand (text), sku (identifier sku), gtin (identifier gtin);
  `required_groups: [["sku","gtin"]]`. `brand` is optional (ARCHITECTURE Appendix A #35); the optional
  row-mapped `variants` (SPEC-13 §4.7); the optional `stock_quantity` (count, `Offer.inventoryLevel`), also a
  sub-field of each `variants` row (Appendix A #39, D-0782). Optional fields the page states (Appendix A #42),
  each with its schema.org path: description (long_text, `Product.description`), additional_images
  (list<image_url>, `Product.image`), color (text, `Product.color`), material (text, `Product.material.name`), gender (text,
  `Product.audience.suggestedGender`), condition (enum OfferItemCondition, `Offer.itemCondition|Product.itemCondition`),
  rating (number, `Product.aggregateRating.ratingValue`), review_count (count,
  `Product.aggregateRating.reviewCount`), mpn (identifier mpn, `Product.mpn`), product_id (identifier custom,
  `Product.productID`); `variant_id` (identifier, `Product.productID`) in each `variants` row (SPEC-13 §4.7). No
  derived values (no counts of variants or images).
- `commerce_listing`: row: title (req), url (req), price; page: next_page_url (url).
- `job_detail`: title (req), company (text, req, `JobPosting.hiringOrganization.name`), locations (list<location>,
  req), description (long_text, req), apply_url (url, req, `JobPosting.url` — see Open issues), date_posted
  (date, req).
- `job_listing`: row: title (req), url (req), location; page: next_page_url.

`sync_presets()` (`crawlerai schemas sync`) inserts a missing preset and updates a changed one in place, as an
edit (§4.1); a preset name held by a caller's schema is refused. Preset files carry no version.

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
  `http://schema.org/InStock`, `InStock`, `schema:InStock`) — standard. Other text that is no IRI is read as the
  `type:` rule below reads it, against each type vocabulary whose codes are all members of the enumeration
  (`type:availability` for `ItemAvailability`), and a member name in any case also counts as the clause (`instock`,
  as Open Graph `product:availability` writes it) (D-0782).
- `type:` vocab: tokenize input (NFKC, casefold, split on non-letters). The input states a code when the tokens of
  its **first clause** equal one of the code's phrases exactly. The first clause runs from the first letter through
  letters, marks, spaces, dashes and connectors (Unicode categories L, M, Zs, Pd, Pc) to the first other character
  (punctuation, symbol, digit, line break); leading spaces, punctuation and symbols are skipped, a leading digit is
  not. A different code whose phrase appears anywhere later (token run, longest match wins) → `Ambiguous`; no
  clause match → `Invalid`. So "In stock (5 available)" → `InStock`; "Not in stock", "In stock soon",
  "5 in stock" → `Invalid`: a word in the clause may negate or qualify the phrase, and no standard lists which
  (C4, C7). "available" is no member name or phrase of the pinned schema.org vocabulary, so it declines. Never
  substring order (§9).
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

**location** → `{text, locality, region, country, remote_flag}`: what the page states, nothing looked up or
inferred (ARCHITECTURE Appendix A #43).
- Text (a string, or a `Place` with only a `name`): `text` as written (NFC, each whitespace run one space,
  trimmed); the other parts `None`. Nothing in the text is parsed: several places, macro-regions or alternatives
  ("A or B") stay one text, never split (owner, 2026-10-16: "just display whatever is written in jobs location";
  ARCHITECTURE Appendix A #44).
- Structured (`Place`/`PostalAddress`): `addressLocality`, `addressRegion` as written (whitespace collapsed);
  `country` only when `addressCountry` (text, or a `Country`'s `identifier` or `name`) is an ISO 3166-1 alpha-2
  code, as CLDR lists them (via Babel) less ISO 3166-1's user-assigned ranges; two other letters → `Invalid("unknown_country")`; a
  country written as a name gets no code. `text` joins the stated parts as written (locality, region, country).
- Nothing stated and not remote → `Invalid("no_match")`.
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

**count** → non-negative integer (D-0782; a stock quantity).
- JSON number with no fraction; schema.org `QuantitativeValue` (the range of `Offer.inventoryLevel`): its `value`,
  with no unit or `unitCode` `C62` (UN/CEFACT Rec. 20 "one") — standard.
- Text: the one number in it, located as money locates an amount and read by the CLDR number symbols of the same
  locale set (`normalize.numbers`): "In stock (5 available)" → 5. No number → `Invalid`; two numbers →
  `Invalid("several_numbers")`; a number the locales read differently → `Ambiguous`.
- Fraction, negative, a range (`minValue`/`maxValue`), another unit → `Invalid`. Not a checkable type (SPEC-05
  §4.5): any number normalizes, so an embedded-state count admits by equality only.

**number** → a decimal as the page states it (Appendix A #42; a rating value, schema.org `Rating.ratingValue`).
- JSON number; text: the one number in it, read as count reads one (`normalize.numbers`): "Rated 4.5 stars" → `4.5`.
  The value is the decimal in fixed-point notation as a string, digits as written (`4.50` stays `4.50`); equality
  compares decimals.
- No number → `Invalid`; two numbers ("4.5 out of 5") → `Invalid("several_numbers")`; a minus sign set apart from
  the digits (possibly a dash) → `Invalid("sign")`; a number the locales read differently → `Ambiguous`. Nothing is
  rescaled (C7). Not a checkable type (SPEC-05 §4.5).

**list<T>**: normalize each item; `Ok` if ≥ 1 item `Ok`; items that decline are dropped and reported in
`reasons`. **object{…}**: normalize each sub-field; `Ok` if all required sub-fields `Ok`.

### 4.5 Equality (`equal`)

money: `amount` equal as Decimal (no rounding) and `currency` equal. enum/identifier/date/count: exact. text: equal
after the text normalization (case-sensitive). url: equal after canonicalization. location: `remote_flag` and
`country` equal, `casefold(locality)` equal; region (casefolded) and text (by tokens) count only when both are
present. range: all four parts equal. list: multiset of
item equality. These functions are used by the resolver's agreement rule (SPEC-05) and by eval (SPEC-03).

### 4.6 Data (C4, INV-05)

`backend/data/manifest.json` entries: `schemaorg-all-https.jsonld` (schema.org release, CC BY-SA 3.0 — used as
a vocabulary file only; attribution in NOTICE), IANA TLD list (SPEC-00). GeoNames is not used (Appendix A #43,
D-0311 superseded). `crawlerai data fetch` downloads and verifies sha256; the files
are not committed. CLDR comes with Babel (BSD-3), no file.

### 4.7 Error handling

Normalizers never raise on bad input; every failure is `Invalid(reason)`. Programming errors (wrong `spec`) raise
`TypeError`. The dispatcher returns `Invalid("unknown_type")` for unknown types so a schema with a future type
cannot crash a job.

## 5. Invariants

INV-05, INV-06, INV-08 (`.importlinter` contracts updated: each new module in the independence list), INV-09,
INV-37 (an enum read from text: only a whole first clause states a member; D-0782).
Property tests are the enforcement for INV-06.

## 6. Testing strategy

Hypothesis property tests per type (`tests/property/test_normalize_<type>.py`), minimum set:
- Idempotence: `normalize(render(Ok.value)) == Ok(value)` for generated values.
- Decline on empty/whitespace input, always.
- money: for every currency symbol shared by ≥ 2 currencies in CLDR, with empty context → `Ambiguous`; with a
  single `page_currencies` code valid for the symbol → `Ok` with that code; never `Ok` with a currency not in the
  locale set or `page_currencies`; amount ≤ 0 → `Invalid`.
- enum: substring order never matters (generate inputs where a shorter member is a substring of a longer phrase:
  "unavailable" must not match "available"); two members in one input → `Ambiguous`; a phrase with another word
  in its first clause ("not in stock") → `Invalid`, never the member.
- count: whole numbers round-trip; a fraction, a negative number or two numbers in a text → `Invalid`.
- date: numeric `a/b/c` with both orders valid and no locale → `Ambiguous`; ISO round-trips.
- identifier: random 13-digit strings with a correct check digit → `Ok`; one digit perturbed → `Invalid`.
- location: generated text publishes as written (whitespace runs collapsed) with no part inferred or split; a stated alpha-2 code publishes, two
  letters that are no code → `Invalid`; a country name gets no code.
- url: any output starts with `http(s)://` and has no fragment.
- Context purity: `normalize` called twice with the same input and context returns the same result (no I/O).
- Schema: generated schema documents round-trip through the model; invalid `schema_org` paths rejected.
- No test uses a hostname or retailer (C9); money tests use ISO codes and CLDR symbols only.

CI gates: `backend` job (property tests run with a fixed Hypothesis profile, `max_examples=200` in CI).

## 7. Acceptance criteria

- All four presets load; `GET` through the registry returns them with every field described.
- Every §9 "declines when" row has a passing property test.
- `lint-imports` passes with all nine normalizer modules in the independence contract.
- `crawlerai data fetch` populates the schema.org file; `data_manifest_check` passes.

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
| 10 | Availability from text: first-clause rule, member names in any case (D-0782) | `normalize/enum` | property, replay | "Not in stock" never gives `InStock`; "In stock (5 available)" and "instock" give `InStock`. |
| 11 | `count` type, shared CLDR number reading, `commerce_detail` v4 `stock_quantity` (also per variant) | `normalize/count`, `normalize/numbers`, `schemas/types`, preset, SPEC-13 §4.7 | property, unit, replay | `inventoryLevel` and "In stock (5 available)" give 5; a fraction, a negative or another unit declines. |
| 12 | `number` type; `commerce_detail` optional fields the page states, `variant_id` per variant (Appendix A #42) | `normalize/number`, `normalize/numbers`, `schemas/types`, preset, vocab `OfferItemCondition` | property, unit, replay | A page stating rating, review count, condition, color, mpn and productID publishes each; one stating none publishes none of them. |

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
