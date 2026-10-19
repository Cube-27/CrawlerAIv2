"""verify-money (`.claude/skills/verify-money/SKILL.md`): generated inputs run on the real money normalizer
(`normalize/money.py`), its number reader (`normalize/numbers.py`) and money grounding (`llm/grounding.py`).

Properties (normalization spec, "money"; llm spec, INV-12; owner decisions 2026-10-18 and 2026-10-19):
1. a grounded amount always publishes: the amount as written, its currency from evidence or `null` (never invented);
2. the raw value grounded for a money claim occurs in the page text, whatever the spacing between sign and digits,
   and never as part of another number or one end of a range;
3. a number written with a CLDR percent sign is never a price;
4. a CLDR compact unit multiplies the amount by its power of ten;
5. an explicit offer or page currency always beats the URL-derived one, and currency fill never changes the amount.

The generators write prices the way a page in the drawn locale does (CLDR number symbols through Babel), with ISO 4217
codes and CLDR symbols only, and synthetic hosts under RFC 2606's `example` label.
"""

import unicodedata
from datetime import UTC, datetime
from decimal import Decimal

from babel import Locale
from babel.core import get_global
from babel.numbers import format_decimal, get_territory_currencies, list_currencies
from hypothesis import assume, given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.llm.grounding import SpanClaim, align
from crawlerai.normalize import money, numbers
from crawlerai.normalize.base import Context, Invalid, NormalizeResult, Ok
from crawlerai.schemas.types import FieldSpec, FieldType

AT = datetime(2026, 1, 1, tzinfo=UTC)
MONEY = FieldSpec(type=FieldType.MONEY)
# Locales whose pages the generators write, as BCP 47 tags (the page's `<html lang>`).
_TAGS = ["en-US", "en-GB", "en-IN", "de-DE", "fr-FR", "fr-CH", "ja-JP", "zh-CN", "ko-KR", "es-ES", "pt-BR", "hi-IN"]
_CODES = sorted(list_currencies())
# CLDR symbols and ISO 4217 codes a page writes beside an amount.
_SIGNS = ["$", "€", "£", "¥", "₹", "R$", "kr", "Rs.", "CHF", "USD", "EUR", "GBP", "JPY", "INR"]
_GAPS = ["", " ", "\u00a0", "\u202f"]
# Two-letter CLDR territories with currency data: what a ccTLD, a country subdomain or a locale segment can name.
_TERRITORIES = sorted(t for t in money._territories() if t.isalpha())

_amounts = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("999999999.99"), places=2)
_tags = st.sampled_from(_TAGS)
_codes = st.sampled_from(_CODES)


def _ctx(**fields: object) -> Context:
    return Context(captured_at=AT, **fields)  # type: ignore[arg-type]


def _written(amount: Decimal, tag: str) -> str:
    """`amount` as a page in locale `tag` writes it (CLDR decimal and group symbols, grouping sizes)."""
    return format_decimal(amount, locale=tag.replace("-", "_"), decimal_quantization=False)


def _amount(result: NormalizeResult) -> Decimal:
    assert isinstance(result, Ok), result
    value = result.value
    assert isinstance(value, dict)
    return Decimal(str(value["amount"]))


def _currency(result: NormalizeResult) -> str | None:
    assert isinstance(result, Ok), result
    assert isinstance(result.value, dict)
    currency = result.value["currency"]
    assert currency is None or isinstance(currency, str)
    return currency


@st.composite
def _urls(draw: st.DrawFn) -> tuple[str, str]:
    """A synthetic URL naming one territory (locale path segment, country subdomain or ccTLD), and that territory."""
    territory = draw(st.sampled_from(_TERRITORIES))
    label = territory.lower()
    languages = sorted(get_global("territory_languages").get(territory, {}))
    forms = [f"https://shop.example.{label}/p", f"https://{label}.example.com/p"]
    forms += [f"https://shop.example.com/{lang}-{label}/p" for lang in languages if 2 <= len(lang) <= 3]
    return draw(st.sampled_from(forms)), territory


def _tender(territory: str) -> str | None:
    """The territory's one tender currency on the capture date (CLDR), the currency its URL names."""
    current = get_territory_currencies(territory, AT.date(), tender=True)
    return current[0] if len(current) == 1 else None


@st.composite
def _evidence(draw: st.DrawFn) -> Context:
    """A page's currency evidence, any of it: structured and declared currencies, and a URL naming a territory."""
    page = tuple(draw(st.lists(_codes, max_size=2)))
    declared = tuple(draw(st.lists(_codes, max_size=2)))
    url = draw(st.one_of(st.none(), _urls().map(lambda u: u[0])))
    return _ctx(html_lang=draw(_tags), page_currencies=page, declared_currencies=declared, page_url=url)


