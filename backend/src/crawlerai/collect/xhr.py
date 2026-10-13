"""The captured network JSON collector (SPEC-05 §4.5, ARCHITECTURE §8.1): the bodies a browser capture kept.

Each body is one document, read as UTF-8 JSON text (RFC 8259 §8.1); a body that is not is skipped with a diagnostic.
Values are admitted by `admission`; locators are `xhr:<n>:<path>`, `n` the body's index in the bundle.
"""

from collections.abc import Sequence

from crawlerai.collect.admission import Admitted, Document, admit
from crawlerai.collect.base import Candidate
from crawlerai.collect.json_doc import parse
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef


class XhrCollector:
    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context, others: Sequence[Candidate]) -> Admitted:
        diagnostics: list[str] = []
        return admit("xhr", network_documents(page, diagnostics), diagnostics, page, schema, ctx, others)


def network_documents(page: ParsedPage, diagnostics: list[str]) -> list[Document]:
    """The page's captured network bodies that are UTF-8 JSON, each addressed by its index in the bundle."""
    documents: list[Document] = []
    for index, body in enumerate(page.network):
        try:
            documents.append(Document(parse(body.decode("utf-8")), str(index)))
        except ValueError as e:  # UnicodeDecodeError is a ValueError
            diagnostics.append(f"xhr:{index}: not UTF-8 JSON ({e})")
    return documents
