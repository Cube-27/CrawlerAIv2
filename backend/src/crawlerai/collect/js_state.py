"""The embedded JSON state collector (extraction spec): the state a page carries in its inline scripts.

The documents are each script's state (`content.state.script_state`), each decoded by its documented shape
(`content.state_decoders.decode`: devalue flat arrays, normalized caches): read by structure only, no variable name
or key looked up. Values are admitted by `admission`; locators are `js_state:<script_xpath>:<path>`, so the documents
of one script share its address.
"""

from collections.abc import Sequence

from crawlerai.collect.admission import Admitted, Document, admit
from crawlerai.collect.base import Candidate
from crawlerai.content.page import ParsedPage
from crawlerai.content.state import script_state
from crawlerai.content.state_decoders import decode
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef


class JsStateCollector:
    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context, others: Sequence[Candidate]) -> Admitted:
        diagnostics: list[str] = []
        return admit("js_state", state_documents(page, diagnostics), diagnostics, page, schema, ctx, others)


def state_documents(page: ParsedPage, diagnostics: list[str]) -> list[Document]:
    """The page's state documents, decoded, each addressed by its script's XPath."""
    return [Document(decode(data), s.xpath) for s in page.scripts for data in script_state(s, diagnostics)]
