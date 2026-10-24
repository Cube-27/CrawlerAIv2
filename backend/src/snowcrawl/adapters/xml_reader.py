"""A safe, bounded XML reader for the feeds adapters read (XML 1.0, W3C REC-xml, §4.4 and §2.8; OWASP XXE prevention):
the document as the JSON value its adapter's `Shape` reads.

The body is already capped by the fetch (`FetchPolicy.max_body_bytes`). The parser neither resolves entities nor
loads a DTD, reaches no network and takes no huge tree, so an entity-expansion or external-entity document cannot
grow the parse; a document with a DOCTYPE at all is refused, a feed has none.

Every element with child elements is an object whose members are its children's names, each an array of that name's
elements in document order (a child present once is an array of one, so a shape always walks `name`, `ALL`); an
element with no child elements is its text, whitespace-trimmed, `None` when empty. Attributes and comments are not read.
"""

from lxml import etree
from pydantic import JsonValue


def read_xml(body: bytes) -> JsonValue:
    """The document element as `{name: [value]}` (one member, its own name); `ValueError` for a body that is not a
    well-formed XML document, has a DOCTYPE, or nests past the parser's depth limit."""
    try:
        parser = etree.XMLParser(
            resolve_entities=False,
            load_dtd=False,
            no_network=True,
            huge_tree=False,
            dtd_validation=False,
            remove_comments=True,
            remove_pis=True,
        )
        root = etree.fromstring(body, parser)
        doctype = root.getroottree().docinfo.doctype
    except etree.XMLSyntaxError as e:
        raise ValueError(f"not XML: {e.msg}") from e
    if doctype:
        raise ValueError("an XML document with a DOCTYPE is not read")
    return {_name(root): [_value(root)]}


def _name(element: etree._Element) -> str:
    return etree.QName(element).localname


def _value(element: etree._Element) -> JsonValue:
    children = [child for child in element if isinstance(child.tag, str)]
    if not children:
        text = (element.text or "").strip()
        return text or None
    members: dict[str, list[JsonValue]] = {}
    for child in children:
        members.setdefault(_name(child), []).append(_value(child))
    return dict(members)
