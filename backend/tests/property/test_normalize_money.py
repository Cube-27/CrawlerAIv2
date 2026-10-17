"""The money normalizer (SPEC-04 §4.4, ARCHITECTURE §9): CLDR currency symbols and number symbols (Babel) for the
locales the context states, `price-parser` to locate the amount, and declines on ambiguous signs, ambiguous decimal
separators, ranges and amounts that are not positive.

The oracle for currency symbols is Babel's CLDR data, read here directly; the tests use ISO codes and CLDR symbols
only (SPEC-04 §6)."""

import unicodedata
from datetime import UTC, datetime
from decimal import Decimal
from functools import cache

import pytest
from babel import Locale
from babel.localedata import locale_identifiers
from babel.numbers import format_currency, list_currencies
from hypothesis import assume, given
from hypothesis import strategies as st
from price_parser import Price
from pydantic import JsonValue

from crawlerai.normalize import money
from crawlerai.normalize.base import Ambiguous, Context, Invalid, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType

AT = datetime(2026, 1, 1, tzinfo=UTC)
CTX = Context(captured_at=AT)
MONEY = FieldSpec(type=FieldType.MONEY)


@cache
def _symbols_by_locale() -> dict[str, dict[str, str]]:
    """CLDR: each locale's currency symbols (NFKC), by ISO 4217 code."""
    return {
        identifier: {
            code: unicodedata.normalize("NFKC", s) for code, s in Locale.parse(identifier).currency_symbols.items()
        }
        for identifier in locale_identifiers()
    }


@cache
def _symbols() -> dict[str, frozenset[str]]:
    """CLDR: every currency symbol (NFKC) and the currencies it stands for in some locale."""
    by_symbol: dict[str, set[str]] = {}
    for symbols in _symbols_by_locale().values():
        for code, symbol in symbols.items():
            by_symbol.setdefault(symbol, set()).add(code)
    return {symbol: frozenset(codes) for symbol, codes in by_symbol.items()}


def _located(sign: str) -> bool:
    # price-parser locates the sign (single letters such as `K` are not located, and decline as `no_currency`).
    return Price.fromstring(f"{sign} 12").currency == sign


# A symbol that is itself an ISO 4217 code names that currency (CLDR `zh` writes ILR, the old sheqel, as `ILS`).
_ISO_CODES = frozenset(list_currencies())
_SHARED = sorted(s for s, codes in _symbols().items() if len(codes) > 1 and s not in _ISO_CODES)
_LOCATED_SHARED = [s for s in _SHARED if _located(s)]
_CODES = sorted(c for c in _ISO_CODES if _located(c))
# One locale per CLDR number convention the tests write amounts in: `.` decimal with `,`, U+2019 and narrow no-break
# space groups, and `,` decimal with `.` groups.
_CONVENTIONS = ["en_US", "de_DE", "fr_FR", "de_CH"]
_amounts = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("999999999.99"), places=2)


@pytest.mark.parametrize("sign", _SHARED)
def test_a_shared_symbol_without_context_is_ambiguous_over_its_currencies(sign: str) -> None:
    over_its_currencies = Ambiguous(
        "currency_symbol", tuple({"amount": "12", "currency": c} for c in sorted(_symbols()[sign]))
    )

    result = money.normalize(f"{sign} 12", MONEY, CTX)

    # A sign `price-parser` does not locate on its own may still decline as no currency; never Ok (C7).
    assert result == over_its_currencies or (not _located(sign) and result == Invalid("no_currency"))


@given(st.data())
def test_one_page_currency_the_symbol_stands_for_settles_it(data: st.DataObject) -> None:
    sign = data.draw(st.sampled_from(_LOCATED_SHARED))
    code = data.draw(st.sampled_from(sorted(_symbols()[sign])))
    ctx = Context(captured_at=AT, page_currencies=(code,))

    assert money.normalize(f"{sign} 12", MONEY, ctx) == Ok({"amount": "12", "currency": code})


