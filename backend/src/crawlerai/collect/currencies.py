"""The currencies, the language and the number convention a page states for its prices (normalization spec, "money"),
as evidence the normalizers weigh.

- Stated in structured data: the ISO 4217 codes written as schema.org `priceCurrency` (on an Offer, AggregateOffer,
  PriceSpecification or any other node, in JSON-LD, microdata or RDFa Lite).
- Declared page-wide: the OGP `product:price:currency` and `og:price:currency`, and a currency in the page's state
  JSON, a member named `currency`, `currencyCode` or `activeCurrency` (letter case and `_` aside) holding an ISO 4217
  code (owner decision of 2026-10-18: generic member names only); on a page showing a platform's signal, the script
  global its documentation names for the shop's currency (`adapters.platforms.CurrencyMember`: Shopify's
  `Shopify.currency.active`, Shopware's `window.currencyIsoCode`).
- The page's number convention: the CLDR decimal symbol every structured `price` the page writes with a fraction uses
  when only one CLDR convention reads it (`12.50`, `1.234,56`), which settles amounts the conventions read differently
  (`numbers.readings`).

Only what the page writes is read (C7): a value that is not an ISO 4217 code as written (three uppercase letters that
ISO 4217 lists) is not a currency here. The language is the schema.org `inLanguage` the page writes, which the number
rules read beside `<html lang>` (`numbers.locale_set`); the ccTLD is weighed by the money rules themselves.
"""

import re
from collections.abc import Iterator

from pydantic import JsonValue

from crawlerai.adapters.platforms import CurrencyMember, signature_of
from crawlerai.collect import jsonld, microdata, og
from crawlerai.collect.js_state import state_documents
from crawlerai.content.page import ParsedPage
from crawlerai.core.json_text import parse_prefix
from crawlerai.normalize import numbers
from crawlerai.normalize.base import Context
from crawlerai.normalize.money import is_currency_code

# schema.org `priceCurrency`: "The currency of the price … Use standard formats: ISO 4217 currency format".
_PROPERTY = "priceCurrency"
# schema.org `inLanguage`: "The language of the content or performance ... Please use one of the language codes from
# the IETF BCP 47 standard."
_LANGUAGE = "inLanguage"
# Owner decision 2026-10-18: the member names of a page-wide currency in state JSON, compared without letter case or
# `_` (`currency_code`, `CurrencyCode`).
_STATE_MEMBERS = frozenset({"currency", "currencycode", "activecurrency"})
# schema.org `price`, the amount whose written form shows the page's decimal symbol.
_PRICE = "price"
# ECMAScript: a string literal in single or double quotes without escapes (a template's `'{{ isoCode }}'`).
_QUOTED = re.compile(r"""\s*(['"])([^'"\\\n]*)\1""")


def stated_currencies(page: ParsedPage) -> tuple[str, ...]:
    """The ISO 4217 codes the page's structured data states, each once, in the order first written (JSON-LD, then
    microdata)."""
    return _codes([*jsonld.property_scalars(page, _PROPERTY), *microdata.property_scalars(page, _PROPERTY)])


def declared_currencies(page: ParsedPage) -> tuple[str, ...]:
    """The ISO 4217 codes the page declares page-wide, each once: OGP's, then its state JSON's."""
    state = [value for document in state_documents(page, []) for value in _state_currencies(document.data)]
    return _codes([*og.price_currencies(page), *state, *_platform_currencies(page)])


def page_convention(page: ParsedPage) -> str | None:
    """The CLDR decimal symbol of the page's structured prices (module docstring), or None when they write none or
    disagree."""
    written = [*jsonld.property_scalars(page, _PRICE), *microdata.property_scalars(page, _PRICE)]
    symbols = {symbol for value in written if (symbol := _decimal_symbol(value)) is not None}
    return symbols.pop() if len(symbols) == 1 else None


def _decimal_symbol(value: JsonValue) -> str | None:
    """The decimal symbol a price is written with: `.` for a JSON number with a fraction (RFC 8259 §6, a float); for
    text, the separator before the fraction of its one amount, when every CLDR convention reads it as one value."""
    if isinstance(value, float):
        return "."
    if not isinstance(value, str):
        return None
    found = numbers.stated(value)
    if isinstance(found, str):
        return None
    read = numbers.readings(found.written, frozenset())
    exponent = read[0].as_tuple().exponent if len(read) == 1 else 0
    if not isinstance(exponent, int) or exponent >= 0:
        return None
    return found.written[exponent - 1]


def _platform_currencies(page: ParsedPage) -> Iterator[str]:
    """The values of the currency globals of the platform whose signal the page shows (`CurrencyMember`)."""
    signature = signature_of(page.html, ())
    for member in () if signature is None else signature.currency_members:
        for script in page.scripts:
            yield from _assigned(script.text, member)


def _assigned(text: str, member: CurrencyMember) -> Iterator[str]:
    """The strings the script `text` assigns to `member.assigned` (followed through `member.members`)."""
    for match in re.finditer(rf"(?<![\w$.]){re.escape(member.assigned)}\s*=(?![=>])", text):
        if quoted := _QUOTED.match(text, match.end()):
            value: JsonValue = quoted.group(2)
        else:
            try:
                value, _ = parse_prefix(text, match.end())
            except ValueError:
                continue
        for name in member.members:
            value = value.get(name) if isinstance(value, dict) else None
        if isinstance(value, str):
            yield value


def stated_languages(page: ParsedPage) -> tuple[str, ...]:
    """The language tags the page's JSON-LD writes as schema.org `inLanguage`, each once, as written; microdata and
    RDFa Lite are read by the same property."""
    written = [*jsonld.property_scalars(page, _LANGUAGE), *microdata.property_scalars(page, _LANGUAGE)]
    return tuple(dict.fromkeys(value.strip() for value in written if isinstance(value, str) and value.strip()))


def with_page_declarations(ctx: Context, page: ParsedPage) -> Context:
    """`ctx` with what `page` states about money and language: the currencies it states (`page_currencies`) and
    declares (`declared_currencies`), its `inLanguage` (`in_language`) and its decimal symbol (`page_convention`)."""
    return ctx.model_copy(
        update={
            "page_currencies": stated_currencies(page),
            "declared_currencies": declared_currencies(page),
            "in_language": stated_languages(page),
            "page_convention": page_convention(page),
        }
    )


def _codes(written: list[JsonValue]) -> tuple[str, ...]:
    found = (value.strip() for value in written if isinstance(value, str))
    return tuple(dict.fromkeys(code for code in found if is_currency_code(code)))


def _state_currencies(document: JsonValue) -> Iterator[JsonValue]:
    """The values of the currency members anywhere in a state document (RFC 8259 objects and arrays)."""
    stack = [document]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for name, member in node.items():
                if name.replace("_", "").lower() in _STATE_MEMBERS and isinstance(member, str):
                    yield member
                elif isinstance(member, (dict, list)):
                    stack.append(member)
        elif isinstance(node, list):
            stack.extend(node)
