"""The `html` content format (SPEC-07 §4.5, ARCHITECTURE §8.5): the page without what runs script, else intact.

No readability cleaning (that is `markdown`) and no per-site rules (C2). The format works on a copy of the page's
selectolax tree, so the shared `ParsedPage` stays as parsed (INV-26).
"""

from selectolax import lexbor

from crawlerai.content.page import ParsedPage

# HTML Living Standard: `script` runs code (§4.12.1), `style` holds CSS (§4.2.6), `noscript` content is parsed as
# markup only when scripting is off (§4.12.2), and `template` content is inert markup meant for script (§4.12.3).
_REMOVED = "script, style, noscript, template"

# WHATWG URL Standard, basic URL parser: leading C0 controls and spaces are stripped and every ASCII tab and newline
# is removed before the scheme is read, so `java<TAB>script:` is a `javascript:` URL in a browser.
_URL_IGNORED = str.maketrans("", "", "\t\n\r")
_C0_OR_SPACE = "".join(map(chr, range(0x21)))


def is_javascript_url(value: str) -> bool:
    """Whether `value` parses as a `javascript:` URL (HTML §7.11.1); the scheme is ASCII case-insensitive."""
    # A `javascript:` URL has a colon; most attribute values (classes, styles, text) don't, and skip the copies.
    return ":" in value and value.translate(_URL_IGNORED).lstrip(_C0_OR_SPACE).lower().startswith("javascript:")


def remove_scripting_attributes(tree: lexbor.LexborHTMLParser) -> None:
    """Remove from the document every event handler content attribute (HTML §8.1.8.2: the `on*`
    names) and every attribute whose value is a `javascript:` URL, whatever the attribute's name."""
    for node in tree.root.traverse() if tree.root is not None else ():
        for name, value in node.attributes.items():
            if name.lower().startswith("on") or is_javascript_url(value or ""):
                del node.attrs[name]


def cleaned_html(page: ParsedPage) -> str:
    """The page with `script`, `style`, `noscript` and `template` elements, event handler attributes and
    `javascript:` URLs removed; everything else is kept. A JSON body (`ParsedPage.json_body`) is no HTML document, so
    it has none: `""` (D-1474); `raw_html` still holds it as received."""
    if page.json_body:
        return ""
    tree = page.tree.clone()
    for node in tree.css(_REMOVED):
        node.decompose()
    remove_scripting_attributes(tree)
    return tree.html or ""