@given(_amounts, _evidence(), st.sampled_from(["", *_SIGNS]), st.sampled_from(_GAPS), st.booleans())
def test_a_grounded_amount_always_publishes_with_a_currency_from_evidence_or_none(
    amount: Decimal, ctx: Context, sign: str, gap: str, before: bool
) -> None:
    assert ctx.html_lang is not None
    written = _written(amount, ctx.html_lang)
    raw = (f"{sign}{gap}{written}" if before else f"{written}{gap}{sign}") if sign else written

    result = money.normalize(raw, MONEY, ctx)

    # Never skipped (owner 2026-10-18): the amount publishes as written, whatever its currency.
    assert _amount(result) == amount
    currency = _currency(result)
    assert isinstance(result, Ok)
    assert (currency is None) == (result.basis == "unknown")
    # Never invented (C7): the sign's own code, else one the sign, the page or its URL names.
    if money.is_currency_code(sign):
        assert currency == sign
    elif currency is not None:
        named = {*ctx.page_currencies, *ctx.declared_currencies, money.url_currency(ctx)}
        assert currency in named | money._currencies_for(sign)
    # The structured form publishes too, a `priceCurrency` ISO 4217 does not list stating none.
    code = sign if money.is_currency_code(sign) else sign.lower() or None
    for price in (format(amount, "f"), float(amount)):
        structured = money.normalize({"price": price, "priceCurrency": code}, MONEY, ctx)
        assert _amount(structured) == amount
        if money.is_currency_code(sign):
            assert _currency(structured) == sign


@st.composite
def _spaced_claims(draw: st.DrawFn) -> tuple[str, str, Decimal]:
    """A page text writing one price, a model's claim of it spaced differently between sign and digits, the amount."""
    amount = draw(_amounts)
    written, sign = _written(amount, "en-US"), draw(st.sampled_from(_SIGNS))
    gaps = st.sampled_from([*_GAPS, "  ", "\n"])
    page_gap = draw(gaps)
    claim_gap = draw(gaps.filter(lambda g: g != page_gap))
    before = draw(st.booleans())
    display, claim = (
        (f"{sign}{page_gap}{written}", f"{sign}{claim_gap}{written}")
        if before
        else (f"{written}{page_gap}{sign}", f"{written}{claim_gap}{sign}")
    )
    filler = st.text(st.sampled_from("abcdefgh "), max_size=30)
    return f"{draw(filler)}\n{display}\n{draw(filler)}", claim, amount


@given(_spaced_claims())
def test_a_grounded_money_value_is_a_span_of_the_page_text_with_the_claimed_amount(
    case: tuple[str, str, Decimal],
) -> None:
    text, claim, amount = case

    grounded = align(SpanClaim(value=claim, start=0, end=len(claim)), text, money=True)

    assert grounded is not None
    assert text[grounded.start : grounded.end] == grounded.value
    us = _ctx(html_lang="en-US")
    assert _amount(money.normalize(grounded.value, MONEY, us)) == _amount(money.normalize(claim, MONEY, us)) == amount


@st.composite
def _ungroundable(draw: st.DrawFn) -> tuple[str, str]:
    """A page text and a money claim it does not write on its own: an amount the text lacks, one end of a range, or
    the tail of a grouped number; each claim spaced unlike the text."""
    a, b = draw(_amounts), draw(_amounts)
    wa, wb, sign = _written(a, "en-US"), _written(b, "en-US"), draw(st.sampled_from(_SIGNS))
    gap = draw(st.sampled_from(_GAPS))
    other = draw(st.sampled_from(_GAPS).filter(lambda g: g != gap))
    dash = draw(st.sampled_from(["-", "\u2013", "\u2014", "~"]))
    kind = draw(st.sampled_from(["absent", "range", "grouped"]))
    if kind == "absent":
        assume(wb not in f"{sign}{gap}{wa}")
        return f"Price {sign}{gap}{wa}", f"{sign}{other}{wb}"
    if kind == "range":
        text = f"{sign}{gap}{wa} {dash} {sign}{gap}{wb}"
        claimed, rest = draw(st.sampled_from([(wa, wb), (wb, wa)]))
        # Known finding KF-2 (SKILL.md): a claim whose digits open a grouped amount (`$ 4` in `$4,000`) grounds at
        # its head; not generated.
        assume(not rest.startswith((f"{claimed},", f"{claimed}.")))
        return text, f"{sign}{other}{claimed}"
    assume("," not in wa)
    return f"1 {wa}{gap}{sign}", f"{wa}{other}{sign}"


@given(_ungroundable())
def test_a_money_claim_the_text_does_not_write_alone_is_not_grounded(case: tuple[str, str]) -> None:
    text, claim = case

    assert align(SpanClaim(value=claim, start=0, end=len(claim)), text, money=True) is None


_PERCENT_SIGNS = numbers._percent_signs()


