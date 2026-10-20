"""Detect-and-report signals (architecture v3 §(b), "report"): the delivery technologies a page shows that the engine
does not read, each named in the page's diagnostics as `signal:<name>` and counted in the job summary (jobs spec,
"Job outcome summary"). Structural only: an element, an attribute, a script's path, a link, a resource the browser
loaded (`CaptureManifest.resources`), never a URL or page text in what is reported. A signal changes no fetch and no
extraction.

- `websocket`, `eventsource`: the page opened a WebSocket or an EventSource (the browser's resource types).
- `wasm`: an `application/wasm` resource loaded; `grpc_web`: an `application/grpc-web*` body.
- `flutter`: `flt-*` or `flutter-view` elements; `blazor_wasm`: `_framework/blazor.webassembly.js`.
- `live_view`: Phoenix LiveView (`phx-*` attributes) or Blazor Server (`blazor.server.js`): live diffs over a socket.
- `obfuscated_text`: Private Use Area code points in a money candidate's text (font-glyph obfuscation).
- `closed_shadow_root`: a custom element with no light-DOM text and no declarative shadow root, judged on the document
  before its pre-passes (`content.page.prepassed` flattens declarative shadow roots into their hosts).
- `turbo_stream`: turbo-stream chunks (`streamController.enqueue`) in an inline script.
- `gatsby_page_data`: a link to Gatsby's `/page-data/`; `amp_alternate`: a `rel=amphtml` link.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Final, Literal, get_args
from urllib.parse import urlsplit

from selectolax import lexbor

from crawlerai.content.page import ParsedPage
from crawlerai.storage.capture_bundle import GRPC_WEB_TYPE, WASM_TYPE

Signal = Literal[
    "websocket",
    "eventsource",
    "wasm",
    "grpc_web",
    "flutter",
    "blazor_wasm",
    "live_view",
    "obfuscated_text",
    "closed_shadow_root",
    "turbo_stream",
    "gatsby_page_data",
    "amp_alternate",
]
SIGNALS: Final[tuple[Signal, ...]] = get_args(Signal)
# A signal's diagnostic is this prefix and its name.
PREFIX: Final = "signal:"

# Unicode Private Use Areas: the BMP area and planes 15 and 16.
_PUA = re.compile("[\ue000-\uf8ff\U000f0000-\U000ffffd\U00100000-\U0010fffd]")
# HTML Standard, valid custom element names: a hyphen in the name, and not one of the reserved SVG/MathML names.
_CUSTOM_TAG = re.compile(r"<[a-z][a-z0-9]*-", re.IGNORECASE)
_RESERVED = frozenset(
    {
        "annotation-xml",
        "color-profile",
        "font-face",
        "font-face-src",
        "font-face-uri",
        "font-face-format",
        "font-face-name",
        "missing-glyph",
    }
)
_FLUTTER_VIEW, _FLUTTER_PREFIX = "flutter-view", "flt-"
_PHX = re.compile(r"\s(?:data-)?phx-", re.IGNORECASE)
_DSD = re.compile("shadowrootmode", re.IGNORECASE)
_TURBO_STREAM = "streamController.enqueue("
_BLAZOR_SERVER, _BLAZOR_WASM = "blazor.server.js", "_framework/blazor.webassembly.js"


def page_signals(
    page: ParsedPage, resources: Mapping[str, int] | None, money_texts: Iterable[str]
) -> tuple[Signal, ...]:
    """The signals of `page`; `resources` are the browser's counts of the page's resources (None for an HTTP capture)
    and `money_texts` the texts of its money candidates."""
    found: set[Signal] = set(_resource_signals(page, resources or {}))
    if not page.json_body:
        found.update(_document_signals(page, page.source_html))
    if any(_PUA.search(text) for text in money_texts):
        found.add("obfuscated_text")
    return tuple(signal for signal in SIGNALS if signal in found)


def _resource_signals(page: ParsedPage, resources: Mapping[str, int]) -> Iterable[Signal]:
    types = {(entry.content_type or "").split(";", 1)[0].strip().lower() for entry in page.network_entries}
    if resources.get("websocket"):
        yield "websocket"
    if resources.get("eventsource"):
        yield "eventsource"
    if resources.get(WASM_TYPE) or WASM_TYPE in types:
        yield "wasm"
    if resources.get(GRPC_WEB_TYPE) or any(t.startswith(GRPC_WEB_TYPE) for t in types):
        yield "grpc_web"


def _document_signals(page: ParsedPage, source_html: str) -> Iterable[Signal]:
    tree = page.tree
    tags = _custom_tags(tree) if _CUSTOM_TAG.search(page.html) else set()
    if _FLUTTER_VIEW in tags or any(tag.startswith(_FLUTTER_PREFIX) for tag in tags):
        yield "flutter"
    paths = [urlsplit(src).path for src in _script_srcs(tree)]
    if (_PHX.search(page.html) and _has_phx_attribute(tree)) or any(_named(path, _BLAZOR_SERVER) for path in paths):
        yield "live_view"
    if any(_named(path, _BLAZOR_WASM) for path in paths):
        yield "blazor_wasm"
    if any(_TURBO_STREAM in script.text for script in page.scripts):
        yield "turbo_stream"
    if tree.css_first('link[href*="/page-data/"]') is not None:
        yield "gatsby_page_data"
    if tree.css_first('link[rel~="amphtml" i]') is not None:
        yield "amp_alternate"
    if tags and _closed_root_suspected(tree, source_html):
        yield "closed_shadow_root"


def _custom_tags(tree: lexbor.LexborHTMLParser) -> set[str]:
    root = tree.root
    return set() if root is None else {node.tag for node in root.traverse() if node.tag and "-" in node.tag}


def _named(path: str, name: str) -> bool:
    """Whether the URL path `path` ends in the path segments `name`."""
    return path == name or path.endswith("/" + name)


def _script_srcs(tree: lexbor.LexborHTMLParser) -> Iterable[str]:
    return (src for node in tree.css("script[src]") if (src := node.attributes.get("src")))


def _has_phx_attribute(tree: lexbor.LexborHTMLParser) -> bool:
    root = tree.root
    names = (name.lower() for node in ([] if root is None else root.traverse()) for name in node.attributes)
    return any(name.startswith(("phx-", "data-phx-")) for name in names)


def _declares_root(node: lexbor.LexborNode) -> bool:
    return node.tag == "template" and "shadowrootmode" in node.attributes


def _closed_root_suspected(tree: lexbor.LexborHTMLParser, source_html: str) -> bool:
    """A custom element (not Flutter's, which has its own signal) with no text in its light DOM and no declarative
    shadow root. The pre-passes moved each declarative root's content into its host, so a document that had any is
    judged as it arrived, where a template's content is no text of its host's."""
    source = lexbor.LexborHTMLParser(source_html) if _DSD.search(source_html) else tree
    root = source.root
    for node in [] if root is None else root.traverse():
        tag = node.tag or ""
        if "-" not in tag or tag in _RESERVED or tag == _FLUTTER_VIEW or tag.startswith(_FLUTTER_PREFIX):
            continue
        if not node.text(deep=True).strip() and not any(_declares_root(child) for child in node.iter()):
            return True
    return False