@given(
    st.sampled_from(sorted(_symbols())),
    st.lists(st.sampled_from(["en", "en-US", "en-CA", "fr", "de-DE", "es-MX", "ja", "zh-Hant-TW", "x-default"])),
    st.lists(st.sampled_from(_CODES[:40]), max_size=2),
    st.sampled_from([None, "CA", "AU", "DE"]),
)
def test_an_ok_currency_is_backed_by_the_evidence(
    sign: str, tags: list[str], page_currencies: list[str], cctld: str | None
) -> None:
    ctx = Context(captured_at=AT, hreflang=tuple(tags), page_currencies=tuple(page_currencies), cctld_territory=cctld)

    result = money.normalize(f"{sign} 12", MONEY, ctx)

    if isinstance(result, Ok):
        assert isinstance(result.value, dict)
        code = result.value["currency"]
        assert isinstance(code, str)
        # The sign is its ISO 4217 code, the page states it, the sign stands for it in the evidence's locales, or the
        # sign stands for nothing else in CLDR.
        assert (
            code == sign
            or code in page_currencies
            or _symbols().get(sign) == frozenset({code})
            or _valid_in_some_locale(sign, code, ctx)
        )


def _valid_in_some_locale(sign: str, code: str, ctx: Context) -> bool:
    languages = {Locale.parse(t, sep="-").language for t in ctx.hreflang if t != "x-default"}
    return any(
        symbols.get(code) == sign
        for i, symbols in _symbols_by_locale().items()
        if i.partition("_")[0] in languages or (not languages and i.endswith(f"_{ctx.cctld_territory}"))
    )


@pytest.mark.parametrize(("tag", "currency"), [("en-US", "USD"), ("en-CA", "CAD"), ("en-AU", "AUD"), ("es-MX", "MXN")])
def test_a_territory_settles_the_dollar_sign(tag: str, currency: str) -> None:
    ctx = Context(captured_at=AT, html_lang=tag)

    assert money.normalize("$12.99", MONEY, ctx) == Ok({"amount": "12.99", "currency": currency})


def test_a_language_without_a_territory_does_not_settle_the_dollar_sign() -> None:
    result = money.normalize("$12.99", MONEY, Context(captured_at=AT, html_lang="en"))

    assert isinstance(result, Ambiguous)
    assert {"amount": "12.99", "currency": "USD"} in result.options
    assert {"amount": "12.99", "currency": "CAD"} in result.options


def test_the_cctld_territory_completes_a_language_without_one() -> None:
    ctx = Context(captured_at=AT, html_lang="en", cctld_territory="CA")

    assert money.normalize("$12.99", MONEY, ctx) == Ok({"amount": "12.99", "currency": "CAD"})


def test_a_tag_cldr_does_not_know_leaves_the_cctld_territory_as_evidence() -> None:
    ctx = Context(captured_at=AT, html_lang="x-default", cctld_territory="CA")

    assert money.normalize("$12.99", MONEY, ctx) == Ok({"amount": "12.99", "currency": "CAD"})


@given(
    st.sampled_from(_CODES),
    st.integers(min_value=1, max_value=99),
    st.sampled_from([("en-US", "."), ("de-DE", ",")]),
    st.booleans(),
)
def test_an_amount_below_one_written_from_its_decimal_symbol_reads_back(
    code: str, cents: int, locale: tuple[str, str], code_first: bool
) -> None:
    tag, decimal = locale
    written = f"{decimal}{cents:02d}"
    raw = f"{code} {written}" if code_first else f"{written} {code}"

    result = money.normalize(raw, MONEY, Context(captured_at=AT, html_lang=tag))

    assert result == Ok({"amount": f"0.{cents:02d}", "currency": code})


@given(st.lists(st.sampled_from(_CODES), min_size=2, max_size=2, unique=True), st.integers(min_value=1))
def test_two_codes_around_one_amount_conflict(codes: list[str], amount: int) -> None:
    assert money.normalize(f"{codes[0]} {amount} {codes[1]}", MONEY, CTX) == Invalid("currency_conflict")


@given(st.sampled_from(_LOCATED_SHARED), st.integers(min_value=1, max_value=99_999), st.data())
def test_a_code_after_a_shared_symbol_settles_it(sign: str, amount: int, data: st.DataObject) -> None:
    code = data.draw(st.sampled_from(sorted(_symbols()[sign])))

    assert money.normalize(f"{sign}{amount} {code}", MONEY, CTX) == Ok({"amount": str(amount), "currency": code})


@given(st.sampled_from(_CODES), _amounts, st.sampled_from(_CONVENTIONS))
def test_an_amount_written_in_the_page_locale_reads_back(code: str, amount: Decimal, locale: str) -> None:
    written = format_currency(amount, code, format="#,##0.00 ¤¤", locale=locale, currency_digits=False)
    ctx = Context(captured_at=AT, html_lang=locale.replace("_", "-"))

    assert money.normalize(written, MONEY, ctx) == Ok({"amount": f"{amount:.2f}", "currency": code})


