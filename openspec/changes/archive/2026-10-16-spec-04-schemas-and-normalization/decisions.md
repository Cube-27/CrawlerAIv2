# SPEC-04 decisions

Decisions for [SPEC-04 — Schemas as data and type normalization](SPEC-04-schemas-and-normalization.md).
Template, statuses and rules: [decisions/README.md](../../../decisions/README.md).

### D-0240 — `schema_org` and `vocab` are checked for syntax only until the schema.org file is in the manifest
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 1 (#43) · Status: decided
- Decision: Syntax per schema.org naming (`schema:<Type>` / `type:<name>`); checking against the pinned vocabulary waits for SPEC-04 PR 7 (§4.6).
- Alternatives: Commit the schema.org file now; hand-type the members.
- Why: The file isn't fetched yet, and §4.6 says data files aren't committed.
- Reversible: yes

### D-0241 — Schema depth and naming rules
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 1 (#43) · Status: decided
- Decision: A top-level field is depth 1 and each `item`/`fields` level adds 1, max 3. A list item needs no description; object sub-fields do. Schema and field names match `^[a-z][a-z0-9_]{0,63}$`.
- Alternatives: Count only container levels; require item descriptions; free-form names.
- Why: The most conservative reading; names are keys in records, configs and API payloads.
- Reversible: yes

### D-0242 — Presets sync through `crawlerai schemas sync`, run by `make migrate`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 1 (#43) · Status: decided
- Decision: Not an Alembic data migration or a startup hook. It refuses (`PresetConflict`, nothing inserted) when a stored (name, version) differs from the file, belongs to a non-preset row, or is newer than the file.
- Alternatives: A data migration; sync on API startup.
- Why: The preset files stay the single source, and a changed file without a version bump fails loudly.
- Reversible: yes

### D-0243 — `create` inserts version 1; `new_version` inserts latest+1
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 1 (#43) · Status: superseded by D-0950
- Decision: `create` refuses an existing name. `new_version(name, SchemaChanges, origin)` applies the given changes to the latest version, validates the whole document and inserts latest+1; older versions stay `active`. The function is `list_schemas`, not `list`.
- Alternatives: `new_version` retires the previous version; `create` takes any version.
- Why: Records and configs reference older versions; retiring is SPEC-07's decision.
- Reversible: yes

### D-0244 — The C3 scan reads `schema_org` paths from schema documents as non-hosts
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 1 (#43) · Status: superseded by D-0248
- Decision: A dotted token is a schema.org path, not a host, when a tracked JSON schema document maps a field to it (up to any `+`). Extends D-0111.
- Alternatives: A shape test on any `schema_org`-like value; an allowlist of paths (C4).
- Why: Derived from the repo, as D-0111's columns are. A tightening is a follow-up (ACTIVE, SPEC-04 PR 1).
- Reversible: yes

### D-0245 — Preset mappings the spec leaves open
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 1 (#43) · Status: decided
- Decision: `url` → `Product.url`, `image_url` → `Product.image`, `brand` → `Product.brand.name`; listings use the same row paths; `next_page_url` has no schema.org mapping.
- Alternatives: `Offer.url`; `Product.brand`.
- Why: schema.org `brand` is a `Brand`/`Organization`, so the text is its `name`; schema.org has no next-page property.
- Reversible: yes

### D-0248 — The C3 scan reads `schema_org` paths only from schema document fields
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 1 follow-up (#48) · Status: decided
- Decision: Paths come only from the field specs of JSON schema documents (`name`, integer `version`, `page_kind`, `fields`), only when they follow schema.org naming (UpperCamelCase type, lowerCamelCase properties), and match case-sensitively. Supersedes D-0244.
- Alternatives: restrict to `schemas/presets/` (a path rule); reject values ending in an IANA TLD (rejects `Product.name`, since `name` is a TLD); validate against the schema.org vocabulary (new manifest data).
- Why: Structural, derived from the schema document shape, as D-0111's columns are. Residual: a reviewed schema document could map a host spelled `Upper.lower.tld`; vocabulary validation would close it if needed.
- Reversible: yes

### D-0254 — Normalizer `base` holds the shared types; `dispatch` holds the dispatcher
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: SPEC-04 §4.1 puts both in `base`, but the dispatcher imports the type modules, which import the result types; one module would cycle.
- Alternatives: The dispatcher in `normalize/__init__`; lazy imports in `base`.
- Why: Avoids an import cycle; C8 holds.
- Reversible: yes

### D-0255 — Import contracts: normalize above schemas, an explicit independence list, a `normalize-internals` layers contract
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: D-0056 anticipated the relaxation of D-0055's wildcard, which can't hold because type modules import `base`. Each new type module joins both normalize contracts in its PR.
- Alternatives: normalize defines its own spec protocol (duplicates `FieldType`).
- Why: Keeps C8's one-module-per-type enforced by `lint-imports`.
- Reversible: yes

### D-0256 — `Context` gains `base_url` and `page_url`; every field except `captured_at` is optional
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: §4.4 resolves URLs against the document base and checks images against the page URL, which §4.3's `Context` lacks. `None` means "no evidence", not a default (C7).
- Alternatives: Pass them as separate arguments.
- Why: The spec's own §4.4 needs them.
- Reversible: yes

### D-0257 — text and url accept only JSON strings
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: Other JSON values, including JSON-LD value objects (`@value`, `@id`), are `Invalid("not_a_string")`; unwrapping is the collector's job.
- Alternatives: Unwrap value objects in the normalizer.
- Why: schema.org Text and URL values are JSON strings; C8.
- Reversible: yes

### D-0258 — long_text keeps line breaks, collapsing runs of blank lines to one
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: trafilatura runs in the content layer, before normalization.
- Alternatives: Keep only paragraph breaks.
- Why: Preserves structure without guessing.
- Reversible: yes

### D-0259 — Placeholder syntaxes for text
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: `{{…}}`, `${…}`, and printf `%s`/`%d` with an optional `%1$`/`%(name)` prefix, no flags, ending at a word boundary.
- Alternatives: Allow printf flags (reads "100% sure" as `% s`).
- Why: Template placeholders by their syntax (structural), not a word list (C4).
- Reversible: yes

### D-0260 — url keeps an empty query's `?`; hosts lowercased, not IDNA-converted
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: RFC 3986 §6.2.3 removes an empty component's delimiter only where the scheme allows it.
- Alternatives: Drop the `?`; IDNA-encode hosts.
- Why: RFC 3986; SPEC-04 PR 9 (url `equal`) may revisit IDNA.
- Reversible: yes

### D-0261 — url declines input empty after WHATWG trimming
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: The empty check runs after the WHATWG trim and tab/newline removal; only C0 controls, spaces and Unicode White_Space is `Invalid("empty")`.
- Alternatives: Check before trimming (C0-only input resolved to the base).
- Why: INV-06 (review fix).
- Reversible: yes

### D-0262 — text removes Cc controls that are not White_Space
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: Control-only input is `Invalid("empty")`. Default_Ignorable-only strings (ZWSP, BOM) are still accepted pending a separate decision.
- Alternatives: Keep controls.
- Why: Controls are not text, and Postgres `text`/`jsonb` can't store NUL.
- Reversible: yes

### D-0263 — url and text decline lone surrogates
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: A string holding a Unicode Cs code point is `Invalid("surrogate")`, via `base.has_surrogate` (shared, C8); url checks the base only when it resolves against it.
- Alternatives: Replace with U+FFFD.
- Why: It has no UTF-8 encoding (url's `quote()` raised); JSON-LD may carry one as an escape (RFC 8259 §8.2). C7: decline rather than guess.
- Reversible: yes

### D-0264 — Hypothesis `ci` profile and mypy `explicit_package_bases`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 2 (#47) · Status: decided
- Decision: `tests/conftest.py` registers `ci` (`max_examples=200`, SPEC-04 §6), loaded when `CI` is set; `explicit_package_bases = true` lets mypy tell the two conftest files apart.
- Alternatives: `__init__.py` files in test directories.
- Why: SPEC-04 §6's example count in CI.
- Reversible: yes

### D-0271 — schema.org enumeration members ship as typed data until the schema.org file is in the manifest
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 4 (#54) · Status: decided
- Decision: `normalize/vocab/schema/ItemAvailability.json` lists the 12 members, typed from the standard; its JUSTIFICATION.md says to read them from the pinned schema.org file once SPEC-04 PR 7 adds it.
- Alternatives: Wait for PR 7 (no enum `Ok` until then); add the file to the manifest here.
- Why: The spec's open issue names hand-typed members as the fallback; a closed standard enumeration, not an incident list (C4).
- Reversible: yes

### D-0272 — "Longest match wins" applies to overlapping matches only
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 4 (#54) · Status: decided
- Decision: A match inside a longer match's span is dropped; matches at separate places all count, and different codes there are `Ambiguous`.
- Alternatives: The longest match anywhere wins.
- Why: Choosing by length across places would guess between two members (C7).
- Reversible: yes

### D-0273 — Vocabulary language comes from the page
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 4 (#54) · Status: decided
- Decision: Primary subtags of `html_lang`, `og_locale` and `request_locale` (not `hreflang`); with none stated, every language is tried; only languages without a file give `Invalid("no_vocabulary_for_language")`.
- Alternatives: Always try every language; require a stated language.
- Why: Vocabularies are language-tagged (§9); cross-language disagreement still shows as `Ambiguous`.
- Reversible: yes

### D-0274 — `schema:` enum matching is exact and case-sensitive
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 4 (#54) · Status: decided
- Decision: Only surrounding white space is trimmed; `instock` against `schema:ItemAvailability` is `Invalid("not_a_member")`; a JSON-LD node with keys other than `@id` is `Invalid("not_a_string")`.
- Alternatives: Casefold; fall back to `type:availability` phrases.
- Why: schema.org names are case-sensitive; the spec links no `schema:` field to a `type:` vocabulary.
- Reversible: yes

### D-0275 — range resolves currency through the money rules via the dispatcher
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 8 (#56) · Status: decided
- Decision: `range.normalize` takes a keyword-only `money` callable; the dispatcher passes `normalize(·, FieldSpec(type=money), ctx)`.
- Alternatives: Import `money` (breaks the independence contract); copy CLDR symbol resolution (C8 duplication).
- Why: §4.4's "currency through the money rules" with one module per type (C8).
- Reversible: yes

### D-0276 — Range value shape `{min, max, currency, unit, period}`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 8 (#56) · Status: decided
- Decision: Bounds are plain-notation decimal strings; exactly one of `currency`/`unit` is set; `period` is one of the five schema.org unitText values or null.
- Alternatives: One `currency|unit` key.
- Why: Keeps ISO 4217 currency and UN/CEFACT or unitText unit distinguishable for PR 9's `equal`.
- Reversible: yes

### D-0277 — A unit range needs no period; a monetary range does
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 8 (#56) · Status: decided
- Decision: A `QuantitativeValue` with a `unitCode` or non-period `unitText` gives `Ok` with `period: null`; a currency range without a period is `Ambiguous("period_missing")`; a period with neither currency nor unit is `Ambiguous("currency_missing")`.
- Alternatives: Require a period for every range.
- Why: §9's "period unresolved" applies to salary-style amounts; a quantity range has no period.
- Reversible: yes

### D-0278 — A currency written once in range text applies to both bounds
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 8 (#56) · Status: decided
- Decision: If only one bound has text around its amount (`€10-20`, `10-20 EUR`), that text is copied around the other bound before each goes to the money rules; with none, `Ambiguous("currency_missing")`.
- Alternatives: Decline unless both bounds carry it.
- Why: A structural property of written ranges; the money rules still decide the currency.
- Reversible: yes

### D-0279 — Range text needs one separator with an amount on each side
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 8 (#56) · Status: decided
- Decision: A lone text value is `Invalid("not_a_range")`; structured `QuantitativeValue.value` gives min = max.
- Alternatives: Read a lone text amount as min = max.
- Why: §4.4: text is two parses around a separator; `value` is a standard single value.
- Reversible: yes

### D-0280 — `type:period` (en) words live in `range.py` until moved into `vocab/`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 8 (#56) · Status: decided
- Decision: hour/day/week/month/year after "per" or "/", derived from schema.org unitText. Follow-up: move into PR 4's vocab framework with a JUSTIFICATION.md.
- Alternatives: Invent a vocab file format ahead of PR 4.
- Why: Avoided a conflict with PR 4 while both were in flight.
- Reversible: yes

### D-0287 — A GTIN keeps its digits as given
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 6 (#59) · Status: decided
- Decision: No padding of GTIN-12/13 to 14 digits; PR 9's `equal` may compare zero-padded.
- Alternatives: Pad to the GS1 14-digit comparison form.
- Why: §4.4 doesn't require padding; the stored value stays what the page published.
- Reversible: yes

### D-0288 — No separators inside a GTIN; ISBN separators per ISO 2108 are dropped
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 6 (#59) · Status: decided
- Decision: Spaces and hyphens in a GTIN are `Invalid("not_digits")`; ISBNs drop ISO 2108 hyphens, spaces and a leading `ISBN ` prefix.
- Alternatives: Also strip GS1 human-readable spacing.
- Why: §4.4 "digits only"; conservative, relaxable for a class of failures.
- Reversible: yes

### D-0289 — Identifiers accept non-negative JSON integers
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 6 (#59) · Status: decided
- Decision: A non-negative JSON integer is read as its decimal digits; booleans, floats, negatives, lists and objects are `Invalid("not_a_string")`.
- Alternatives: Strings only.
- Why: JSON-LD publishers write `gtin13` unquoted; a lost leading zero shows as a length or check-digit failure, never a silent change.
- Reversible: yes

### D-0290 — An ISBN-13 needs the 978/979 prefix
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 6 (#59) · Status: decided
- Decision: Any other EAN-13 under scheme `isbn` is `Invalid("prefix")`.
- Alternatives: Accept any EAN-13.
- Why: ISO 2108.

### D-0293 — Date order comes from the CLDR locales of `html_lang` and `og_locale`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 5 (#57) · Status: decided
- Decision: A tag with a territory uses its CLDR locale's short date pattern; a language-only tag allows the orders of every CLDR locale of that language (and script), so `en` declines `03/04/2026` while `de` is DMY; no locale allows every order.
- Alternatives: CLDR likely subtags (`en` → `en_US`); also using `cctld_territory`/`request_locale`.
- Why: Likely subtags would act as a default (C7), and §4.4 names only these two sources.
- Reversible: yes

### D-0294 — Numeric dates are parsed by our own code, not `dateparser`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 5 (#57) · Status: decided
- Decision: Three-field numeric dates are read in each allowed order by the module; `dateparser` handles text with words.
- Alternatives: `dateparser` with `DATE_ORDER` for every input.
- Why: `dateparser` silently swaps fields when a reading is invalid, so it cannot report ambiguity.
- Reversible: yes

### D-0295 — A two-digit year is read in every century
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 5 (#57) · Status: decided
- Decision: `yy` is read as 19yy, 20yy and 21yy, and the 1970–2100 range settles which (`26` → 2026; `85` → `Ambiguous`); `dateparser` readings are checked for a year written in full.
- Alternatives: POSIX `%y` pivoting.
- Why: A pivot is a default (C7).
- Reversible: yes

### D-0296 — A datetime needs a time and a numeric offset; output is UTC with `Z`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 5 (#57) · Status: decided
- Decision: Date-only input is `Invalid("no_time")`; a naive time or a zone abbreviation is `Invalid("no_offset")`; `2 hours ago` is `Invalid("relative_datetime")`. A `date` field takes the calendar date the input states in its own offset.
- Alternatives: Keep the source offset in the output; assume UTC for naive times.
- Why: Exact equality (§4.5) needs one form per instant, and an assumed zone is a default (C7).
- Reversible: yes

### D-0297 — Relative dates are detected structurally
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 5 (#57) · Status: decided
- Decision: A reading is relative when it moves with the base time (parsed again with the base one day later); only `day`/`time` periods name a day.
- Alternatives: A list of relative phrases.
- Why: No phrase list (C4); `1 month ago` and `March 2026` do not name a day.
- Reversible: yes

### D-0298 — Relative dates are read against fixed bases
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 5 (#57) · Status: decided
- Decision: `dateparser` reads against two fixed bases and the result is shifted onto `ctx.captured_at`; a reading that is not a plain one-day shift is dropped.
- Alternatives: Use the capture time as `RELATIVE_BASE`.
- Why: `dateparser` keeps every settings object for the life of the process, so a per-page base grows memory per page.
- Reversible: yes

### D-0299 — Date and datetime inputs are strings only
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 5 (#57) · Status: decided
- Decision: Any other JSON value is `Invalid("not_a_string")`.
- Alternatives: Accept JSON numbers as timestamps.
- Why: Structured sources (JSON-LD `datePosted`) carry strings; a number's unit and epoch are not stated.
- Reversible: yes

### D-0300 — Money accepts text, schema.org `price` + `priceCurrency`, or `amount` + `currency`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 3 (#58) · Status: decided
- Decision: A structured amount is a JSON number or a schema.org `price` string (ASCII digits, `.` decimal point, no grouping); a structured currency must be an uppercase ISO 4217 code Babel lists.
- Alternatives: Lenient parsing of structured strings; uppercasing codes.
- Why: schema.org `price` syntax and ISO 4217 define these forms; accepting the normalized form makes labels re-normalizable and idempotence direct.
- Reversible: yes

### D-0301 — Money text with no currency sign is `Invalid("no_currency")`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 3 (#58) · Status: decided
- Decision: This holds even when `page_currencies` holds one code.
- Alternatives: Take the single page currency.
- Why: §4.4 lets a page currency settle a sign, not supply a missing one; the most conservative reading (C7).
- Reversible: yes

### D-0302 — Money's locale set comes from the context tags, then the ccTLD
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 3 (#58) · Status: decided
- Decision: Tags come from `html_lang`, `og_locale`, `request_locale` and `hreflang`. A tag with a territory is used as is; a language-only tag becomes `language_ccTLD` when CLDR has that locale, else every CLDR locale of the language. Tags CLDR can't parse (`x-default`) are ignored; with no tag CLDR knows, the ccTLD stands for its territory's locales. With no locales at all, every CLDR locale counts.
- Alternatives: Read `en` as CLDR's default `en` (US).
- Why: A tag without a territory doesn't say which territory's `$` is meant, so `$` with `lang="en"` stays ambiguous (ARCHITECTURE §9).
- Reversible: yes

### D-0303 — Precedence of money currency evidence
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 3 (#58) · Status: decided
- Decision: (1) an ISO 4217 code names itself; (2) the `page_currencies` codes the sign stands for anywhere in CLDR; (3) the currencies the sign stands for in the locale set; (4) if none, every currency the sign stands for in CLDR. One currency is `Ok`, several are `Ambiguous`.
- Alternatives: Intersect locale and page evidence.
- Why: §4.4 makes a stated page currency decisive for a sign valid for it; an ISO code naming itself also covers CLDR `zh` writing ILR as `ILS`.
- Reversible: yes

### D-0304 — Money locates its own amount and sign, with `price-parser` as fallback
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 3 (#58) · Status: decided
- Decision: The amount is the one run of digits joined by CLDR decimal and group separators; two runs are `Invalid("range")`. The sign is the longest CLDR symbol or ISO code next to the amount, not inside a run of letters; failing that, the sign `price-parser` locates if it is a whole token. A minus sign (U+002D, U+2212) before the amount is `Invalid("not_positive")`.
- Alternatives: Use `price-parser`'s amount and sign as given.
- Why: `price-parser` drops minus signs (`-5 €` gives 5), reads only the first of two amounts, and locates `S$` inside `BS$`.
- Reversible: yes

### D-0305 — Money signs on both sides of the amount must agree; an amount may open with its decimal symbol
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 3 (#58) · Status: decided
- Decision: The longest sign before and the longest after the amount are both read and the currency is what both can denote (`$5 USD` gives USD); none shared (`USD 12 EUR`) is `Invalid("currency_conflict")`. An amount may open with `.` or `,` (`.99`) unless a letter or digit precedes it, and CLDR decides whether it is the decimal symbol.
- Alternatives: Keep the first or shorter sign; drop the leading separator.
- Why: `.99 USD` read as 99 and `USD 12 EUR` resolved to one code, both wrong values (C7).
- Reversible: yes

### D-0306 — Money amounts fit `numeric(18,6)` and keep their written digits
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 3 (#58) · Status: decided
- Decision: An amount must be below 10^12 with at most 6 significant fraction digits (trailing zeros don't count), else `Invalid("out_of_range")`; the output keeps its written digits (`19.90`).
- Alternatives: Round.
- Why: Values must be storable without rounding (D-0005), and §4.5 compares amounts as Decimals.
- Reversible: yes

### D-0312 — Fetched entries in the data manifest
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 7 (#60) · Status: decided
- Decision: A `"fetched": true` entry is absent from git: `data_manifest_check` allows it to be missing and checks its hash when present; `crawlerai data fetch` writes it only after the hash matches.
- Alternatives: Commit the files.
- Why: SPEC-04 §4.6 keeps the GeoNames files out of git.
- Reversible: yes

### D-0313 — The gazetteer is read from the source tree's `backend/data/geonames/`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 7 (#60) · Status: decided
- Decision: Read once per process from `backend/data/geonames/`, the rule calibration follows (`core.engine_version.data_dir`). Without the files, text location input raises `GazetteerMissing` ("run `crawlerai data fetch`"); input that declines on its own never loads it.
- Alternatives: Decline every location silently.
- Why: A missing deployment file should be loud. Follow-up for the image build: run `crawlerai data fetch` and ship `backend/data` (or a settings path) with `VERSION` and calibration.
- Reversible: yes

### D-0314 — Country codes are not read in free text
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 7 (#60) · Status: decided
- Decision: ISO 3166-1 codes are accepted only in structured `addressCountry` (alpha-2 or alpha-3), not in location text.
- Alternatives: Match codes in text too.
- Why: The conservative reading of SPEC-04 §4.4's "country name/code match": alpha-2 codes collide with ISO 3166-2 subdivision abbreviations and short words.
- Reversible: yes

### D-0315 — The country is not implied from the page context
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 7 (#60) · Status: decided
- Decision: `cctld_territory` and the page language never settle a homonym; the languages only choose which CLDR country names and `type:remote` phrases are read.
- Alternatives: Prefer the page's territory.
- Why: C7: no values from URL codes.
- Reversible: yes

### D-0316 — Every place name in location text must fit the value
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 7 (#60) · Status: decided
- Decision: Text naming places no single place fits (a city and a country it is not in, or two countries) is `Invalid("inconsistent")`. A city in several regions of one country, with no region named, gives country and locality with `region: null`.
- Alternatives: Keep the first match.
- Why: SPEC-04 §4.4 ("exists in exactly one country → Ok"); C7.
- Reversible: yes

### D-0317 — A structured address without `addressCountry` is read as text
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 7 (#60) · Status: decided
- Decision: It is read as the text "locality, region" through the text rules.
- Alternatives: Decline it.
- Why: The text rules already resolve or decline homonyms (§4.4).
- Reversible: yes

### D-0318 — `jobLocationType` is read as JSON-LD allows
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 7 (#60) · Status: decided
- Decision: A string, an array of values, or a node object with `@id`; any one TELECOMMUTE value makes the job remote. Any other shape is not remote and never raises.
- Alternatives: Accept strings only.
- Why: JSON-LD 1.1 §4.1 and §4.3; SPEC-04 §4.7 (normalizers never raise on bad input).
- Reversible: yes

### D-0322 — `equal` is reflexive and symmetric for every JSON value
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 9 (#66) · Status: decided
- Decision: Identical values are always equal, whatever their shape; each type's `equal` and `dispatch.equal` start from that.
- Alternatives: Refuse values of the wrong shape, as the old object rule did for unknown keys.
- Why: Eval compares hand-entered labels, and a non-reflexive equality breaks the multiset match.
- Reversible: yes

### D-0323 — Location equality also compares `remote_flag`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 9 (#66) · Status: decided
- Decision: Country, casefolded locality, region only when both have one (§4.5), and `remote_flag`.
- Alternatives: Only §4.5's three parts.
- Why: A remote job and an on-site one in the same country differ; the conservative reading.
- Reversible: yes

### D-0324 — GTINs compare in the GS1 14-digit form
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 9 (#66) · Status: decided
- Decision: `identifier.equal` left-pads GTIN-8/12/13 with zeros to 14 digits; other schemes compare exactly.
- Alternatives: Exact (§4.5).
- Why: D-0287 left this to PR 9; GS1 General Specifications §3.3.2.
- Reversible: yes

### D-0325 — List `normalize`: a single value is a list of one; reasons in `Ok.reasons`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 9 (#66) · Status: decided
- Decision: With no item `Ok`, the list is `Ambiguous("no_item")` if any item was ambiguous, else `Invalid("no_item")`; dropped items are reported as `<path>: <reason>`.
- Alternatives: Refuse non-lists; pick an item's options.
- Why: JSON-LD 1.1 §4.3.1 treats a value and a one-element array alike; options for a whole list would be a cross product.
- Reversible: yes

### D-0326 — Object `normalize` ignores unnamed keys and treats `null` as missing
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 9 (#66) · Status: decided
- Decision: The value holds only the sub-fields that normalized; a required one that declines declines the object.
- Alternatives: Refuse extra keys; emit nulls.
- Why: Structured sources carry `@type` and more; JSON-LD drops nulls.
- Reversible: yes

### D-0327 — The labeling API returns `FieldSpec` in `PageDetail.fields`
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 9 (#66) · Status: decided
- Decision: `FieldShape` goes (D-0167); `eval` uses `FieldSpec` and `dispatch.equal`; the TS client is regenerated.
- Alternatives: Keep a separate shape model.
- Why: One model for schema fields (C8); the response is a superset of the old one.
- Reversible: yes

### D-0328 — `type:period` phrases are "per <unit>" per language
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 9 (#66) · Status: decided
- Decision: `vocab/type/period/en.json`; the solidus form `/<unit>` takes the phrase's last word; only the page's languages are read (all when it states none).
- Alternatives: Keep English "per" in code.
- Why: C4 and §9: language-tagged vocabularies; the solidus is SI/ISO 80000-1 notation for "per". Closes D-0280's follow-up.
- Reversible: yes

### D-0329 — url percent-decodes a domain host and refuses forbidden domain code points
- Date: 2026-10-13 · Spec/PR: SPEC-04 PR 9 (#66) · Status: decided
- Decision: `Invalid("forbidden_host_code_point")`, or `Invalid("unparsable")` when the host decodes to invalid UTF-8.
- Alternatives: Keep the host percent-encoded.
- Why: WHATWG URL Standard, host parsing.
- Reversible: yes

### D-0773 — Page currencies come from structured data only, read in `collect`
- Date: 2026-10-14 · Spec/PR: SPEC-04 §4.4, UAT accuracy R1a (#161) · Status: decided
- Decision: `Context.page_currencies` is the ISO 4217 codes the page writes, as written, in schema.org `priceCurrency` (any node, in JSON-LD, microdata or RDFa Lite) or OGP `product:price:currency`. `collect.currencies.with_stated_currencies` sets it after `page_context` in the pipeline, held-out validation and the labeling prefill. This fills what D-0487 left empty.
- Alternatives: Read them in `content/context.py`, which sits below the collectors and cannot use their scope rules; read only Offer nodes, which misses PriceSpecification and AggregateOffer.
- Why: SPEC-04 §4.4 names the page's structured data as the source; a page currency only narrows a symbol the text writes, never supplies a missing one (D-0301).
- Reversible: yes

### D-0781 — Preset `commerce_detail` version 2: `brand` optional
- Date: 2026-10-15 · Spec/PR: ARCHITECTURE §5.3, Appendix A #35; SPEC-04 §4.2 (#167) · Status: decided (owner answer, accuracy Q1)
- Decision: `commerce_detail` version 2 drops `required` from `brand`. Version 1 rows stay stored. The other Q1 options are not decided: `url` from the final URL stays open as D-0355, and an "absent" field status is D-0784.
- Alternatives: Keep `brand` required (role C asked on every page of a site that never shows a brand).
- Why: Owner, 2026-10-14: "brand is not that important." In the UAT re-run, brand was absent from the pages of 4 sites, so those records were never complete and role C ran on every page.
- Reversible: yes (a later preset version)

### D-0882 — A `schema:` enum reads member text through its type vocabularies
- Date: 2026-10-16 · Spec/PR: follow-up (#200) · Status: decided
- Decision: A string that is neither a member name nor an absolute IRI (RFC 3987) is matched as the `type:` path does against every type vocabulary whose codes are all members of the enumeration (today `type:availability` for `ItemAvailability`); two members are `Ambiguous`, none is `Invalid("not_a_member")`. Takes, for text only, the alternative D-0274 set aside.
- Alternatives: Switch the preset to `type:availability` (loses IRIs); an explicit enumeration-to-vocabulary map.
- Why: SPEC-04 §4.4 builds `type:availability` from the `ItemAvailability` members, so codes ⊆ members is the structural link (C2); DOM availability text otherwise never normalizes.
- Reversible: yes

### D-0883 — Range word separators are a type vocabulary
- Date: 2026-10-16 · Spec/PR: follow-up (#200) · Status: decided
- Decision: `type:range_to` (en: "to") holds the words that separate a range's bounds, read in the page's languages only; hyphen-minus and en dash stay in code.
- Alternatives: Keep "to" in `range.py` for every page.
- Why: C4, and period words already work this way (D-0328).
- Reversible: yes

### D-0920 — Enum text is read by its whole first clause
- Date: 2026-10-16 · Spec/PR: SPEC-04 PR 10 (#203) · Status: decided
- Decision: Text states an enum member only when its first clause (Unicode L, M, Zs, Pd, Pc up to the first other character; a leading digit leaves it empty) equals one of the member's phrases or, for `schema:` enums, the member name in token form (`instock`); another member's phrase later in the text is `Ambiguous` (`vocab.stated_codes`, INV-37). Members stay the shipped transcription of the standard; "available" has no versioned source and declines.
- Alternatives: D-0782 option (b), the leading token run ("In stock soon" would give `InStock`); a negation word list (C4); reading the fetched schema.org file at normalize time (not fetched in CI).
- Why: the structural rule that never turns "Not in stock" into `InStock` (C7); replaces D-0882's anywhere match.
- Reversible: yes

### D-0921 — The `count` field type
- Date: 2026-10-16 · Spec/PR: SPEC-04 PR 11 (#203) · Status: decided
- Decision: A non-negative whole number from a JSON number, a schema.org `QuantitativeValue` with no unit or `unitCode` `C62` (UN/CEFACT Rec. 20 "one"), or the one number in a text read by the page's CLDR locales. Fractions, negatives, ranges, other units and two numbers decline; not a checkable type.
- Alternatives: `range` with min = max; `text`; accepting any `unitText`.
- Why: ARCHITECTURE §5.1 adds a type with its own module (C8); units are not guessed (C7).
- Reversible: yes

### D-0922 — CLDR number reading lives in `normalize.numbers`
- Date: 2026-10-16 · Spec/PR: SPEC-04 PR 11 (#203) · Status: decided
- Decision: Money's locale set, number readings, JSON-number decimal and minus rule moved unchanged to `normalize.numbers`, in the `vocab` layer of the import contract; money and count both use them.
- Alternatives: count imports money (breaks the independence contract); a second copy (C8).
- Why: one way to read a number (C8).
- Reversible: yes

### D-0923 — `commerce_detail` version 4: `stock_quantity`
- Date: 2026-10-16 · Spec/PR: SPEC-04 PR 11 (#203) · Status: decided
- Decision: Optional count `stock_quantity` (`Offer.inventoryLevel`) at the top level and in each `variants` row; required fields, completeness and `record_fingerprint` unchanged. As an Offer field it follows the atomic-offer rule.
- Alternatives: rows only; a new preset.
- Why: owner answer to D-0782 (per variant when stated so, else the page's value).
- Reversible: costly (a later version)

### D-0924 — The frontend lists the `count` type
- Date: 2026-10-16 · Spec/PR: SPEC-04 PR 11 (#203) · Status: decided
- Decision: The regenerated `FieldType` adds `count` to the frontend registries it must appear in (`schemaDocument.ts` label, `field.ts` scalar list); its value renders as a plain number.
- Alternatives: none; `Record<FieldType, …>` fails the build without it.
- Why: generated types are the authority (ENGINEERING "Type-system discipline").
- Reversible: yes

### D-0960 — A `number` field type
- Date: 2026-10-16 · Spec/PR: SPEC-04 PR 12 (#208) · Status: decided
- Decision: A decimal as the page states it, from a JSON number or the one number in a text, read through `normalize.numbers.stated` (shared with count). The value is a fixed-point string with its digits as written, and equality compares decimals. No number, two numbers ("4.5 out of 5") or a minus set apart from the digits decline; a number the locales read differently is `Ambiguous`. Not checkable.
- Alternatives: `count` (refuses fractions); `text` (4.5 ≠ 4.50); rescaling ratings to a common scale (enrichment, C7).
- Why: `rating` (`aggregateRating.ratingValue`) needs a decimal; ARCHITECTURE §5.1 (Appendix A #42).
- Reversible: yes

### D-0961 — `commerce_detail` optional fields the page states, edited in place
- Date: 2026-10-16 · Spec/PR: SPEC-04 PR 12 (#208) · Status: decided
- Decision: Optional `description`, `additional_images`, `color`, `material`, `gender`, `condition` (OfferItemCondition members added), `rating`, `review_count`, `mpn` and `product_id`, and `variant_id` per variant row, each mapped to its schema.org path. The preset is edited in place with no version bump. Nothing derived (no variant or image counts).
- Alternatives: a version 5; a separate preset.
- Why: owner, 2026-10-16: greenfield, extract don't enrich (Appendix A #42).
- Reversible: yes

### D-0962 — The frontend lists the `number` type
- Date: 2026-10-16 · Spec/PR: SPEC-04 PR 12 (#208) · Status: decided
- Decision: The regenerated `FieldType` adds `number` to `schemaDocument.ts` and the `field.ts` scalar list, as D-0924 did for `count`.
- Alternatives: none; `Record<FieldType, …>` fails the build without it.
- Why: generated types are the authority.
- Reversible: yes

### D-0967 — `apply_url` stays `JobPosting.url` (eval class 13)
- Date: 2026-10-16 · Spec/PR: reference-eval follow-ups (#209) · Status: decided
- Decision: No change to the mapping (D-0015). The eval's JobPosting states `directApply: true` and no `url`; its external link is in the DOM only, told apart only by its text; no dev page states an `ApplyAction`.
- Alternatives: Map `potentialAction.target`; pick the link by its text.
- Why: Link text is a word list (C4) and a DOM heuristic is the §22 structural-collector candidate (D-0946); `directApply: true` agrees with the posting URL. `ApplyAction` waits for a dev page that shows it (C5).
- Reversible: yes.

### D-0950 — A schema edit is in place and sends the schema's sites back to learning
- Date: 2026-10-16 · Spec/PR: greenfield (#210) · Status: decided
- Decision: One `schema_def` row per name; `PUT` rewrites the document. A changed document runs `progressive.relearn_schema`: the schema's `active` configs become `suspended` (drafts stay), its states go `cold` (a `schema_edit` transition) with no run in flight and `active_config_id`, `retry_at_pages` cleared, `pages_extracted` kept. An unchanged document changes nothing. A learning run the edit overtook ends its job `failed` with `schema_edited` and touches no state (it compares `document_digest` of its document with the current one). A retired schema or a preset is 409. `crawlerai schemas sync` upserts presets the same way.
- Alternatives: a new `relearn` config status; deleting learned configs; keeping versions.
- Why: ARCHITECTURE §5.2, Appendix A #43 (owner, greenfield). A run started before the edit can then neither activate nor fail its state (`NotLearning`).
- Reversible: costly — versions would come back in the tables, API and IR.

### D-0953 — `location` publishes what the page states; country codes only as stated
- Date: 2026-10-16 · Spec/PR: greenfield (#210) · Status: decided
- Decision: The value is `{text, locality, region, country, remote_flag}`. `country` only from an `addressCountry` that is an ISO 3166-1 alpha-2 code as CLDR lists territories (via Babel) less ISO 3166-1's user-assigned codes (AA, QM–QZ, X*, ZZ); other two-letter values are `Invalid("unknown_country")`, a country name gets no code. Location is no longer a checkable type: any string is a location's text.
- Alternatives: keep a gazetteer; derive codes from Babel's territory names.
- Why: Appendix A #43: "our job is to extract page data, not change it"; C7 (decline rather than guess).
- Reversible: yes — a lookup could be added back as a separate step.

### D-1058 — Owner answer to D-0946 class 11: a job location publishes as written
- Date: 2026-10-16 · Spec/PR: SPEC-04 §4.4, ARCHITECTURE §9 (#216) · Status: confirmed
- Decision: "just display whatever is written in jobs location." No macro-region parsing and no "or" split: a location text naming several places stays one `text`. The only change to the value is that each whitespace run in the text and the stated address parts becomes one space (it was NFC and trimmed only). Structured parts stay where the page states them structurally (`PostalAddress`).
- Alternatives: a new location representation with regions and alternatives (round-1 class 11 as framed in D-0946).
- Why: owner answer, 2026-10-16 (Appendix A #44); extract, never enrich (Appendix A #43).
- Reversible: yes
