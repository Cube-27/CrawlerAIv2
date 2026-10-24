"""JSON text (RFC 8259) as the engine reads it from pages, their calls and platform answers: the one reader every
such site uses, so a body that is not JSON, is not text, or nests deeper than the parser can follow is the same
`ValueError` everywhere instead of a crash (a deeply nested document raises `RecursionError` in Python's parser).

The release executor keeps a copy of its own: it shares no code with the engine.
"""

import json
import re

from pydantic import JsonValue


def parse(data: str | bytes, *, lenient: bool = False) -> JsonValue:
    """`data` as one JSON value; raises `ValueError` when it is not JSON. Bytes are decoded as RFC 8259 §8.1 says JSON
    text is exchanged, UTF-8, with the UTF-16 and UTF-32 forms RFC 4627 §3 let a reader tell from the first bytes
    (`json.detect_encoding`). `lenient` also accepts raw control characters (U+0000-U+001F) inside strings, which RFC
    8259 §7 requires escaped and §9 lets a parser accept as an extension: a raw newline in a string is unambiguous, so
    the value is the one an escaped newline would give. It also accepts a number written with leading zeros
    (`0745114652584`), which RFC 8259 §6 forbids: its value is the digits as written, a string, since reading them as
    a number would drop the zeros the page wrote (an identifier such as a GTIN, written unquoted). And it accepts a
    trailing comma before the `]` or `}` that closes an array or object, which RFC 8259 §5 and §4 do not allow (a
    comma separates two values or members): it separates nothing, so the value is the one written without it."""
    text = data.decode(json.detect_encoding(data)) if isinstance(data, bytes) else data
    try:
        return _decode(text, _LENIENT_DECODER if lenient else _DECODER)
    except ValueError:
        if not lenient or (written := _extended(text)) == text:
            raise
        return _decode(written, _LENIENT_DECODER)


def _decode(text: str, decoder: json.JSONDecoder) -> JsonValue:
    try:
        return decoder.decode(text)  # type: ignore[no-any-return]
    except RecursionError:
        raise ValueError("nested too deeply") from None


def _extended(text: str) -> str:
    """`text` with the extensions `parse(lenient=True)` accepts written as RFC 8259 JSON."""
    return _TRAILING_COMMAS.sub(_without_comma, _LEADING_ZEROS.sub(_as_written, text))


def _as_written(match: re.Match[str]) -> str:
    """A string token as it is, a number with leading zeros as a string of its digits (`parse`)."""
    return match[0] if match["number"] is None else f'{match["space"]}"{match["number"]}"'


def _without_comma(match: re.Match[str]) -> str:
    """A string token, or an opening bracket's comma, as it is; a trailing comma as nothing (`parse`)."""
    return "" if match[0] == "," else match[0]


def parse_prefix(text: str, start: int) -> tuple[JsonValue, int]:
    """The JSON value that starts at `text[start]` after optional whitespace, ignoring what follows it, and the index
    just past it; raises `ValueError` when none does."""
    found = _NOT_WHITESPACE.search(text, start)
    start = len(text) if found is None else found.start()
    try:
        return _DECODER.raw_decode(text, start)
    except RecursionError:
        raise ValueError("nested too deeply") from None


def _not_json(constant: str) -> JsonValue:
    # RFC 8259 §6: `NaN` and `Infinity` are not JSON numbers, though Python's parser reads them.
    raise ValueError(f"{constant} is not JSON")


_DECODER = json.JSONDecoder(parse_constant=_not_json)
# `strict=False` relaxes exactly the control characters inside strings (Python `json` docs); nothing else.
_LENIENT_DECODER = json.JSONDecoder(parse_constant=_not_json, strict=False)
# RFC 8259 §7: a string token, its escapes included (`[\s\S]`: lenient strings may hold raw line breaks), is skipped
# whole; outside strings, a value (after `[`, `:`, `, ` or the text's start and before `, `, `]`, `}` or its end)
# that is a number (ASCII digits) with a zero before further integer digits.
_LEADING_ZEROS = re.compile(
    r'"(?:[^"\\]|\\[\s\S])*"'
    r"|(?:(?<=[\[:,])|(?<![\s\S]))(?P<space>[ \t\n\r]*)(?P<number>-?0[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?)"
    r"(?=[ \t\n\r]*(?:[,\]}]|\Z))"
)
# RFC 8259 §7: a string token is skipped whole, as above, and so is a comma right after `[` or `{` (§5: it follows no
# value, so `[, ]` stays invalid); outside strings, a comma (value separator) followed only by whitespace before
# the `]` or `}` that ends its array or object.
_TRAILING_COMMAS = re.compile(r'"(?:[^"\\]|\\[\s\S])*"|[\[{][ \t\n\r]*,|,(?=[ \t\n\r]*[\]}])')
# RFC 8259 §2: insignificant whitespace is space, horizontal tab, line feed and carriage return.
_NOT_WHITESPACE = re.compile(r"[^ \t\n\r]")
