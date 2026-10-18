"""The embedded JSON state collector (SPEC-05 §4.5, ARCHITECTURE §8.1): JSON a page carries in its inline scripts.

A document is the text of a `<script type="application/json">` (an invalid one is skipped with a diagnostic), or, in
any other script except JSON-LD's, the JSON value after the `=` of each `window.<ident> =` or `var|let|const <ident> =`
assignment (ECMAScript assignment and variable declaration syntax), in script order; the search for the next one
starts after the value just read, so an assignment written inside a string of that value is not one. Script code that
is not such an assignment is not state, and is skipped without a diagnostic. The structure is all that is read: no
variable name or key is looked up. Values are admitted by `admission`; locators are `js_state:<script_xpath>:<path>`,
so the documents of one script share its address.
"""

import re
from collections.abc import Iterator, Sequence

from pydantic import JsonValue

from crawlerai.collect.admission import Admitted, Document, admit
from crawlerai.collect.base import Candidate
from crawlerai.collect.jsonld import MEDIA_TYPE as JSONLD
from crawlerai.content.page import ParsedPage, ScriptBlock
from crawlerai.core.json_text import parse, parse_prefix
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef

# RFC 8259 §1.2 / IANA media types: `application/json` holds JSON text.
_JSON = "application/json"
# ECMAScript IdentifierName, its ASCII part plus Unicode letters: `$`, `_` or a letter, then those or digits.
_IDENT = r"(?:[^\W\d]|\$)[\w$]*"
# ECMAScript: an assignment to a property of `window` (the global object in a browser, HTML Standard), or a variable
# declaration with an initializer. `=` not followed by `=` or `>` is assignment, not comparison or an arrow.
_ASSIGNMENT = re.compile(rf"(?:\bwindow\s*\.\s*|\b(?:var|let|const)\s+){_IDENT}\s*=(?![=>])")


class JsStateCollector:
    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context, others: Sequence[Candidate]) -> Admitted:
        diagnostics: list[str] = []
        return admit("js_state", state_documents(page, diagnostics), diagnostics, page, schema, ctx, others)


def state_documents(page: ParsedPage, diagnostics: list[str]) -> list[Document]:
    """The page's state documents, each addressed by its script's XPath."""
    return [Document(data, s.xpath) for s in page.scripts for data in _documents(s, diagnostics)]


def _documents(script: ScriptBlock, diagnostics: list[str]) -> Iterator[JsonValue]:
    if script.type == JSONLD:  # the JSON-LD collector's blocks
        return
    if script.type == _JSON:
        try:
            yield parse(script.text)
        except ValueError as e:
            diagnostics.append(f"js_state:{script.xpath}: invalid JSON ({e})")
        return
    start = 0
    while (match := _ASSIGNMENT.search(script.text, start)) is not None:
        start = match.end()
        try:
            data, start = parse_prefix(script.text, start)
        except ValueError:
            continue  # not JSON (`var f = function …`): code, not state
        # State is an object or an array; a scalar initializer (`var n = 1`) is a script variable.
        if isinstance(data, (dict, list)):
            yield data
