"""The state a page carries in its inline scripts, read by structure only.

A document is the text of a `<script type="application/json">` (or Adobe Commerce's `text/x-magento-init`), or, in
any other script except JSON-LD's, in script order:
- the object or array literal after the `=` of an assignment: `window.<ident> =`, `var|let|const <ident> =`, or a bare
  `<ident> =` (ECMAScript AssignmentExpression and variable declaration syntax);
- each object literal argument of a call `<ident>(…)` or `<ident>.<ident>…(…)` whose arguments before it are literals
  or references (ECMAScript CallExpression: `dataLayer.push({…})`, `fbq('track', 'ViewContent', {…})`,
  `kit.start(app, element, {…})`).
Values are read by the JS literal reader (`content.js_literal`); a value that is not a literal (a function, a call)
is code, not state, and so is a literal followed by more of its expression (`{…}.items`). The search for the next one
starts after the value just read and skips comments and string and template literals, so an assignment written inside
a string or a commented-out call is not one. No variable name or key is looked up. The JSON state collector
(`collect.js_state`) decodes and admits values from these documents.

A page's React Server Components payload is one more document (`flight_rows`): Next.js's App Router writes it as
`self.__next_f.push([<segment>, <chunk>])` calls (`client/app-index.tsx`), whose UTF-8 string chunks (segment 1) and
base64 binary chunks (segment 3) make one Flight stream in script order, split anywhere, rows included; segments 0
(bootstrap) and 2 (form state) are no part of it. The stream is read by the RSC Flight reader (`content.rsc`).
"""

import base64
import re
from collections.abc import Iterator, Sequence

from pydantic import JsonValue

from crawlerai.content.js_literal import IDENT, STRINGS, NotLiteral, ends_value, read_literal, skip_space
from crawlerai.content.page import ScriptBlock
from crawlerai.content.rsc import MAX_BYTES, Row, read_rows
from crawlerai.core.json_text import parse

# RFC 8259 §1.2 / IANA media types: `application/json` holds JSON text.
_JSON = "application/json"
# Adobe Commerce, JavaScript initialization: `text/x-magento-init` scripts hold JSON (`{"<selector>": {...}}`).
_MAGENTO_INIT = "text/x-magento-init"
# W3C JSON-LD 1.1 §7.3: JSON-LD's script data blocks, which hold linked data, not a script's state.
_JSON_LD = "application/ld+json"
# ECMAScript: an assignment to an identifier or to a property of `window` (the global object in a browser, HTML
# Standard), `var|let|const` included; `=` not followed by `=` or `>` is assignment, not comparison or an arrow. Or
# the callee of a call: an identifier or a member chain that is not itself a member of what precedes it.
_STATEMENT = re.compile(
    rf"(?:\bwindow\s*\.\s*|(?<![\w$.])){IDENT}\s*=(?![=>])|(?<![\w$.]){IDENT}(?:\s*\.\s*{IDENT})*\s*\("
)
# ECMAScript comments, string and template literals: code inside them is not a statement.
_SKIP_START = re.compile(r"//|/\*|['\"`]")
_SKIPPED = {
    "//": re.compile(r"//[^\n\r\u2028\u2029]*"),
    "/*": re.compile(r"/\*.*?\*/", re.S),
    "`": re.compile(r"`(?:[^`\\]|\\[\s\S])*`"),
    **STRINGS,
}
# ECMAScript: an identifier reference or a member chain (`app`, `document.body`), an argument that is not state.
_REFERENCE = re.compile(rf"{IDENT}(?:\s*\.\s*{IDENT})*")
# Next.js `client/app-index.tsx`: the call that hands the client a Flight chunk, and its UTF-8 and base64 segments.
_FLIGHT_PUSH = re.compile(r"\bself\s*\.\s*__next_f\s*\.\s*push\s*\(")
_UTF8_CHUNK, _BASE64_CHUNK = 1, 3
_SURROGATE = re.compile("[\ud800-\udfff]")


