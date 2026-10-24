"""What role A reads of a sample page: the page's HTML reduced
to its elements, their text and a few attributes, cut around the published values, and its JSON documents as key
paths without their values.

The reduced HTML keeps every element other than `script` and `style`, so the paths the model writes are paths of the
page the executors run on. Only the attributes selectors anchor on or read values from are kept.
"""

import copy
import html
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from lxml import etree
from lxml import html as lxml_html
from pydantic import JsonValue

from snowcrawl.collect import js_state, jsonld, xhr
from snowcrawl.collect.json_doc import is_scalar, nodes
from snowcrawl.content.page import ParsedPage

# The attributes the model sees, besides every `data-*` one (HTML Standard §3.2.6.6, custom data
# attributes). `id`, `class`, `itemprop` and `data-*` are the anchors induction also uses; `href`, `src`,
# `content`, `name` and `property` carry values (links, images, meta elements).
KEPT_ATTRIBUTES: Final = frozenset({"id", "class", "itemprop", "href", "src", "content", "name", "property"})
# HTML Standard §4.12.1, §4.2.6: a script's and a style's contents are not rendered text. Script JSON is shown as key
# paths instead (`json_keys`).
DROPPED_ELEMENTS: Final = ("script", "style")
# The key paths of a page's JSON documents are cut to this many characters; the HTML has its own limit.
KEYS_MAX_CHARS: Final = 20_000
# JSON-LD 1.1 §3.5: `@type` names the node's types, which a `jsonld` step's `when_type` matches, so its values are
# shown; no other value is.
_TYPE_KEY: Final = "['@type']"


@dataclass(frozen=True, slots=True)
class Cut:
    """A text as the model reads it, and the diagnostic that records a cut."""

    text: str
    note: str | None = None


def reduced_html(page: ParsedPage) -> str:
    """The page's lxml tree without scripts, styles and comments, with only the kept attributes, serialized."""
    tree = copy.deepcopy(page.lxml_tree)  # the parsed page is shared, so it is never changed
    etree.strip_elements(tree, etree.Comment, *DROPPED_ELEMENTS, with_tail=False)
    for element in tree.iter():
        for name in [name for name in element.attrib if not _kept(name)]:
            del element.attrib[name]
    return lxml_html.tostring(tree, encoding="unicode")


def _kept(name: str) -> bool:
    return name in KEPT_ATTRIBUTES or name.startswith("data-")


def cut_around(text: str, values: Iterable[str], limit: int) -> Cut:
    """`text` cut to `limit` characters: a window over the first and last of `values` found in it (as HTML text, with
    `&`, `<` and `>` escaped), centred as far as the text allows; the start when none is found."""
    if len(text) <= limit:
        return Cut(text)
    escaped = dict.fromkeys(html.escape(v, quote=False) for v in values)  # a listing repeats many values
    found = [(i, i + len(v)) for v in escaped if v and (i := text.find(v)) >= 0]
    start = 0
    if found:
        first, last = min(s for s, _ in found), max(e for _, e in found)
        start = max(0, min(first - max(0, limit - (last - first)) // 2, len(text) - limit))
    return Cut(text[start : start + limit], f"characters {start} to {start + limit} of {len(text)}")


def json_keys(page: ParsedPage, limit: int) -> Cut:
    """One line per JSON document of the page (JSON-LD blocks, script state, JSON attributes, captured responses)
    with its key paths, array indices as `[*]` (RFC 9535 §2.5.1.2), cut to `limit` characters (at most
    `KEYS_MAX_CHARS`)."""
    limit = min(limit, KEYS_MAX_CHARS)
    documents = [
        *((f"jsonld block {index}", data) for index, data in jsonld.blocks(page, [])),
        *((f"js_state {document.address}", document.data) for document in js_state.script_documents(page, [])),
        *((f"attr {document.address}", document.data) for document in js_state.attribute_documents(page)),
        *((f"xhr {document.address}", document.data) for document in xhr.network_documents(page, [])),
    ]
    text = "\n".join(f"{name}: {' '.join(_key_paths(data))}" for name, data in documents)
    if len(text) <= limit:
        return Cut(text)
    return Cut(text[:limit], f"the first {limit} of {len(text)} characters of JSON keys")


def _key_paths(document: JsonValue) -> Iterable[str]:
    nodes_ = nodes(document, wildcard=True)
    return dict.fromkeys(f"{path}={value}" if _is_type(path) else path for path, value in nodes_ if is_scalar(value))


def _is_type(path: str) -> bool:
    return path.endswith((_TYPE_KEY, f"{_TYPE_KEY}[*]"))