@st.composite
def _percentages(draw: st.DrawFn) -> str:
    """A ratio as CLDR locales write it: a percent sign after (white space or a bidi mark between) or before it."""
    value = str(draw(st.decimals(min_value=1, max_value=99, places=draw(st.integers(0, 1)))))
    sign = draw(st.sampled_from(_PERCENT_SIGNS))
    minus = draw(st.sampled_from(["", "-", "\u2212"]))
    if draw(st.booleans()):
        return f"{minus}{sign}{value}"  # CLDR writes the minus before a leading percent sign (`-%20`)
    return f"{minus}{value}{draw(st.sampled_from(['', ' ', '\u200e', '\u200f', ' \u061c']))}{sign}"


@given(_percentages(), _amounts, st.sampled_from(["USD", "EUR", "€", "£"]), st.integers(0, 2))
def test_a_percentage_is_never_a_price(ratio: str, amount: Decimal, sign: str, where: int) -> None:
    us = _ctx(html_lang="en-US")
    price = f"{sign} {_written(amount, 'en-US')}"

    assert money.normalize(ratio, MONEY, us) == Invalid("no_amount")
    assert money.normalize({"price": ratio, "priceCurrency": "EUR"}, MONEY, us) == Invalid("no_amount")
    # A discount written beside the price is not a second amount. Known finding KF-1 (SKILL.md): white space alone
    # between the price and a ratio not opened by a minus (`12.99 20%`, `12.99 %20`) drops the price; not generated.
    text = [f"{price} ({ratio})", f"{ratio} {price}", f"{price} {ratio}"][where]
    assume(where != 2 or ratio[0] in "-\u2212")
    assert _amount(money.normalize(text, MONEY, us)) == amount


def _units(tag: str) -> dict[str, int]:
    """The locale's CLDR compact units (`decimalFormats-short`) that stand for one power of ten."""
    powers: dict[str, set[int]] = {}
    for unit, power in numbers._compact_units(str(Locale.parse(tag, sep="-"))):
        powers.setdefault(unit, set()).add(power)
    return {unit: p.pop() for unit, p in powers.items() if len(p) == 1}


@st.composite
def _compact(draw: st.DrawFn) -> tuple[str, str, int, Decimal]:
    tag = draw(st.sampled_from(["en-US", "en-IN", "de-DE", "fr-FR", "es-ES", "ja-JP", "zh-CN", "ko-KR", "hi-IN"]))
    unit, power = draw(st.sampled_from(sorted(_units(tag).items())))
    amount = draw(st.decimals(min_value=Decimal("0.1"), max_value=Decimal("999.9"), places=1))
    return tag, unit, power, amount


@given(_compact(), st.sampled_from(["USD ", "EUR ", "€", ""]))
def test_a_cldr_compact_unit_multiplies_the_amount(case: tuple[str, str, int, Decimal], sign: str) -> None:
    tag, unit, power, amount = case
    ctx = _ctx(html_lang=tag)

    result = money.normalize(f"{sign}{_written(amount, tag)}{unit}", MONEY, ctx)

    total = amount.scaleb(power)
    if total >= Decimal(10) ** 12:
        assert result == Invalid("out_of_range")
    else:
        assert _amount(result) == total
    # A unit that starts a word (`12 Kg`) is no unit: the amount stays as written.
    shorter = any(unit != other and unit.startswith(other) for other in _units(tag))
    if unicodedata.name(unit.strip()[-1]).startswith("LATIN") and not shorter:
        assert _amount(money.normalize(f"{sign}{_written(amount, tag)}{unit}g", MONEY, ctx)) == amount


@given(_amounts, _urls(), _codes, st.booleans())
def test_an_explicit_currency_beats_the_url_one_and_currency_fill_never_changes_the_amount(
    amount: Decimal, url: tuple[str, str], code: str, final: bool
) -> None:
    address, territory = url
    where = {"page_url": address} if final else {"request_url": address}
    price = format(amount, "f")
    expected = _tender(territory)

    # The URL fills a currency the page does not state: its territory's one tender currency, flagged `url`.
    raws: tuple[JsonValue, ...] = (price, {"price": price})
    for raw in raws:
        filled = money.normalize(raw, MONEY, _ctx(**where))
        assert isinstance(filled, Ok)
        assert (_currency(filled), filled.basis) == (expected, "url" if expected else "unknown")
        assert _amount(filled) == _amount(money.normalize(raw, MONEY, _ctx())) == amount
    # An offer's own currency, or one the page states page-wide, always wins.
    offer = money.normalize({"price": price, "priceCurrency": code}, MONEY, _ctx(**where))
    assert (_currency(offer), _amount(offer)) == (code, amount)
    for stated in ({"page_currencies": (code,)}, {"declared_currencies": (code,)}):
        page = money.normalize(price, MONEY, _ctx(**where, **stated))
        assert (_currency(page), _amount(page)) == (code, amount)
    # A sign naming one currency is explicit too.
    signed = money.normalize(f"{code} {price}", MONEY, _ctx(**where))
    assert (_currency(signed), _amount(signed)) == (code, amount)
