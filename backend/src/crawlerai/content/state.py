"""The JSON state a page carries in its inline scripts (extraction spec, "embedded JSON state"), read by structure only.

A document is the text of a `<script type="application/json">`, or, in any other script except JSON-LD's, the JSON value
after the `=` of each `window.<ident> =` or `var|let|const <ident> =` assignment (ECMAScript assignment and variable
declaration syntax), in script order; the search for the next one starts after the value just read, so an assignment
written inside a string of that value is not one. Script code that is not such an assignment is not state. No variable
name or key is looked up. The JSON state collector (`collect.js_state`) admits values from these documents; resolution
weighs them as a sign the page's data came with its HTML (`holds_state`).
"""

import re
from collections.abc import Iterator
from typing import Final

from pydantic import JsonValue

from crawlerai.content.page import ParsedPage, ScriptBlock
from crawlerai.core.json_text import parse, parse_prefix

# RFC 8259 §1.2 / IANA media types: `application/json` holds JSON text.
_JSON = "application/json"
# W3C JSON-LD 1.1 §7.3: JSON-LD's script data blocks, which hold linked data, not a script's state.
_JSON_LD = "application/ld+json"
# ECMAScript IdentifierName, its ASCII part plus Unicode letters: `$`, `_` or a letter, then those or digits.
_IDENT = r"(?:[^\W\d]|\$)[\w$]*"
# ECMAScript: an assignment to a property of `window` (the global object in a browser, HTML Standard), or a variable
# declaration with an initializer. `=` not followed by `=` or `>` is assignment, not comparison or an arrow.
# The fewest scalar values (RFC 8259 strings, numbers, literals) a state document holds to be the page's data, not a
# script's settings: an unmeasured starting point, to be confirmed on dev.
STATE_MIN_VALUES: Final = 50
_ASSIGNMENT = re.compile(rf"(?:\bwindow\s*\.\s*|\b(?:var|let|const)\s+){_IDENT}\s*=(?![=>])")


def script_state(script: ScriptBlock, diagnostics: list[str]) -> Iterator[JsonValue]:
    """The state documents of one inline script, in order; an invalid JSON script adds a diagnostic."""
    if script.type == _JSON_LD:  # the JSON-LD collector's blocks
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


def holds_state(page: ParsedPage) -> bool:
    """Whether the page carries a state document of at least `STATE_MIN_VALUES` scalar values: its data came with the
    HTML, for its script to render."""
    return any(_values(document) >= STATE_MIN_VALUES for s in page.scripts for document in script_state(s, []))


def _values(document: JsonValue) -> int:
    """The scalar values of a JSON document, counted up to `STATE_MIN_VALUES` (walked with a stack, not recursion)."""
    count, stack = 0, [document]
    while stack and count < STATE_MIN_VALUES:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
        else:
            count += 1
    return count
