"""Documented JSON attributes and Magento init scripts as source documents,
from the forms each framework documents, and their `attr:` locators read back to their values."""

import json
from html import escape

from pydantic import JsonValue

from crawlerai.collect import json_doc
from crawlerai.collect.js_state import attribute_documents, state_documents
from crawlerai.collect.locator import parse_locator
from crawlerai.config_ir.executor import documents
from crawlerai.content.page import ParsedPage

INERTIA: JsonValue = {
    "component": "Products/Show",
    "props": {"product": {"name": "Desk lamp", "price": "49.00"}},
    "url": "/products/1",
    "version": "c32b8e4965f418ad16eaebba1d4e960f",
}
LIVEWIRE: JsonValue = {
    "data": {"quantity": 1, "price": 12.5},
    "memo": {"id": "Xq1", "name": "cart-line", "path": "products/1", "method": "GET"},
    "checksum": "9f2c",
}
VARIATIONS: JsonValue = [
    {
        "variation_id": 11,
        "attributes": {"attribute_pa_size": "small"},
        "display_price": 18,
        "display_regular_price": 20,
        "is_in_stock": True,
    },
    {
        "variation_id": 12,
        "attributes": {"attribute_pa_size": "large"},
        "display_price": 24,
        "display_regular_price": 24,
        "is_in_stock": False,
    },
]
SP_CONFIG: JsonValue = {
    "spConfig": {
        "optionPrices": {
            "21": {"oldPrice": {"amount": 59}, "basePrice": {"amount": 49}, "finalPrice": {"amount": 49}},
        },
        "prices": {"finalPrice": {"amount": 49}},
    }
}
MAGE_INIT: JsonValue = {"configurable": SP_CONFIG}
X_MAGENTO_INIT: JsonValue = {"#product_addtocart_form": {"configurable": SP_CONFIG}}
# Astro `serializeObject`: every value a `[type, value]` tuple (0 value, 1 array, 3 Date).
ASTRO_PROPS: JsonValue = {
    "product": [0, {"name": [0, "Desk lamp"], "price": [0, 49], "sizes": [1, [[0, "S"], [0, "L"]]]}],
    "released": [3, "2026-01-02T00:00:00.000Z"],
}


def _attr(value: JsonValue) -> str:
    return escape(json.dumps(value), quote=True)


def _page() -> ParsedPage:
    return ParsedPage(
        "<html><head>"
        f'<script type="text/x-magento-init">{json.dumps(X_MAGENTO_INIT)}</script>'
        '<script data-page="app" type="application/json">{"component": "Home"}</script>'
        "</head><body>"
        f'<div id="app" data-page="{_attr(INERTIA)}"></div>'
        f'<div wire:snapshot="{_attr(LIVEWIRE)}" wire:id="Xq1"></div>'
        f'<form class="variations_form" data-product_variations="{_attr(VARIATIONS)}"></form>'
        f'<div class="swatches" data-mage-init="{_attr(MAGE_INIT)}"></div>'
        f'<astro-island uid="1" props="{_attr(ASTRO_PROPS)}"></astro-island>'
        # Not documents: a broken value, WooCommerce above its threshold, an undocumented attribute, `props` off an
        # island.
        '<div data-mage-init="{&quot;configurable&quot;: {"></div>'
        '<form data-product_variations="false"></form>'
        f'<div data-config="{_attr({"price": 1})}" props="{_attr({"price": [0, 1]})}"></div>'
        "</body></html>"
    )


def test_documented_attributes_are_documents() -> None:
    page = _page()
    found = [(d.address, d.data) for d in attribute_documents(page)]
    assert found == [
        ("/html[1]/body[1]/div[1]@data-page", INERTIA),
        ("/html[1]/body[1]/div[2]@wire:snapshot", LIVEWIRE),
        ("/html[1]/body[1]/form[1]@data-product_variations", VARIATIONS),
        ("/html[1]/body[1]/div[3]@data-mage-init", MAGE_INIT),
        (
            "/html[1]/body[1]/astro-island[1]@props",
            {
                "product": {"name": "Desk lamp", "price": 49, "sizes": ["S", "L"]},
                "released": "2026-01-02T00:00:00.000Z",
            },
        ),
    ]
    # The Magento init script is script state; Inertia's script form is a JSON script, its `data-page="app"` nothing.
    scripts = [d.data for d in state_documents(page, []) if d.scheme is None]
    assert scripts == [X_MAGENTO_INIT, {"component": "Home"}]
    assert documents("attr", page) == [data for _, data in found]


def test_locators_read_back_to_their_values() -> None:
    page = _page()
    by_address = {d.address: d.data for d in attribute_documents(page)}
    for document in attribute_documents(page):
        for path, value in json_doc.nodes(document.data):
            locator = parse_locator(document.locator("js_state", path))
            assert locator.scheme == "attr"
            address, query = locator.parts
            assert json_doc.select(query, by_address[address]) == [(path, value)]
