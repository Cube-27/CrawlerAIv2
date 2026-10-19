"""The JS literal reader (extraction spec, "Source documents"): the value a script writes as an ECMAScript literal,
read without evaluating anything.

The grammar is the ECMAScript literal subset: object literals (identifier, string or numeric keys), array literals,
trailing commas, string literals in either quote with their escapes, numeric literals (decimal with fraction and
exponent, `0x`, `0o`, `0b`, a leading `-`), `true`, `false`, `null`, `undefined` and `void 0` (both read as `null`),
parentheses, and the devalue IIFE `(function(a,b){return <literal>}(<literals>))` (devalue's `uneval` output, Nuxt 2's
`window.__NUXT__=`), whose parameters are replaced by its arguments. JSON text is a subset of the grammar and is read
by the JSON reader first. Anything else (a function body, a call, an operator) is not a literal: `NotLiteral`.

Hostile input is bounded: nesting deeper than `MAX_DEPTH` or a value of more than `MAX_NODES` values is `NotLiteral`.
"""

import re
from typing import Any

from pydantic import JsonValue

from crawlerai.core.json_text import parse_prefix

# Bounds on what one read builds: the nesting depth and the number of values, substituted parameters counted at their
# size each time they are used.
MAX_DEPTH = 128
MAX_NODES = 1_000_000


class NotLiteral(ValueError):
    """The text at the position is not a literal of the grammar (module docstring)."""


# ECMAScript WhiteSpace and LineTerminator, and comments.
_SPACE = re.compile(r"(?:[\s\ufeff]+|/\*.*?\*/|//[^\n\r\u2028\u2029]*)*", re.S)
# ECMAScript IdentifierName, its ASCII part plus Unicode letters: `$`, `_` or a letter, then those or digits.
IDENT = r"(?!\d)[\w$]+"
_IDENT = re.compile(IDENT)
# ECMAScript NumericLiteral (numeric separators aside): a hex, octal or binary integer, or a decimal literal.
_RADIX_NUMBER = re.compile(r"0[xXoObB][\da-fA-F]+")
_RADIX = {"x": 16, "o": 8, "b": 2}
_DECIMAL = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
# ECMAScript StringLiteral: no unescaped quote or line terminator; an escape takes the next character (CRLF as one).
STRINGS = {q: re.compile(rf"{q}((?:[^{q}\\\n\r]|\\(?:\r\n|[\s\S]))*){q}") for q in ("'", '"')}
# ECMAScript EscapeSequence: unicode code point and code unit escapes, hex escapes, line continuations, single chars.
_ESCAPE = re.compile(r"\\(u\{[0-9a-fA-F]{1,6}\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|\r\n|[\s\S])")
_SINGLE_ESCAPES = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", "0": "\0"}
_LINE_CONTINUATIONS = frozenset({"\n", "\r", "\r\n", "\u2028", "\u2029"})
_SURROGATE = re.compile("[\ud800-\udfff]")
_CONSTANTS: dict[str, JsonValue] = {"true": True, "false": False, "null": None, "undefined": None}
# devalue IIFE: `function(<params>){return ` opens it.
_IIFE_HEAD = re.compile(rf"function\s*\(\s*((?:{IDENT}\s*(?:,\s*{IDENT}\s*)*)?)\)\s*\{{\s*return\b")


def skip_space(text: str, pos: int) -> int:
    """The index of the first character at or after `pos` that is not whitespace or a comment."""
    found = _SPACE.match(text, pos)
    return pos if found is None else found.end()


# What may follow the end of an expression statement's value: on the same line, after spaces and comments, a `;`, `,`
# or closing bracket, a line terminator (ECMAScript automatic semicolon insertion) or the end of the text.
_VALUE_END = re.compile(r"[ \t\ufeff]*(?:/\*.*?\*/[ \t]*)*(?:$|//|[;,)}\]\n\r\u2028\u2029])", re.S)


