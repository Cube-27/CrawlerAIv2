---
name: verify-money
description: Hypothesis property checks of money on the real code. Use when a diff touches backend/src/crawlerai/normalize/money.py, backend/src/crawlerai/normalize/numbers.py, backend/src/crawlerai/llm/grounding.py, or backend/tests/property/test_money_properties.py, or changes how a price, its currency (page, locale or URL), a percentage or a CLDR compact unit is read.
---

# verify-money

Money is the field the product is judged on: a skipped price, a discount read as the price, `3.5万` read as 3.5, or
a URL guess overriding the currency the page states each publish a wrong record silently. This skill checks those
outcomes on generated inputs, against the real code (no mocks).

## Applies when

The diff touches any of these (the CI job `verify-money` is filtered on the same paths, `tools/ci_changes.py`):

- `backend/src/crawlerai/normalize/money.py`: `normalize`, `_text`, `_structured`, `_currency_of`, `_unwritten`,
  `_narrowed`, `url_currency`, `_money`, `_sign_forms` (bidi controls, trailing full stop), the minor-unit filter;
- `backend/src/crawlerai/normalize/numbers.py`: `stated`, `_percentage`, `compact_unit`, `readings`, `locale_set`,
  `_conventions` (CLDR `latn`/`arab`/`arabext` symbols, group-symbol fallbacks, page convention);
- `backend/src/crawlerai/llm/grounding.py`: `align`, `_sign_spaced` (money claims);
- `backend/src/crawlerai/normalize/units.py`: `per_suffix` (an amount per a CLDR unit or period);
- `backend/src/crawlerai/normalize/base.py` (`Context`), `backend/tests/property/test_money_properties.py`,
  `backend/tests/conftest.py` (the `verify` profile), `backend/pyproject.toml` / `backend/uv.lock` (Babel, CLDR data,
  price-parser, Hypothesis).

Last confirmed in sync with the code at `eeb57101` plus the P8 locale change (`numbers.readings`, `locale_set`), the
PR 6 per-unit reading (`units.per_suffix`) and the PR 7 currency and number fixes (minor units, symbol forms, Arabic
conventions, page convention).

## The one command

```
cd backend && uv run pytest tests/property/test_money_properties.py -q --hypothesis-profile=verify
```

About 30 s; 2000 examples per property, no deadline. Green is `8 passed`. The default and `ci` profiles (`pytest`,
the full CI suite) run the same file with fewer examples.

## Properties (one test each)

| Test | Property |
| --- | --- |
| `test_a_grounded_amount_always_publishes_with_a_currency_from_evidence_or_none` | A price written as a page in the drawn locale writes it (CLDR symbols via Babel), with or without a sign, or as schema.org `price`, is `Ok` with exactly that amount, except a text amount with more decimals than the minor unit of a currency the evidence names, which is `Invalid("minor_unit")`; a published currency's minor unit holds the amount. Currency is `null` exactly when basis is `unknown`; an ISO code written beside it is the currency; otherwise the currency is one the sign, the page or the URL names, never invented. |
| `test_a_grounded_money_value_is_a_span_of_the_page_text_with_the_claimed_amount` | A model claim spaced differently from the page between sign and digits grounds (`align(..., money=True)`) at a span that is `text[start:end]`, and normalizes to the same amount as the claim. |
| `test_a_money_claim_the_text_does_not_write_alone_is_not_grounded` | A claim of an amount the text lacks, of one end of a range, or of the head or tail of a grouped or decimal number (`$ 4` in `$4,000`, `219.98 €` in `1 219.98€`) is not grounded. |
| `test_a_percentage_is_never_a_price` | A ratio with a CLDR percent sign (before or after, spaces and bidi marks allowed, with or without a minus) is `no_amount`, as text or as `price`; beside a price (white space alone between them included: `USD 0.01 1%`, `USD 0.01 %1`) it never replaces it. |
| `test_a_cldr_compact_unit_multiplies_the_amount` | An amount Babel's own compact formatter writes for the page locale (CLDR `decimalFormats-short`: `3.5万`, `12,345 Mio.`, `1.5L`) reads back as that amount. The oracle is Babel's formatter, not the reader's unit table. |
| `test_a_compact_unit_that_starts_a_word_is_no_unit` | An `en` unit followed by a letter (`12Kg`) does not multiply. |
| `test_a_reading_with_more_decimals_than_the_currency_minor_unit_never_publishes` | An amount written with more decimals than its currency's ISO 4217 minor unit (Babel `get_currency_precision`), in the drawn locale, with its ISO code or the page's stated currency, never publishes as that amount: whatever publishes is in that currency with at most its minor unit's decimals. |
| `test_an_explicit_currency_beats_the_url_one_and_currency_fill_never_changes_the_amount` | A URL naming one territory (locale segment, country subdomain, ccTLD; final or requested URL) fills its single CLDR tender currency, basis `url` (else `null`/`unknown`); `priceCurrency`, a single page or declared currency, or an ISO code written with the amount always wins; the amount is identical with and without the URL. |