@given(st.integers(min_value=1, max_value=999), st.integers(min_value=0, max_value=999))
def test_a_lone_group_or_decimal_separator_without_context_is_ambiguous(head: int, tail: int) -> None:
    result = money.normalize(f"{head}.{tail:03d} EUR", MONEY, CTX)

    assert result == Ambiguous(
        "decimal_separator",
        (
            {"amount": f"{head}.{tail:03d}", "currency": "EUR"},
            {"amount": f"{head}{tail:03d}", "currency": "EUR"},
        ),
    )


@pytest.mark.parametrize(("tag", "amount"), [("en-US", "1.234"), ("de-DE", "1234")])
def test_the_page_locale_settles_the_decimal_separator(tag: str, amount: str) -> None:
    assert money.normalize("1.234 EUR", MONEY, Context(captured_at=AT, html_lang=tag)) == Ok(
        {"amount": amount, "currency": "EUR"}
    )


def test_locales_that_disagree_on_the_decimal_separator_decline() -> None:
    ctx = Context(captured_at=AT, html_lang="en-US", og_locale="de_DE")

    result = money.normalize("1.234 EUR", MONEY, ctx)

    readings: tuple[JsonValue, ...] = ({"amount": "1.234", "currency": "EUR"}, {"amount": "1234", "currency": "EUR"})
    assert result == Ambiguous("decimal_separator", readings)


@given(st.sampled_from(_CODES), st.decimals(max_value=0, places=2, allow_nan=False, allow_infinity=False))
def test_a_structured_amount_that_is_not_positive_is_invalid(code: str, amount: Decimal) -> None:
    # A negative string is not schema.org `price` syntax: the text reader reads it, and declines its minus.
    assert money.normalize({"price": str(amount), "priceCurrency": code}, MONEY, CTX) == Invalid("not_positive")
    assert money.normalize({"amount": float(amount), "currency": code}, MONEY, CTX) == Invalid("not_positive")


@pytest.mark.parametrize("raw", ["-12.50 EUR", "EUR -12.50", "\u221212.50 EUR", "EUR \u221212.50", "0 EUR", "0.00 EUR"])
def test_a_written_amount_that_is_not_positive_is_invalid(raw: str) -> None:
    assert money.normalize(raw, MONEY, CTX) == Invalid("not_positive")


@given(
    st.sampled_from(_CODES),
    st.integers(min_value=1),
    st.integers(min_value=1),
    st.sampled_from([" - ", "\u2013", " to "]),
)
def test_two_amounts_are_a_range_not_money(code: str, low: int, high: int, separator: str) -> None:
    assert money.normalize(f"{code} {low}{separator}{high}", MONEY, CTX) == Invalid("range")


def test_text_without_an_amount_or_a_currency_is_invalid() -> None:
    assert money.normalize("EUR", MONEY, CTX) == Invalid("no_amount")
    assert money.normalize("12.50", MONEY, CTX) == Invalid("no_currency")


@given(st.text(max_size=8), st.characters(categories=["Cs"]))
def test_input_with_a_lone_surrogate_is_invalid(raw: str, surrogate: str) -> None:
    assert money.normalize(f"EUR 12{raw}{surrogate}", MONEY, CTX) == Invalid("surrogate")


@given(st.one_of(st.none(), st.booleans(), st.integers(), st.floats(), st.lists(st.text(), max_size=2)))
def test_a_json_value_that_is_neither_text_nor_an_object_is_invalid(raw: JsonValue) -> None:
    assert money.normalize(raw, MONEY, CTX) == Invalid("not_money")


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ({"priceCurrency": "EUR"}, "no_amount"),
        ({"price": "12.50"}, "no_currency"),
        ({"price": "12.50", "priceCurrency": "eur"}, "unknown_currency"),
        ({"price": "12.50", "priceCurrency": "XYZ"}, "unknown_currency"),
        ({"price": "€12.50", "priceCurrency": "USD"}, "currency_conflict"),
        ({"price": "12.50 €", "priceCurrency": "USD"}, "currency_conflict"),
        ({"price": "$10 - $20", "priceCurrency": "USD"}, "range"),
        ({"price": "Free", "priceCurrency": "EUR"}, "no_amount"),
        ({"price": True, "priceCurrency": "EUR"}, "unparsable_amount"),
        ({"price": float("nan"), "priceCurrency": "EUR"}, "unparsable_amount"),
        ({"price": "1000000000000", "priceCurrency": "EUR"}, "out_of_range"),
        ({"price": "0.0000001", "priceCurrency": "EUR"}, "out_of_range"),
        ({"price": "1e3", "priceCurrency": "EUR"}, "range"),
    ],
)
def test_a_structured_value_outside_schema_org_price_syntax_is_invalid(raw: JsonValue, reason: str) -> None:
    assert money.normalize(raw, MONEY, CTX) == Invalid(reason)


