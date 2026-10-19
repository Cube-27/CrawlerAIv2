"""One parsed page per capture (INV-26; extraction spec).

The body is decoded once and parsed at most once per parser: selectolax on first use, lxml only when an XPath step or
trafilatura asks for it. The script blocks, the cleaned text and the visibility index are derived once from the
selectolax tree; the captured network bodies are kept as the bundle holds them. Every consumer (collectors, content
formats, pagination, the engine executor) takes a `ParsedPage`, never the raw body.
"""

import itertools
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property

from lxml import html as lxml_html
from selectolax import lexbor

from crawlerai.acquire.items import Group, item_groups, lxml_root
from crawlerai.content.segment import rank
from crawlerai.content.text import CleanedText, VisibleIndex, render, xpath_step
from crawlerai.storage.capture_bundle import CaptureBundle, NetworkBody, decode_body


@dataclass(frozen=True)
class ScriptBlock:
    """An inline `<script>`: its type's MIME essence (`""` when absent), its raw text, and its XPath 1.0 path in the
    selectolax tree (not guaranteed to resolve in `lxml_tree`: libxml2 builds HTML trees differently)."""

    type: str
    text: str
    xpath: str


class ParsedPage:
    def __init__(
        self,
        html: str,
        network: tuple[bytes, ...] = (),
        network_entries: tuple[NetworkBody, ...] = (),
        *,
        json_body: bool = False,
        item_areas: Mapping[str, float] | None = None,
    ) -> None:
        self.html = html
        # The rendered area of the page's item blocks, when a browser capture measured them (`CaptureManifest`).
        self.item_areas = item_areas
        # Whether the body is a JSON document, not HTML: an `api` capture's is (`body.json`, persistence-storage spec).
        # Its text is still parsed as HTML for the readers of text, but it holds no HTML elements of its own
        # (`content.links`).
        self.json_body = json_body
        # The bundle's captured network bodies, in capture order (the `xhr:<n>` locator indexes them), and their
        # manifest entries (the request each answered), when the caller has them.
        self.network = network
        self.network_entries = network_entries
        # What a later layer derives from this parse, by the deriving class, so a page read twice for the same work is
        # read once (INV-26): the extraction pipeline's collection, which the render check reads before extraction.
        # Each is kept with the inputs it was derived from, compared by identity.
        self.derived: dict[type, tuple[tuple[object, ...], object]] = {}

    @classmethod
    def of(cls, bundle: CaptureBundle) -> "ParsedPage":
        manifest = bundle.manifest
        return cls(
            decode_body(bundle),
            bundle.network,
            manifest.network_bodies,
            json_body=manifest.method == "api",
            item_areas=manifest.item_areas,
        )

    @cached_property
    def tree(self) -> lexbor.LexborHTMLParser:
        return lexbor.LexborHTMLParser(self.html)

    @cached_property
    def lxml_tree(self) -> lxml_html.HtmlElement:
        return lxml_root(self.html)

    @cached_property
    def scripts(self) -> tuple[ScriptBlock, ...]:
        # HTML Standard, the script element: a script with `src` runs the external resource, not its text. The type
        # attribute is a MIME type, compared by its essence (WHATWG MIME Sniffing: lower-cased, parameters dropped).
        blocks: list[ScriptBlock] = []
        for node in self.tree.css("script"):
            attributes = node.attributes
            if "src" not in attributes:
                media_type = (attributes.get("type") or "").split(";", 1)[0].strip().lower()
                blocks.append(ScriptBlock(type=media_type, text=node.text(deep=True), xpath=node_xpath(node)))
        return tuple(blocks)

    @cached_property
    def item_groups(self) -> tuple[Group, ...]:
        """The page's groups of repeated item blocks, best first (the item layer's segment step, `content.segment`)."""
        return rank(item_groups(self.lxml_tree), self.item_areas)

    @cached_property
    def text_spans(self) -> dict[str, tuple[int, int]]:
        """Each element's span of the cleaned text, from its first text run to its last, by its node path in the
        selectolax tree (`content.text.TextRun`); an element that renders no text has none."""
        spans: dict[str, tuple[int, int]] = {}
        for run in self.cleaned_text.offsets:
            path = run.node_path
            while path:
                start, end = spans.get(path, (run.start, run.end))
                spans[path] = (min(start, run.start), max(end, run.end))
                path = path.rpartition("/")[0]
        return spans

    @cached_property
    def own_runs(self) -> dict[str, tuple[tuple[int, int], ...]]:
        """The spans of the cleaned text each element's own text nodes render (not its children's), by node path."""
        runs: dict[str, list[tuple[int, int]]] = {}
        for run in self.cleaned_text.offsets:
            runs.setdefault(run.node_path, []).append((run.start, run.end))
        return {path: tuple(spans) for path, spans in runs.items()}

    @cached_property
    def digit_joins(self) -> tuple[int, ...]:
        """The offsets of the cleaned text where two text nodes meet with a digit on each side and nothing between
        them: adjacent inline elements (`<span>$12</span><span>20</span>`) render as one run of digits that is two
        numbers, a token boundary the text does not show."""
        text, runs = self.cleaned_text.text, self.cleaned_text.offsets
        return tuple(
            right.start
            for left, right in itertools.pairwise(runs)
            if left.end == right.start and text[left.end - 1 : left.end].isdigit() and text[right.start].isdigit()
        )

    @property
    def cleaned_text(self) -> CleanedText:
        return self._rendered[0]

    @cached_property
    def visible_values(self) -> VisibleIndex:
        return VisibleIndex(*self._rendered)

    @cached_property
    def _rendered(self) -> tuple[CleanedText, tuple[str, ...]]:
        root = self.tree.root
        if root is None:
            raise RuntimeError("the HTML parser creates an `html` element in every document")
        return render(root)


def node_xpath(node: lexbor.LexborNode) -> str:
    """The XPath 1.0 path of an element in the selectolax tree, one positional step per ancestor."""
    steps: list[str] = []
    current: lexbor.LexborNode | None = node
    while current is not None and current.is_element_node:
        index, sibling = 1, current.prev
        while sibling is not None:
            index += sibling.is_element_node and sibling.tag == current.tag
            sibling = sibling.prev
        steps.append(xpath_step(current.tag or "", index))
        current = current.parent
    return "/" + "/".join(reversed(steps))
