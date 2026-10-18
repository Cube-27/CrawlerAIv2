"""JSON text (RFC 8259) as the engine reads it from pages, their calls and platform answers: the one reader every
such site uses, so a body that is not JSON, is not text, or nests deeper than the parser can follow is the same
`ValueError` everywhere instead of a crash (a deeply nested document raises `RecursionError` in Python's parser).

The release executor keeps a copy of its own: it shares no code with the engine (INV-20).
"""

import json
import re

from pydantic import JsonValue


def parse(data: str | bytes, *, lenient: bool = False) -> JsonValue:
    """`data` as one JSON value; raises `ValueError` when it is not JSON. Bytes are decoded as RFC 8259 §8.1 says JSON
    text is exchanged, UTF-8, with the UTF-16 and UTF-32 forms RFC 4627 §3 let a reader tell from the first bytes
    (`json.detect_encoding`). `lenient` also accepts raw control characters (U+0000-U+001F) inside strings, which RFC
    8259 §7 requires escaped and §9 lets a parser accept as an extension: a raw newline in a string is unambiguous, so
    the value is the one an escaped newline would give."""
    text = data.decode(json.detect_encoding(data)) if isinstance(data, bytes) else data
    decoder = _LENIENT_DECODER if lenient else _DECODER
    try:
        return decoder.decode(text)  # type: ignore[no-any-return]
    except RecursionError:
        raise ValueError("nested too deeply") from None


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
# RFC 8259 §2: insignificant whitespace is space, horizontal tab, line feed and carriage return.
_NOT_WHITESPACE = re.compile(r"[^ \t\n\r]")