Bounds: locales `en-US en-GB en-IN de-DE fr-FR fr-CH ja-JP zh-CN ko-KR es-ES pt-BR hi-IN`, amounts 0.01 to
999 999 999.99 with two places (the grounding and URL properties keep to the minor unit of the currency they write), every CLDR territory with currency data, every ISO 4217 code. Out of scope: ranges,
negative amounts, ambiguous decimal separators (example tests in `tests/property/test_normalize_money.py` cover them),
and the resolver.

## Reading a failure: real bug or model error

Hypothesis prints the shrunk input (`Failing test case: ...`) and replays it first on the next run of the command
(its example database). Replay it by hand too:

```
cd backend && uv run python -c "from datetime import UTC, datetime; from crawlerai.normalize import money; \
from crawlerai.normalize.base import Context; from crawlerai.schemas.types import FieldSpec; \
print(money.normalize('USD 0.01 1%', FieldSpec(type='money'), Context(captured_at=datetime(2026, 1, 1, tzinfo=UTC), html_lang='en-US')))"
```

Then decide:

- **Real bug**: a real page could write that input (a CLDR locale writes the number that way, the sign is a CLDR
  symbol or ISO code, the URL shape occurs) and the output breaks the owner rule the property states (a skipped
  price, a wrong amount, a URL currency beating a stated one). Fix the code; never weaken the property. If the fix is
  out of scope, record it under Known findings with the shrunk input and exclude exactly that shape with an
  `assume(...)` naming the finding.
- **Model (generator) error**: the input is not something a page writes, or the expectation ignores a rule the code
  is right to apply. Examples met while writing this skill: `%-1` (CLDR writes the minus before a leading percent
  sign: `-%1`); `0,1 mil Mg` in `es-ES` (the longer unit ` mil M` starts a word, so the shorter ` mil` applies,
  correctly); `EUR 1Br` (`Br` is a CLDR currency symbol, so the text writes two currencies). Fix the generator or the expectation, with a comment saying why.

If in doubt, read the normalization spec's "money" section (`openspec/specs/`) and the module docstring: the
property must follow them, not the other way round.

## Known findings (open)

None.

When a finding is fixed, delete its `assume(...)` and its entry here in the same PR.

## Updating the properties when behaviour changes on purpose

1. The owner decision or spec change comes first (`openspec/specs/`, decision id in the PR).
2. Change the property's expectation (and the table above) in the same PR as the code; keep the property general:
   no per-site or per-case literals, no fixed example where a generator can draw it.
3. Run the one command, then break the property on a scratch edit of the code to confirm it still fails, and revert.
4. Move "Last confirmed in sync" to the new base commit only after the run is green.
5. Delete example tests the properties now subsume; never add one per case.
