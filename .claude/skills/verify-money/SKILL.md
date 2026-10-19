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
  `_narrowed`, `url_currency`, `_money`;
- `backend/src/crawlerai/normalize/numbers.py`: `stated`, `_percentage`, `compact_unit`, `readings`, `locale_set`;
- `backend/src/crawlerai/llm/grounding.py`: `align`, `_sign_spaced` (money claims);
- `backend/src/crawlerai/normalize/base.py` (`Context`), `backend/tests/property/test_money_properties.py`,
  `backend/tests/conftest.py` (the `verify` profile), `backend/pyproject.toml` / `backend/uv.lock` (Babel, CLDR data,
  price-parser, Hypothesis).

Last confirmed in sync with the code at `ef91d81a` (after #315, URL-currency fill).

## The one command

```
cd backend && uv run pytest tests/property/test_money_properties.py -q --hypothesis-profile=verify
```

About 20 s; 2000 examples per property, no deadline. Green is `6 passed`. The default and `ci` profiles (`pytest`,
the full CI suite) run the same file with fewer examples.

## Properties (one test each)

| Test | Property |
| --- | --- |
| `test_a_grounded_amount_always_publishes_with_a_currency_from_evidence_or_none` | A price written as a page in the drawn locale writes it (CLDR symbols via Babel), with or without a sign, or as schema.org `price`, is `Ok` with exactly that amount. Currency is `null` exactly when basis is `unknown`; an ISO code written beside it is the currency; otherwise the currency is one the sign, the page or the URL names, never invented. |
| `test_a_grounded_money_value_is_a_span_of_the_page_text_with_the_claimed_amount` | A model claim spaced differently from the page between sign and digits grounds (`align(..., money=True)`) at a span that is `text[start:end]`, and normalizes to the same amount as the claim. |
| `test_a_money_claim_the_text_does_not_write_alone_is_not_grounded` | A claim of an amount the text lacks, of one end of a range, or of the tail of a grouped number (`219.98 €` in `1 219.98€`) is not grounded. |
| `test_a_percentage_is_never_a_price` | A ratio with a CLDR percent sign (before or after, spaces and bidi marks allowed, with or without a minus) is `no_amount`, as text or as `price`; beside a price it never replaces it. |
| `test_a_cldr_compact_unit_multiplies_the_amount` | `amount + unit` (CLDR `decimalFormats-short` of the page locale, e.g. `万`, ` Mio.`, `L`) is `amount × 10^power`, or `out_of_range` at ≥ 10^12; a Latin unit followed by a letter (`12Kg`) does not multiply. |
| `test_an_explicit_currency_beats_the_url_one_and_currency_fill_never_changes_the_amount` | A URL naming one territory (locale segment, country subdomain, ccTLD; final or requested URL) fills its single CLDR tender currency, basis `url` (else `null`/`unknown`); `priceCurrency`, a single page or declared currency, or an ISO code written with the amount always wins; the amount is identical with and without the URL. |

Bounds: locales `en-US en-GB en-IN de-DE fr-FR fr-CH ja-JP zh-CN ko-KR es-ES pt-BR hi-IN`, amounts 0.01 to
999 999 999.99 with two places, every CLDR territory with currency data, every ISO 4217 code. Out of scope: ranges,
negative amounts, ambiguous decimal separators (example tests in `tests/property/test_normalize_money.py` cover them),
and the resolver.

## Reading a failure: real bug or model error

Hypothesis prints the shrunk input (`Failing test case: ...`). Replay it by hand first:

```
cd backend && uv run python -c "from datetime import UTC, datetime; from crawlerai.normalize import money; \
from crawlerai.normalize.base import Context; from crawlerai.schemas.types import FieldSpec, FieldType; \
print(money.normalize('USD 0.01 1%', FieldSpec(type=FieldType.MONEY), Context(captured_at=datetime(2026, 1, 1, tzinfo=UTC), html_lang='en-US')))"
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
  correctly). Fix the generator or the expectation, with a comment saying why.

If in doubt, read the normalization spec's "money" section (`openspec/specs/`) and the module docstring: the
property must follow them, not the other way round.

## Known findings (open)

- **KF-1** `numbers.stated`: white space alone between a price and a ratio not opened by a minus drops the price:
  `USD 0.01 1%` (digit runs join across the space: `0.01 1%` is one run, a percentage) and `USD 0.01 %1` (the `%`
  is read as the price's own suffix) are `Invalid("no_amount")`. Excluded in `test_a_percentage_is_never_a_price`.
- **KF-2** `grounding._sign_spaced`: a claim whose digits open a grouped amount grounds at its head:
  `align(SpanClaim("$ 4", ...), "Now $4,000", money=True)` is `$4`. Excluded in `_ungroundable` (range case).

When a finding is fixed, delete its `assume(...)` and its entry here in the same PR.

## Updating the properties when behaviour changes on purpose

1. The owner decision or spec change comes first (`openspec/specs/`, decision id in the PR).
2. Change the property's expectation (and the table above) in the same PR as the code; keep the property general:
   no per-site or per-case literals, no fixed example where a generator can draw it.
3. Run the one command, then break the property on a scratch edit of the code to confirm it still fails, and revert.
4. Move "Last confirmed in sync" to the new base commit only after the run is green.
5. Delete example tests the properties now subsume; never add one per case.