def script_state(script: ScriptBlock, diagnostics: list[str]) -> Iterator[JsonValue]:
    """The state documents of one inline script, in order; an invalid JSON script adds a diagnostic."""
    if script.type == _JSON_LD:  # the JSON-LD collector's blocks
        return
    if script.type in (_JSON, _MAGENTO_INIT):
        try:
            yield parse(script.text)
        except ValueError as e:
            diagnostics.append(f"js_state:{script.xpath}: invalid JSON ({e})")
        return
    text, start = script.text, 0
    while (match := _next_code(_STATEMENT, text, start)) is not None:
        start = match.end()
        if text[start - 1] == "(":
            for argument, end in _object_arguments(text, start):
                yield argument
                start = end
            continue
        try:
            data, start = read_literal(text, start)
        except NotLiteral:
            continue
        # State is an object or an array; a scalar initializer (`var n = 1`) is a script variable.
        if isinstance(data, (dict, list)) and ends_value(text, start):
            yield data


def _next_code(pattern: re.Pattern[str], text: str, start: int) -> re.Match[str] | None:
    """The next match of `pattern` (an assignment or a call) at or after `start` that is not inside a comment or a
    string or template literal. The pattern is searched again only when a skipped literal or comment passes the
    match's start: a match is the same from any start at or before it, so the text is read once."""
    match = pattern.search(text, start)
    while match is not None:
        opener = _SKIP_START.search(text, start, match.start())
        if opener is None:
            return match
        skipped = _SKIPPED[opener.group()].match(text, opener.start())
        start = opener.end() if skipped is None else skipped.end()  # an unterminated quote (`/'/`) is skipped alone
        if start > match.start():
            match = pattern.search(text, start)
    return None


def _object_arguments(text: str, pos: int) -> Iterator[tuple[JsonValue, int]]:
    """The object literal arguments of the call whose `(` ends before `pos`, each with the index after it, up to the
    first argument that is neither a literal nor a reference."""
    pos = skip_space(text, pos)
    while text[pos : pos + 1] not in ("", ")"):
        try:
            value, end = read_literal(text, pos)
        except NotLiteral:
            reference = _REFERENCE.match(text, pos)
            if reference is None:
                return
            value, end = None, reference.end()
        pos = skip_space(text, end)
        if text[pos : pos + 1] not in (",", ")"):  # `{…}.x`, `a + b`: an expression, not that literal
            return
        if isinstance(value, dict):
            yield value, end
        if text[pos] == ",":
            pos = skip_space(text, pos + 1)


def flight_rows(scripts: Sequence[ScriptBlock], diagnostics: list[str]) -> tuple[str, list[Row]] | None:
    """The rows of the page's Flight stream, with the XPath of the first script that pushes a chunk of it; None when no
    script does."""
    stream = bytearray()
    first: str | None = None
    for script in scripts:
        for chunk in _flight_chunks(script.text, f"js_state:{script.xpath}", diagnostics):
            first = first or script.xpath
            stream += chunk
            if len(stream) > MAX_BYTES:  # stop gathering: `read_rows` reads no stream this long
                return first, read_rows(bytes(stream), f"js_state:{first}", diagnostics)
    if first is None:
        return None
    return first, read_rows(bytes(stream), f"js_state:{first}", diagnostics)


def _flight_chunks(text: str, source: str, diagnostics: list[str]) -> Iterator[bytes]:
    start = 0
    while (match := _next_code(_FLIGHT_PUSH, text, start)) is not None:
        start = match.end()
        try:
            segment, start = read_literal(text, start)
        except NotLiteral:
            continue
        if not isinstance(segment, list) or len(segment) < 2 or isinstance(segment[0], bool):
            continue
        if not isinstance(segment[1], str):
            continue
        if segment[0] == _UTF8_CHUNK:
            # A lone surrogate is encoded as U+FFFD, as the browser's `TextEncoder` does (Encoding Standard §8.2).
            yield _SURROGATE.sub("\ufffd", segment[1]).encode()
        elif segment[0] == _BASE64_CHUNK:
            try:
                yield base64.b64decode(segment[1], validate=True)
            except ValueError as e:  # binascii.Error, or a character outside ASCII
                diagnostics.append(f"{source}: Flight chunk is not base64 ({e})")
