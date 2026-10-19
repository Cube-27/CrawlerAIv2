"""The embedded JSON state collector (extraction spec): the state a page carries in its inline scripts.

The documents are each script's state (`content.state.script_state`), each decoded by its documented shape
(`content.state_decoders.decode`: devalue flat arrays, normalized caches): read by structure only, no variable name
or key looked up. Values are admitted by `admission`; locators are `js_state:<script_xpath>:<path>`, so the documents
of one script share its address. The page's Flight stream (`content.state.flight_rows`) is one document more, after
them: its JSON rows by row id, each decoded, addressed by the first script that pushes a chunk of it.
Each documented JSON attribute's document follows, located as `attr:<element_xpath>@<name>:<path>`.
"""

from collections.abc import Sequence

from crawlerai.collect.admission import Admitted, Document, admit
from crawlerai.collect.base import Candidate
from crawlerai.content.attr_json import attribute_document
from crawlerai.content.page import ParsedPage
from crawlerai.content.rsc import model_rows
from crawlerai.content.state import flight_rows, script_state
from crawlerai.content.state_decoders import decode
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef


class JsStateCollector:
    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context, others: Sequence[Candidate]) -> Admitted:
        diagnostics: list[str] = []
        return admit("js_state", state_documents(page, diagnostics), diagnostics, page, schema, ctx, others)


def state_documents(page: ParsedPage, diagnostics: list[str]) -> list[Document]:
    """The page's state documents, decoded: its scripts' (`script_documents`), then its documented JSON attributes'
    (`content.attr_json`), each addressed as `<element xpath>@<name>` under the `attr` scheme."""
    return script_documents(page, diagnostics) + attribute_documents(page)


def script_documents(page: ParsedPage, diagnostics: list[str]) -> list[Document]:
    """The page's inline scripts' state documents, decoded, each addressed by its script's XPath, then its Flight
    stream's."""
    documents = [Document(decode(data), s.xpath) for s in page.scripts for data in script_state(s, diagnostics)]
    if (flight := flight_rows(page.scripts, diagnostics)) is not None and (rows := model_rows(flight[1])):
        documents.append(Document({row_id: decode(value) for row_id, value in rows.items()}, flight[0]))
    return documents


def attribute_documents(page: ParsedPage) -> list[Document]:
    """The page's documented JSON attributes' documents, in document order."""
    return [
        Document(decode(data), f"{a.xpath}@{a.name}", "attr")
        for a in page.json_attributes
        if (data := attribute_document(a.tag, a.name, a.value)) is not None
    ]
