"""The regex subset of config steps and `regex_replace` (SPEC-08 §4.2, ARCHITECTURE §12.2, D-0034).

Exported configs run their regexes in PHP (PCRE2, `preg_*`) and the engine runs them in Python `re`. A pattern passes
when Python compiles it and every construct in it is one both engines read the same way; anything else is refused,
not translated. The check is a conservative scan (Python `re` syntax; PCRE2 `pcre2pattern`), so some patterns both
engines share are refused too.

Both engines treat `\\d`, `\\w`, `\\s` and `\\b` as ASCII classes only when Python compiles with `re.ASCII` (PCRE2 does
without the UCP option), so `compile_portable` does.
"""

import re
import string
from typing import Final

# Escapes with the same meaning in both: classes, anchors other than the end of string, and control characters.
_LETTER_ESCAPES: Final = frozenset("dDsSwWbBntrfA")
# Inside a class `\b` is a backspace in Python and PCRE, but reads like a word boundary; refused there.
_CLASS_LETTER_ESCAPES: Final = frozenset("dDsSwWntrf")
# `(?...)` openers both engines read alike: non-capturing group, lookarounds, a named group, a named backreference,
# and the `i`, `m` and `s` flags, set for the rest of the pattern or for one group.
_GROUP_OPENERS: Final = re.compile(
    r"\?(?::|=|!|<=|<!|P<[A-Za-z_][A-Za-z0-9_]{0,31}>|P=[A-Za-z_][A-Za-z0-9_]{0,31}\)|[ims]*(?:-[ims]+)?[:)])"
)
# A counted quantifier: `{n}`, `{n,}` or `{n,m}`. Python reads `{,m}` as `{0,m}`, older PCRE as literal text.
_COUNTED: Final = re.compile(r"\{\d+(?:,\d*)?\}")
# A backreference `\1` to `\9`: `\10` is group 10 or octal depending on the engine and the group count.
_BACKREFERENCE: Final = re.compile(r"\\[1-9](?![0-9])")
_HEX_ESCAPE: Final = re.compile(r"\\x[0-9A-Fa-f]{2}")
# Python warns on these inside a class (reserved for set operations); PCRE reads them as characters.
_CLASS_DOUBLES: Final = ("&&", "--", "~~", "||")


class RegexError(ValueError):
    """A pattern or replacement outside the portable subset; the message names the construct."""


def compile_portable(pattern: str) -> re.Pattern[str]:
    """`pattern` compiled with the flags that give Python PCRE2's reading of it."""
    check_pattern(pattern)
    return re.compile(pattern, re.ASCII)


def check_pattern(pattern: str) -> str:
    """`pattern` unchanged when Python compiles it and both engines read every construct in it alike."""
    position = 0
    while position < len(pattern):
        position = _skip_construct(pattern, position)
    try:
        re.compile(pattern, re.ASCII)
    except re.error as error:
        raise RegexError(f"not a valid pattern: {error}") from None
    return pattern


def check_replacement(replacement: str, pattern: re.Pattern[str]) -> str:
    """`replacement` unchanged when `re.sub` and `preg_replace` read it alike: literal text and group references
    `\\1` to `\\9` to groups `pattern` has. `$1` and `${1}` are PHP references and Python text, so they are refused."""
    for match in re.finditer(r"\\(?:[0-9]+|.?)|\$(?:[0-9]|\{)", replacement, re.DOTALL):
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
        opener = _GROUP_OPENERS.match(pattern, position + 1)
        if opener is None:
            raise RegexError(f"{pattern[position : position + 4]} is not a portable group")
        return opener.end()
    if char == "{":
        counted = _COUNTED.match(pattern, position)
        if counted is None:
            raise RegexError(f"{_until(pattern, position, '}')} is not a counted quantifier; escape a literal {{")
        return counted.end()
    if char == "[":
        return _skip_class(pattern, position)
    return position + 1


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
