"""One parsed page per capture (INV-26; extraction spec).

The body is decoded once and parsed once, by selectolax (lexbor, the HTML Standard's parsing algorithm) on first use;
the lxml tree an XPath step or the Markdown writer reads is a copy of that parse (`acquire.items.lxml_of`), so an
element has one path in both. The script blocks, their JSON-LD documents, the cleaned text and the visibility index are
derived once from the selectolax tree; the captured network bodies are kept as the bundle holds them. Every consumer
(collectors, content formats, pagination, the engine executor) takes a `ParsedPage`, never the raw body.
"""

import itertools
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property

from lxml import html as lxml_html
from pydantic import JsonValue
from selectolax import lexbor

from crawlerai.acquire.items import Group, item_groups, lxml_of
from crawlerai.content.attr_json import DOCUMENTED, SELECTOR
from crawlerai.content.fragments import FRAME_HEADER, Answers, append, declares_frames, include, is_partial
from crawlerai.content.segment import rank
from crawlerai.content.text import CleanedText, VisibleIndex, render, script_revealed, xpath_step
from crawlerai.core.json_text import parse
from crawlerai.storage.capture_bundle import CaptureBundle, NetworkBody, decode_html, is_html

# HTML Standard §4.12.3: a `template` whose `shadowrootmode` is `open` or `closed` is a declarative shadow root.
_SHADOW_ROOT = "template[shadowrootmode]"
_SHADOW_MARK = re.compile("shadowrootmode", re.IGNORECASE)
_SHADOW_MODES = frozenset({"open", "closed"})
_TEMPLATE = "template"
# React Fizz instruction set (`completeBoundary`, called as `$RC("<boundary id>", "<content id>")`): the call that
# moves a streamed segment into its Suspense boundary. A `$RX` call renders the fallback on the client: nothing moves.
_COMPLETE = re.compile(r"""\$RC\(\s*(["'])([^"']+)\1\s*,\s*(["'])([^"']+)\3\s*\)""")
# Fizz boundary comments: `<!--$-->`, `<!--$?-->`, `<!--$!-->` open one, `<!--/$-->` closes it.
_OPEN, _CLOSE = "$", "/$"


@dataclass(frozen=True)
class ScriptBlock:
    """An inline `<script>`: its type's MIME essence (`""` when absent), its raw text, and its XPath 1.0 path in the
    selectolax tree (the same element's in `lxml_tree`)."""

    type: str
    text: str
    xpath: str


# The JSON-LD media type (JSON-LD 1.1, IANA considerations); HTML embeds JSON-LD in a script element of that type
# (JSON-LD 1.1 §7.3).
JSON_LD = "application/ld+json"


@dataclass(frozen=True)
class JsonLdBlock:
    """An `application/ld+json` block as JSON: its document, or why it is no JSON text (`error`, the document None)."""

    document: JsonValue
    error: str | None = None


