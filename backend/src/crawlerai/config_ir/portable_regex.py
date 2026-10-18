"""The regex subset of config steps and `regex_replace` (learning-configs spec, D-0034).

Exported configs run their regexes in PHP (PCRE2, `preg_*`) and the engine runs them in Python `re`. A pattern passes
when Python compiles it and every construct in it is one both engines read the same way; anything else is refused,
not translated. The check is a conservative scan (Python `re` syntax; PCRE2 `pcre2pattern`), so some patterns both
engines share are refused too.

Both engines treat `\\d`, `\\w`, `\\s` and `\\b` as ASCII classes only when Python compiles with `re.ASCII` (PCRE2 does
without the UCP option), so Python compiles these patterns with `PCRE_FLAGS`. Exports run them in PCRE2's UTF mode (PHP
`/u`), where `.` and classes match code points as in Python; but there PCRE2 folds case for non-ASCII letters and
Python with `re.ASCII` does not, so a pattern with the `i` flag must be ASCII.
"""

import re
import string
from typing import Final

# The flags that give Python PCRE2's reading of a portable pattern.
PCRE_FLAGS: Final = re.ASCII
# Escapes with the same meaning in both: classes, anchors other than the end of string, and control characters.
_LETTER_ESCAPES: Final = frozenset("dDsSwWbBntrfA")
# Inside a class `\b` is a backspace in Python and PCRE, but reads like a word boundary; refused there.
_CLASS_LETTER_ESCAPES: Final = frozenset("dDsSwWntrf")
# `(?...)` openers both engines read alike: non-capturing group, lookarounds, a named group, a named backreference,
# and the `i`, `m` and `s` flags, set for the rest of the pattern or for one group.
# PCRE2 group names are at most 32 characters; Python refuses one that starts with a digit.
_GROUP_OPENERS: Final = (
    re.compile(r"\?<?[=!]"),
    re.compile(r"\?P(?:<\w{1,32}>|=\w{1,32}\))", re.ASCII),
    re.compile(r"\?[ims]*(?:-[ims]+)?[:)]"),
)
# A counted quantifier: `{n}`, `{n,}` or `{n,m}`. Python reads `{,m}` as `{0,m}`, older PCRE as literal text.
_COUNTED: Final = re.compile(r"\{\d+(?:,\d*)?\}", re.ASCII)
# A backreference `\1` to `\9`: `\10` is group 10 or octal depending on the engine and the group count.
_BACKREFERENCE: Final = re.compile(r"\\[1-9](?!\d)", re.ASCII)
# What a replacement may reference: `\` escapes (including a trailing one) and PHP's `$n` and `${n}`.
_REPLACEMENT_REFERENCE: Final = re.compile(r"\\(?:\d+|.?)|\$[\d{]", re.ASCII | re.DOTALL)
_HEX_ESCAPE: Final = re.compile(r"\\x[0-9A-Fa-f]{2}")
# Python warns on these inside a class (reserved for set operations); PCRE reads them as characters.
_CLASS_DOUBLES: Final = ("&&", "--", "~~", "||")
# An inline flag group that names `i`, to set or clear it (either way part of the pattern is caseless), and a `\xhh`
# escape above U+007F. Exported regexes run with PHP `/u` (PCRE2 UTF mode).
_CASELESS: Final = re.compile(r"\(\?[-ms]*i[-ims]*[:)]")
_NON_ASCII_HEX: Final = re.compile(r"\\x[89A-Fa-f][0-9A-Fa-f]")


class RegexError(ValueError):
    """A pattern or replacement outside the portable subset; the message names the construct."""


def check_pattern(pattern: str) -> str:
    """`pattern` unchanged when Python compiles it and both engines read every construct in it alike."""
    position = 0
    while position < len(pattern):
        position = _skip_construct(pattern, position)
    if _CASELESS.search(pattern) and (not pattern.isascii() or _NON_ASCII_HEX.search(pattern)):
        raise RegexError("a caseless pattern has non-ASCII characters, which PCRE2 /u and Python fold differently")
    try:
        re.compile(pattern, PCRE_FLAGS)
    except re.error as error:
        raise RegexError(f"not a valid pattern: {error}") from None
    return pattern


def check_replacement(replacement: str, pattern: re.Pattern[str]) -> str:
    """`replacement` unchanged when `re.sub` and `preg_replace` read it alike: literal text and group references
    `\\1` to `\\9` to groups `pattern` has. `$1` and `${1}` are PHP references and Python text, so they are refused."""
    for match in _REPLACEMENT_REFERENCE.finditer(replacement):
        reference = match.group()
        if reference == "\\":
            raise RegexError("trailing backslash")
        if not _BACKREFERENCE.fullmatch(reference):
            raise RegexError(f"{reference} is not a portable replacement")
        if int(reference[1:]) > pattern.groups:
            raise RegexError(f"group {reference[1:]} is not in the pattern")
    return replacement


def _skip_construct(pattern: str, position: int) -> int:
    """The position after the construct that starts at `position`, refusing one outside the subset."""
    char = pattern[position]
    if char == "\\":
        return _skip_escape(pattern, position, _LETTER_ESCAPES, backreferences=True)
    if char == "(" and pattern.startswith("?", position + 1):
        return _skip_group_opener(pattern, position)
    if char == "{":
        counted = _COUNTED.match(pattern, position)
        if counted is None:
            raise RegexError(f"{_until(pattern, position, '}')} is not a counted quantifier; escape a literal {{")
        return counted.end()
    if char == "[":
        return _skip_class(pattern, position)
    return position + 1


def _skip_group_opener(pattern: str, position: int) -> int:
    for opener in _GROUP_OPENERS:
        if match := opener.match(pattern, position + 1):
            return match.end()
    raise RegexError(f"{pattern[position : position + 4]} is not a portable group")


def _skip_escape(pattern: str, position: int, letters: frozenset[str], *, backreferences: bool) -> int:
    escape = pattern[position : position + 2]
    following = escape[1:]
    if following in letters or (following and following in string.punctuation):
        return position + 2
    if backreferences and (reference := _BACKREFERENCE.match(pattern, position)):
        return reference.end()
    if hex_escape := _HEX_ESCAPE.match(pattern, position):
        return hex_escape.end()
    raise RegexError(f"{pattern[position : position + 3]} is not a portable escape")


def _skip_class(pattern: str, position: int) -> int:
    """A character class `[...]`: ranges, the escapes classes share and literal characters, nothing nested."""
    position += 2 if pattern.startswith("[^", position) else 1
    if pattern.startswith("]", position):
        raise RegexError("a ] first in a class is written \\]")
    while position < len(pattern) and pattern[position] != "]":
        if pattern[position] == "[":
            raise RegexError("[ inside a class is written \\[")
        if pattern.startswith(_CLASS_DOUBLES, position):
            raise RegexError(f"{pattern[position : position + 2]} inside a class is reserved in Python")
        if pattern[position] == "\\":
            position = _skip_escape(pattern, position, _CLASS_LETTER_ESCAPES, backreferences=False)
        else:
            position += 1
    return position + 1


def _until(text: str, start: int, end: str) -> str:
    stop = text.find(end, start)
    return text[start:] if stop < 0 else text[start : stop + 1]