# CLDR symbols written without digits or number symbols, each with a currency it stands for somewhere.
_SYMBOL_CODES = sorted(
    (symbol, code)
    for symbol, codes in _symbols().items()
    if not any(c.isdigit() or c in ".,'\u2019" or c.isspace() for c in symbol)
    for code in codes
)


@given(st.sampled_from(_SYMBOL_CODES), st.integers(min_value=1, max_value=999), st.booleans())
def test_a_structured_price_written_with_a_sign_of_its_currency_reads_in_that_currency(
    symbol_code: tuple[str, str], amount: int, sign_first: bool
) -> None:
    symbol, code = symbol_code
    written = f"{symbol}{amount}" if sign_first else f"{amount} {symbol}"

    result = money.normalize({"price": written, "priceCurrency": code}, MONEY, CTX)

    assert result == Ok({"amount": str(amount), "currency": code})


@given(st.sampled_from(_SYMBOL_CODES), st.sampled_from(_CODES), st.integers(min_value=1, max_value=999))
def test_a_structured_price_whose_sign_cannot_denote_its_currency_is_invalid(
    symbol_code: tuple[str, str], stated: str, amount: int
) -> None:
    symbol, _ = symbol_code
    assume(stated not in _symbols()[symbol] and symbol != stated)

    result = money.normalize({"price": f"{symbol}{amount}", "priceCurrency": stated}, MONEY, CTX)

    assert isinstance(result, Invalid)


@pytest.mark.parametrize(
    ("price", "tag", "amount"),
    [("$1,295.99", "en-US", "1295.99"), ("1.295,99", "de-DE", "1295.99"), ("1,295.99", "en", "1295.99")],
)
def test_a_structured_price_with_grouping_reads_in_the_page_locale(price: str, tag: str, amount: str) -> None:
    ctx = Context(captured_at=AT, html_lang=tag)

    assert money.normalize({"price": price, "priceCurrency": "USD"}, MONEY, ctx) == Ok(
        {"amount": amount, "currency": "USD"}
    )


def test_a_structured_price_the_locales_read_differently_is_ambiguous() -> None:
    ctx = Context(captured_at=AT, hreflang=("en-US", "de-DE"))

    result = money.normalize({"price": "1.295", "priceCurrency": "EUR"}, MONEY, ctx)

    # `1.295` is schema.org's own syntax (a decimal point), read as written; a grouped form is read in the locales.
    assert result == Ok({"amount": "1.295", "currency": "EUR"})
    assert money.normalize({"price": "€1,295", "priceCurrency": "EUR"}, MONEY, ctx) == Ambiguous(
        "decimal_separator", ({"amount": "1.295", "currency": "EUR"}, {"amount": "1295", "currency": "EUR"})
    )


@given(
    st.sampled_from(sorted(list_currencies())),
    st.decimals(min_value=Decimal("0.000001"), max_value=Decimal("999999999999.999999"), places=6),
)
def test_an_ok_value_normalizes_to_itself_in_both_structured_forms(code: str, amount: Decimal) -> None:
    result = money.normalize({"price": format(amount, "f"), "priceCurrency": code}, MONEY, CTX)

    assert result == Ok({"amount": format(amount, "f"), "currency": code})
    assert money.normalize(result.value, MONEY, CTX) == result


def test_the_dispatcher_sends_money_to_the_money_module() -> None:
    assert normalize("12,50 EUR", MONEY, CTX) == Ok({"amount": "12.50", "currency": "EUR"})


def test_a_spec_of_another_type_is_a_programming_error() -> None:
    spec = FieldSpec(type=FieldType.TEXT)

    with pytest.raises(TypeError):
        money.normalize("EUR 12", spec, CTX)


def test_trailing_zeros_beyond_six_fraction_digits_are_not_precision() -> None:
    raw: JsonValue = {"price": "12.50000000", "priceCurrency": "EUR"}

    assert money.normalize(raw, MONEY, CTX) == Ok({"amount": "12.50000000", "currency": "EUR"})
