"""The currencies and the language a page states for its prices (normalization spec, "money"), as evidence the
normalizers weigh.

- Stated in structured data: the ISO 4217 codes written as schema.org `priceCurrency` (on an Offer, AggregateOffer,
  PriceSpecification or any other node, in JSON-LD, microdata or RDFa Lite).
- Declared page-wide: the OGP `product:price:currency` and `og:price:currency`, and a currency in the page's state
  JSON, a member named `currency`, `currencyCode` or `activeCurrency` (letter case and `_` aside) holding an ISO 4217
  code (owner decision of 2026-10-18: generic member names only).

Only what the page writes is read (C7): a value that is not an ISO 4217 code as written (three uppercase letters that
ISO 4217 lists) is not a currency here. The language is the schema.org `inLanguage` the page writes, which the number
rules read beside `<html lang>` (`numbers.locale_set`); the ccTLD is weighed by the money rules themselves.
"""

from collections.abc import Iterator

from pydantic import JsonValue

from crawlerai.collect import jsonld, microdata, og
from crawlerai.collect.js_state import state_documents
from crawlerai.content.page import ParsedPage
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


def stated_currencies(page: ParsedPage) -> tuple[str, ...]:
    """The ISO 4217 codes the page's structured data states, each once, in the order first written (JSON-LD, then
    microdata)."""
    return _codes([*jsonld.property_scalars(page, _PROPERTY), *microdata.property_scalars(page, _PROPERTY)])


def declared_currencies(page: ParsedPage) -> tuple[str, ...]:
    """The ISO 4217 codes the page declares page-wide, each once: OGP's, then its state JSON's."""
    state = [value for document in state_documents(page, []) for value in _state_currencies(document.data)]
    return _codes([*og.price_currencies(page), *state])


def stated_languages(page: ParsedPage) -> tuple[str, ...]:
    """The language tags the page's JSON-LD writes as schema.org `inLanguage`, each once, as written; microdata and
    RDFa Lite are read by the same property."""
    written = [*jsonld.property_scalars(page, _LANGUAGE), *microdata.property_scalars(page, _LANGUAGE)]
    return tuple(dict.fromkeys(value.strip() for value in written if isinstance(value, str) and value.strip()))


def with_page_declarations(ctx: Context, page: ParsedPage) -> Context:
    """`ctx` with what `page` states about money and language: the currencies it states (`page_currencies`) and
    declares (`declared_currencies`), and its `inLanguage` (`in_language`)."""
    return ctx.model_copy(
        update={
            "page_currencies": stated_currencies(page),
            "declared_currencies": declared_currencies(page),
            "in_language": stated_languages(page),
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