def ends_value(text: str, pos: int) -> bool:
    """Whether the value read up to `pos` is the whole value: `"USD".replace(…)` or `{…}.items` is another
    expression, not that literal."""
    return _VALUE_END.match(text, pos) is not None


def read_literal(text: str, start: int = 0) -> tuple[JsonValue, int]:
    """The literal that starts at `text[start]` after optional whitespace, ignoring what follows it, and the index just
    past it; raises `NotLiteral` when none does."""
    try:
        return parse_prefix(text, start)
    except ValueError:
        pass
    reader = _Reader(text)
    value = reader.value(skip_space(text, start), 0, {})
    return value, reader.pos


class _Param:
    """A devalue IIFE parameter in its body, replaced by its argument once the arguments are read."""


class _Reader:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.nodes = 0

    def value(self, pos: int, depth: int, env: dict[str, _Param]) -> Any:
        if depth > MAX_DEPTH:
            raise NotLiteral("nested too deeply")
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise NotLiteral("too many values")
        char = self.text[pos : pos + 1]
        if char == "{":
            return self._object(pos + 1, depth, env)
        if char == "[":
            return self._array(pos + 1, depth, env)
        if char in STRINGS:
            return self._string(pos)
        if char == "(":
            return self._parenthesized(pos + 1, depth, env)
        if char == "-":
            return -self._number(skip_space(self.text, pos + 1))
        if char.isdigit() or char == ".":
            return self._number(pos)
        return self._identifier(pos, env)

    def _object(self, pos: int, depth: int, env: dict[str, _Param]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        pos = skip_space(self.text, pos)
        while self.text[pos : pos + 1] != "}":
            key, pos = self._key(pos)
            pos = self._expect(pos, ":")
            result[key] = self.value(skip_space(self.text, pos), depth + 1, env)
            pos = self._separator(self.pos, "}")
        self.pos = pos + 1
        return result

    def _array(self, pos: int, depth: int, env: dict[str, _Param]) -> list[Any]:
        result: list[Any] = []
        pos = skip_space(self.text, pos)
        while self.text[pos : pos + 1] != "]":
            result.append(self.value(pos, depth + 1, env))
            pos = self._separator(self.pos, "]")
        self.pos = pos + 1
        return result

    def _key(self, pos: int) -> tuple[str, int]:
        char = self.text[pos : pos + 1]
        if char in STRINGS:
            return self._string(pos), self.pos
        if found := _IDENT.match(self.text, pos):
            return found.group(), found.end()
        if char.isdigit() or char == ".":
            number = self._number(pos)
            return str(number), self.pos
        raise NotLiteral(f"no property name at {pos}")

    def _separator(self, pos: int, close: str) -> int:
        """After a member: `,` (a trailing one allowed) or the closing bracket; the index of the next member or of the
        bracket."""
        pos = skip_space(self.text, pos)
        char = self.text[pos : pos + 1]
        if char == ",":
            return skip_space(self.text, pos + 1)
        if char == close:
            return pos
        raise NotLiteral(f"no `,` or `{close}` at {pos}")

    def _expect(self, pos: int, char: str) -> int:
        pos = skip_space(self.text, pos)
        if self.text[pos : pos + 1] != char:
            raise NotLiteral(f"no `{char}` at {pos}")
        return skip_space(self.text, pos + 1)

    def _string(self, pos: int) -> str:
        found = STRINGS[self.text[pos]].match(self.text, pos)
        if found is None:
            raise NotLiteral(f"unterminated string at {pos}")
        self.pos = found.end()
        value = _ESCAPE.sub(_unescape, found.group(1))
        if _SURROGATE.search(value):  # JS strings are UTF-16: escaped surrogate pairs are one character
            value = value.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")
        return value

    def _number(self, pos: int) -> int | float:
        found = _RADIX_NUMBER.match(self.text, pos) or _DECIMAL.match(self.text, pos)
        if found is None or _IDENT.match(self.text, found.end()):  # `1px`, `0x` alone: not a numeric literal
            raise NotLiteral(f"no number at {pos}")
        self.pos = found.end()
        written = found.group()
        if radix := _RADIX.get(written[1:2].lower()):
            try:
                return int(written[2:], radix)
            except ValueError:  # `0b12`: a digit outside the radix
                raise NotLiteral(f"no number at {pos}") from None
        if any(c in written for c in ".eE"):
            return float(written)
        return int(written)

    def _identifier(self, pos: int, env: dict[str, _Param]) -> Any:
        found = _IDENT.match(self.text, pos)
        if found is None:
            raise NotLiteral(f"no literal at {pos}")
        name = found.group()
        self.pos = found.end()
        if name in env:
            return env[name]
        if name in _CONSTANTS:
            return _CONSTANTS[name]
        if name == "void":  # `void 0`: `undefined`
            self._number(skip_space(self.text, self.pos))
            return None
        raise NotLiteral(f"`{name}` is not a literal")

    def _parenthesized(self, pos: int, depth: int, env: dict[str, _Param]) -> Any:
        pos = skip_space(self.text, pos)
        if head := _IIFE_HEAD.match(self.text, pos):
            return self._iife(head, depth, env)
        value = self.value(pos, depth + 1, env)
        self.pos = self._expect(self.pos, ")")
        return value

    def _iife(self, head: re.Match[str], depth: int, env: dict[str, _Param]) -> Any:
        """The devalue IIFE after its opening `(`, `function(<params>){return <literal>}(<args>))` or
        `function(…){…})(<args>)`, each parameter in the body replaced by its argument (`undefined` when there is
        none)."""
        params = {name.strip(): _Param() for name in head.group(1).split(",") if name.strip()}
        body = self.value(skip_space(self.text, head.end()), depth + 1, {**env, **params})
        pos = skip_space(self.text, self.pos)
        if self.text[pos : pos + 1] == ";":
            pos = skip_space(self.text, pos + 1)
        pos = self._expect(pos, "}")
        called_outside = self.text[pos : pos + 1] == ")"
        pos = self._expect(pos + 1 if called_outside else pos, "(")
        args, pos = self._arguments(pos, depth, env)
        self.pos = pos if called_outside else self._expect(pos, ")")
        bound = {id(param): args[i] if i < len(args) else (None, 0) for i, param in enumerate(params.values())}
        return self._substitute(body, bound, depth)

    def _arguments(self, pos: int, depth: int, env: dict[str, _Param]) -> tuple[list[tuple[Any, int]], int]:
        """The literal arguments up to `)`, each with its number of values, and the index after the `)`."""
        args: list[tuple[Any, int]] = []
        while self.text[pos : pos + 1] != ")":
            before = self.nodes
            args.append((self.value(pos, depth + 1, env), self.nodes - before))
            pos = self._separator(self.pos, ")")
        return args, pos + 1

    def _substitute(self, node: Any, bound: dict[int, tuple[Any, int]], depth: int) -> Any:
        if depth > MAX_DEPTH:
            raise NotLiteral("nested too deeply")
        if isinstance(node, _Param):
            if id(node) not in bound:  # an enclosing IIFE's parameter: replaced by that IIFE
                return node
            value, size = bound[id(node)]
            self.nodes += size
            if self.nodes > MAX_NODES:
                raise NotLiteral("too many values")
            return value
        if isinstance(node, dict):
            return {key: self._substitute(member, bound, depth + 1) for key, member in node.items()}
        if isinstance(node, list):
            return [self._substitute(item, bound, depth + 1) for item in node]
        return node


def _unescape(escape: re.Match[str]) -> str:
    sequence = escape.group(1)
    if sequence[0] in "ux":
        if len(sequence) == 1:  # `\u` or `\x` without its digits: a syntax error
            raise NotLiteral("malformed escape")
        code = int(sequence[1:].strip("{}"), 16)
        if code > 0x10FFFF:
            raise NotLiteral("code point out of range")
        return chr(code)
    if sequence in _LINE_CONTINUATIONS:
        return ""
    return _SINGLE_ESCAPES.get(sequence, sequence)
