"""The currencies a page's structured data states (SPEC-04 §4.4, ARCHITECTURE §9): the ISO 4217 codes written as
schema.org `priceCurrency` (on an Offer, AggregateOffer, PriceSpecification or any other node, in JSON-LD, microdata
or RDFa Lite) and as the OGP `product:price:currency`. They settle a currency symbol the page writes in text (`$` on a
page whose Offer says USD) and nothing else: a page currency never supplies a missing sign (D-0301).

Only what the page states is read (C7): a value that is not an ISO 4217 code as written (three uppercase letters
that ISO 4217 lists) is not a currency here, and nothing is inferred from the host, the language or other prices.
"""

from crawlerai.collect import jsonld, microdata, og
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context
from crawlerai.normalize.money import is_currency_code

# schema.org `priceCurrency`: "The currency of the price … Use standard formats: ISO 4217 currency format".
_PROPERTY = "priceCurrency"


def stated_currencies(page: ParsedPage) -> tuple[str, ...]:
    """The ISO 4217 codes the page states, each once, in the order first written (JSON-LD, microdata, then OGP)."""
    written = [
        *jsonld.property_scalars(page, _PROPERTY),
        *microdata.property_scalars(page, _PROPERTY),
        *og.price_currencies(page),
    ]
    found = (value.strip() for value in written if isinstance(value, str))
    return tuple(dict.fromkeys(code for code in found if is_currency_code(code)))


def with_stated_currencies(ctx: Context, page: ParsedPage) -> Context:
    """`ctx` with `page_currencies` set to what `page` states."""
    return ctx.model_copy(update={"page_currencies": stated_currencies(page)})
