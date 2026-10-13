"""One parsed page per capture (ARCHITECTURE §8 "Parse once", Appendix A #31, INV-26; SPEC-05 §4.1).

The body is decoded once and parsed at most once per parser: selectolax on first use, lxml only when an XPath step or
trafilatura asks for it. The script blocks, the cleaned text and the visibility index are derived once from the
selectolax tree. Every consumer (collectors, content formats, pagination, the engine executor) takes a `ParsedPage`,
never the raw body.
"""

from dataclasses import dataclass
from functools import cached_property

from lxml import etree
from lxml import html as lxml_html
from selectolax import lexbor

from crawlerai.content.text import CleanedText, VisibleIndex, render, xpath_step
from crawlerai.storage.capture_bundle import CaptureBundle, decode_body


@dataclass(frozen=True)
class ScriptBlock:
    """An inline `<script>`: its type's MIME essence (`""` when absent), its raw text, and its XPath 1.0 path in the
    selectolax tree (not guaranteed to resolve in `lxml_tree`: libxml2 builds HTML trees differently)."""

    type: str
    text: str
    xpath: str


class ParsedPage:
    def __init__(self, html: str) -> None:
        self.html = html

    @classmethod
    def of(cls, bundle: CaptureBundle) -> "ParsedPage":
        return cls(decode_body(bundle))

    @cached_property
    def tree(self) -> lexbor.LexborHTMLParser:
        return lexbor.LexborHTMLParser(self.html)

    @cached_property
    def lxml_tree(self) -> lxml_html.HtmlElement:
        # lxml refuses a str that carries an XML encoding declaration, so it gets the decoded text back as UTF-8 with
        # the encoding named; the declaration is then ignored, and both parsers read the same characters.
        parser = lxml_html.HTMLParser(encoding="utf-8")
        try:
            return lxml_html.document_fromstring(self.html.encode("utf-8"), parser=parser)
        except etree.ParserError:  # an empty or all-whitespace document has no root element to return
            return lxml_html.Element("html")

    @cached_property
    def scripts(self) -> tuple[ScriptBlock, ...]:
        # HTML Standard, the script element: a script with `src` runs the external resource, not its text. The type
        # attribute is a MIME type, compared by its essence (WHATWG MIME Sniffing: lower-cased, parameters dropped).
        blocks: list[ScriptBlock] = []
        for node in self.tree.css("script"):
            attributes = node.attributes
            if "src" not in attributes:
                media_type = (attributes.get("type") or "").split(";", 1)[0].strip().lower()
                blocks.append(ScriptBlock(type=media_type, text=node.text(deep=True), xpath=_xpath(node)))
        return tuple(blocks)

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


def _xpath(node: lexbor.LexborNode) -> str:
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
