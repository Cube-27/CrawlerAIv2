"""The XPath 1.0 check for config steps (SPEC-08 §4.2, ARCHITECTURE §12.1, D-0034).

Exported configs run in PHP `DOMXPath` and in lxml, which both implement W3C XPath 1.0 through libxml2. libxml2
compiles calls to functions it does not have and fails only when they run, so an expression passes here when lxml
compiles it and its tokens (XPath 1.0 §3.7) call only the core function library (XPath 1.0 §4). Variable references
and namespace prefixes need bindings a config cannot carry, so they are refused too.
"""

import re
from collections.abc import Iterator
from typing import Final

from lxml import etree

# W3C XPath 1.0 §4.1 to 4.4: the core function library.
XPATH1_FUNCTIONS: Final = frozenset(
    {
        *("last", "position", "count", "id", "local-name", "namespace-uri", "name"),
        *("string", "concat", "starts-with", "contains", "substring-before", "substring-after", "substring"),
        *("string-length", "normalize-space", "translate"),
        *("boolean", "not", "true", "false", "lang"),
        *("number", "sum", "floor", "ceiling", "round"),
    }
)
# XPath 1.0 §2.3 NodeType: written like a call, but a node test.
_NODE_TYPES: Final = frozenset({"comment", "text", "processing-instruction", "node"})
# XPath 1.0 §3.7 OperatorName.
_OPERATOR_NAMES: Final = frozenset({"and", "or", "mod", "div"})
# XPath 1.0 §3.7 ExprToken. NCName is approximated by word characters plus `.` and `-` (XML Names §3).
_TOKEN: Final = re.compile(
    r"""
    (?P<space>\s+)
    | (?P<literal>"[^"]*"|'[^']*')
    | (?P<number>\d+(?:\.\d*)?|\.\d+)
    | (?P<variable>\$)
    | (?P<name>[^\W\d][\w.\-]*(?::(?:[^\W\d][\w.\-]*|\*))?)
    | (?P<punct>\.\.|::|//|!=|<=|>=|[./()\[\]@,|+\-=<>*])
    """,
    re.VERBOSE,
)
# §3.7: after one of these (or at the start) a `*` is a name test and an NCName is a name, not an operator.
_OPERAND_STARTS: Final = frozenset(
    {"@", "::", "(", "[", ",", "/", "//", "|", "+", "-", "=", "!=", "<", "<=", ">", ">="}
)


class XPath1Error(ValueError):
    """An expression outside XPath 1.0 as the IR allows it; the message names the construct."""


def check_xpath1(expression: str) -> str:
    """`expression` unchanged when it is XPath 1.0 that libxml2 compiles and that calls only core functions."""
    try:
        etree.XPath(expression)
    except etree.XPathSyntaxError as error:
        raise XPath1Error(f"not XPath 1.0: {error}") from None
    tokens = list(_tokens(expression))
    after_operand = False
    for i, (kind, text) in enumerate(tokens):
        is_operator = after_operand and (text == "*" or text in _OPERATOR_NAMES)
        if kind == "name" and not is_operator:
            _check_name(text, calls=i + 1 < len(tokens) and tokens[i + 1][1] == "(")
        after_operand = not is_operator and (kind != "punct" or text not in _OPERAND_STARTS)
    return expression


def _tokens(expression: str) -> Iterator[tuple[str, str]]:
    position = 0
    while position < len(expression):
        match = _TOKEN.match(expression, position)
        if match is None:
            raise XPath1Error(f"{expression[position]!r} is not an XPath 1.0 token")
        kind = match.lastgroup or ""  # every alternative is a named group
        if kind == "variable":
            raise XPath1Error("variable references are not allowed")
        if kind != "space":
            yield kind, match.group()
        position = match.end()


def _check_name(name: str, *, calls: bool) -> None:
    if ":" in name:
        raise XPath1Error(f"namespace prefix in {name}")
    if calls and name not in XPATH1_FUNCTIONS | _NODE_TYPES:
        raise XPath1Error(f"{name}() is not an XPath 1.0 function")