@dataclass(frozen=True)
class AttributeBlock:
    """A documented JSON attribute (`content.attr_json.DOCUMENTED`): its element's tag, its name, its value as the
    parser unescaped it, and its element's XPath 1.0 path in the selectolax tree."""

    tag: str
    name: str
    value: str
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
        url: str | None = None,
    ) -> None:
        # The document after its structural pre-passes (`prepassed`), which every reader of the page reads.
        fetched = () if json_body or not network_entries else _html_answers(network, network_entries)
        answers = _answers(fetched) if fetched and declares_frames(html) else None
        partials = tuple((entry.url, text) for entry, text in fetched if is_partial(text))
        self.html = html if json_body else prepassed(html, url, answers, partials)
        # The document as it arrived, before its pre-passes (`content.signals` reads its declarative shadow roots).
        self.source_html = html
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
        # read once (INV-26): the extraction pipeline's collection, its scripts' state documents (`collect.js_state`).
        # Each is kept with the inputs it was derived from, compared by identity.
        self.derived: dict[type, tuple[tuple[object, ...], object]] = {}

    @classmethod
    def of(cls, bundle: CaptureBundle) -> "ParsedPage":
        manifest = bundle.manifest
        return cls(
            bundle.text,
            bundle.network,
            manifest.network_bodies,
            json_body=manifest.method == "api",
            item_areas=manifest.item_areas,
            url=manifest.final_url,
        )

    @cached_property
    def tree(self) -> lexbor.LexborHTMLParser:
        return lexbor.LexborHTMLParser(self.html)

    @cached_property
    def lxml_tree(self) -> lxml_html.HtmlElement:
        return lxml_of(self.tree)

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
    def json_ld(self) -> tuple[JsonLdBlock, ...]:
        """The page's JSON-LD blocks in document order, each parsed once for every reader (the JSON-LD collector, the
        `metadata` format). Raw control characters inside strings and a number with leading zeros are read as
        `core.json_text.parse` reads them (RFC 8259 §9: a parser may accept extensions)."""
        found: list[JsonLdBlock] = []
        for script in self.scripts:
            if script.type == JSON_LD:
                try:
                    found.append(JsonLdBlock(parse(script.text, lenient=True)))
                except ValueError as e:
                    found.append(JsonLdBlock(None, str(e)))
        return tuple(found)

    @cached_property
    def json_attributes(self) -> tuple[AttributeBlock, ...]:
        """The documented JSON attributes of the page's elements, in document order."""
        return tuple(
            AttributeBlock(tag=node.tag or "", name=name, value=value or "", xpath=node_xpath(node))
            for node in self.tree.css(SELECTOR)
            for name, value in node.attributes.items()
            if name in DOCUMENTED
        )

    @cached_property
    def item_groups(self) -> tuple[Group, ...]:
        """The page's groups of repeated item blocks, best first (the item layer's segment step, `content.segment`)."""
        return rank(item_groups(self.lxml_tree), self.item_areas, self.revealed)

    @cached_property
    def revealed(self) -> frozenset[str]:
        """The node paths of the concealed elements a script reveals (`content.text.script_revealed`), which the
        cleaned text shows."""
        return frozenset(node_xpath(node) for node in self.tree.css("[hidden], [style]") if script_revealed(node))

    @cached_property
    def run_starts(self) -> tuple[int, ...]:
        """Where each text run of the cleaned text starts, in order (the runs are in document order)."""
        return tuple(run.start for run in self.cleaned_text.offsets)

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

    @cached_property
    def word_joins(self) -> tuple[int, ...]:
        """The offsets of the cleaned text where the text runs of two elements, neither holding the other, meet with a
        letter or digit on each side and nothing between them (`<span>Engineer</span><span>Paris</span>`): CSS Text 3
        renders adjacent inline boxes without a space, so a template running two of its fields' words together sets
        them apart by a layout the cleaned text does not apply (each a line of its own)."""
        text, runs = self.cleaned_text.text, self.cleaned_text.offsets
        return tuple(
            right.start
            for left, right in itertools.pairwise(runs)
            if left.end == right.start
            and text[left.end - 1 : left.end].isalnum()
            and text[right.start].isalnum()
            and not _nested(left.node_path, right.node_path)
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


def _nested(a: str, b: str) -> bool:
    """Whether one of two node paths is the other's or an ancestor's."""
    return a == b or a.startswith(f"{b}/") or b.startswith(f"{a}/")


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


def prepassed(
    html: str, url: str | None = None, answers: Answers | None = None, partials: Sequence[tuple[str, str]] = ()
) -> str:
    """The document after the four structural pre-passes, in this order (extraction spec, "Source documents"): each
    declarative shadow root's content in place of its `template` under its host; each Suspense boundary a `$RC` call
    completed holding its streamed segment; each eager Turbo frame of the page at `url` holding the matching element
    of its answer in `answers`; and the fetched `partials` (URL, markup) whose text it does not show appended to its
    body (`content.fragments`). No script runs. A document none applies to is returned as it is, unparsed."""
    shadow = _SHADOW_MARK.search(html) is not None
    streamed = "$RC(" in html
    frames = bool(answers) and url is not None and declares_frames(html)
    if not (shadow or streamed or frames or partials):
        return html
    tree = lexbor.LexborHTMLParser(html)
    if shadow:
        _flatten_shadow_roots(tree)
    if streamed:
        _complete_boundaries(tree)
    included = include(tree, url, answers) if frames and url is not None and answers else set()
    if partials:
        append(tree, partials, included)
    return tree.html or html


def _flatten_shadow_roots(tree: lexbor.LexborHTMLParser) -> None:
    """HTML Standard: a declarative shadow root's content is its host's rendered content, so it takes the template's
    place among the host's children; slotted light-DOM children stay where they are. A shadow root inside one is
    flattened in turn."""
    while True:
        template = next(
            (t for t in tree.css(_SHADOW_ROOT) if (t.attributes.get("shadowrootmode") or "").lower() in _SHADOW_MODES),
            None,
        )
        if template is None:
            return
        # The parser keeps a template's content apart from the tree; its serialization holds it.
        for name in [*template.attrs.keys()]:
            del template.attrs[name]
        markup = template.html or ""
        for node in lexbor.parse_fragment(markup[len(_TEMPLATE) + 2 : -(len(_TEMPLATE) + 3)]):
            template.insert_before(node)
        template.decompose()


def _complete_boundaries(tree: lexbor.LexborHTMLParser) -> None:
    """For each `$RC(boundary, content)` call of an inline script, the children of the (hidden) element with the
    content id take the place of the `template` with the boundary id, and the fallback after it, up to the boundary's
    closing comment, is removed, as `completeBoundary` does."""
    for script in tree.css("script"):
        if "src" in script.attributes:
            continue
        for match in _COMPLETE.finditer(script.text(deep=True)):
            # Looked up per call: a completed segment may hold a boundary a later call completes.
            marker, content = tree.css_first(f'[id="{match.group(2)}"]'), tree.css_first(f'[id="{match.group(4)}"]')
            if marker is None or content is None or marker.tag != _TEMPLATE:
                continue
            _remove_fallback(marker)
            for child in content.iter(include_text=True):
                marker.insert_before(child)
            marker.decompose()
            content.decompose()


def _remove_fallback(marker: lexbor.LexborNode) -> None:
    """Remove the siblings after a boundary's `template`, up to the comment that closes the boundary (nested
    boundaries counted); without that comment nothing is removed."""
    fallback: list[lexbor.LexborNode] = []
    depth, node = 0, marker.next
    while node is not None:
        if node.is_comment_node:
            data = (node.comment_content or "").strip()
            if data == _CLOSE and depth == 0:
                for sibling in fallback:
                    sibling.decompose()
                return
            depth += data.startswith(_OPEN) - (data == _CLOSE)
        fallback.append(node)
        node = node.next


def _html_answers(network: tuple[bytes, ...], entries: tuple[NetworkBody, ...]) -> tuple[tuple[NetworkBody, str], ...]:
    """The captured 2xx HTML answers (no data call's), each decoded as an HTTP body (`decode_html`), in capture
    order."""
    return tuple(
        (entry, decode_html(body, entry.response_headers or _labelled(entry), "http"))
        for body, entry in zip(network, entries, strict=False)
        if 200 <= entry.status < 300 and entry.data_call is None and is_html(entry.content_type)
    )


def _labelled(entry: NetworkBody) -> tuple[tuple[str, str], ...]:
    """A body's `Content-Type` as its only header, for an entry that kept no response headers."""
    return () if entry.content_type is None else (("content-type", entry.content_type),)


def _answers(fetched: Sequence[tuple[NetworkBody, str]]) -> dict[tuple[str, str | None], str]:
    """The `fetched` HTML answers by URL and the frame their request named (`fragments.FRAME_HEADER`): the eager
    frames' answers."""
    answers: dict[tuple[str, str | None], str] = {}
    for entry, text in fetched:
        frame = next((v for n, v in entry.request_headers or () if n.lower() == FRAME_HEADER.lower()), None)
        answers.setdefault((entry.url, frame), text)
    return answers
