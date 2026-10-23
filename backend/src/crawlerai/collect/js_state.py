"""The embedded JSON state collector: the state a page carries in its inline scripts.

The documents are each script's state (`content.state.script_state`), each decoded by its documented shape
(`content.state_decoders.decode`: devalue flat arrays, normalized caches): read by structure only, no variable name
or key looked up. Values are admitted by `admission`; locators are `js_state:<script_xpath>:<path>`, so the documents
of one script share its address. The page's Flight stream (`content.state.flight_rows`) is one document more, after
them: its JSON rows by row id, each decoded, located as `rsc:<row>:<path in the row>`.
Each documented JSON attribute's document follows, located as `attr:<element_xpath>@<name>:<path>`.
"""

from collections.abc import Sequence
from typing import cast

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


class _ScriptDocuments:
    """The key of a page's script documents, and the diagnostics reading them gave, in `ParsedPage.derived`."""


def script_documents(page: ParsedPage, diagnostics: list[str]) -> list[Document]:
    """The page's inline scripts' state documents, decoded, each addressed by its script's XPath, then its Flight
    stream's (`flight_document`). They are read once per parse: a later caller gets the same documents, and
    the diagnostics reading them gave."""
    derived = page.derived.get(_ScriptDocuments)
    if derived is None:
        found: list[str] = []
        documents = [Document(decode(data), s.xpath) for s in page.scripts for data in script_state(s, found)]
        if (flight := flight_document(page, found)) is not None:
            documents.append(flight)
        derived = ((), (documents, found))
        page.derived[_ScriptDocuments] = derived
    documents, found = cast(tuple[list[Document], list[str]], derived[1])
    diagnostics.extend(found)
    return list(documents)


def flight_document(page: ParsedPage, diagnostics: list[str]) -> Document | None:
    """The page's inline Flight stream as one document of its JSON rows by row id, each decoded; None without one."""
    if (flight := flight_rows(page.scripts, diagnostics)) is not None and (rows := model_rows(flight[1])):
        return Document({row_id: decode(value) for row_id, value in rows.items()}, flight[0], "rsc")
    return None


class _AttributeDocuments:
    """The key of a page's attribute documents in `ParsedPage.derived`."""


def attribute_documents(page: ParsedPage) -> list[Document]:
    """The page's documented JSON attributes' documents, in document order, decoded once per parse."""
    derived = page.derived.get(_AttributeDocuments)
    if derived is None:
        documents = [
            Document(decode(data), f"{a.xpath}@{a.name}", "attr")
            for a in page.json_attributes
            if (data := attribute_document(a.tag, a.name, a.value)) is not None
        ]
        derived = ((), documents)
        page.derived[_AttributeDocuments] = derived
    return list(cast(list[Document], derived[1]))
