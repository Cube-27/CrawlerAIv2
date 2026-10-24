"""The JSON documents a page carries in attributes its framework documents as JSON: only the attributes named below
count, never any attribute whose value happens to start with `{`.

The value, HTML-unescaped by the parser, is a document when it starts with `{` or `[` and is RFC 8259 JSON (the JSON
reader, `core.json_text`); otherwise (Inertia's `<script data-page="app">`, WooCommerce's `false` above its
variation threshold, a broken value) the attribute gives none. Astro island props are revived from their `[type,
value]` tuples (`state_decoders.revive_astro_props`). The JSON state collector (`collect.js_state`) admits the values;
their locators are `attr:<element xpath>@<name>:<path>`.
"""

import re
from collections.abc import Mapping
from typing import Final

from pydantic import JsonValue

from snowcrawl.content.state_decoders import revive_astro_props
from snowcrawl.core.json_text import parse

_ASTRO_PROPS: Final = "props"
# Each documented JSON attribute and the element it is documented on (`*`: any):
# - Inertia.js, The protocol: the page object in `data-page` on the root element (versions before the script form);
# - Livewire, Hydration: a component's snapshot in `wire:snapshot` on its root element;
# - WooCommerce `single-product/add-to-cart/variable.php`: a variable product's variations, `data-product_variations`;
# - Adobe Commerce, JavaScript initialization: an element's components in `data-mage-init`;
# - Astro `serialize.ts`: an island's props in `props` on `astro-island`.
DOCUMENTED: Final[Mapping[str, str]] = {
    "data-page": "*",
    "wire:snapshot": "*",
    "data-product_variations": "*",
    "data-mage-init": "*",
    _ASTRO_PROPS: "astro-island",
}
# The attribute part of an `attr:` locator's address.
NAME_PATTERN: Final = "|".join(re.escape(name) for name in DOCUMENTED)
# CSS Selectors: the documented attributes on their elements, `:` escaped in a name.
SELECTOR: Final = ", ".join(
    f"{'' if tag == '*' else tag}[{name.replace(':', chr(92) + ':')}]" for name, tag in DOCUMENTED.items()
)
# RFC 8259 §2: insignificant whitespace before a JSON text.
_JSON_START = re.compile(r"[ \t\n\r]*[{\[]")


def attribute_document(tag: str, name: str, value: str) -> JsonValue | None:
    """The document of the attribute `name` of a `tag` element, or None (module docstring)."""
    if DOCUMENTED.get(name) not in ("*", tag) or _JSON_START.match(value) is None:
        return None
    try:
        data = parse(value)
    except ValueError:
        return None
    if name == _ASTRO_PROPS:
        revived = revive_astro_props(data)
        return data if revived is None else revived
    return data
