"""The text forms every layer compares in (normalization spec, "One module per type"): composed, white space collapsed
or set aside, cut short by an ellipsis, split into sentences, and folded to words.

Folding is for comparison only: a published value keeps the form the page states (`compose` and `collapse` are the
text normalization's own steps). A text is cut only where a caller's spec already cuts it.
"""

import re
import unicodedata
from typing import Final

# Unicode U+2026 HORIZONTAL ELLIPSIS and its compatibility decomposition (NFKC), three U+002E FULL STOPs: how a text
# cut short ends.
ELLIPSES: Final = ("…", "...")
# Unicode general category Cc (U+0000 to U+001F, U+007F to U+009F): control characters are not text. Those that are
# Unicode White_Space (tab, line breaks, NEL) are kept for the whitespace collapse; the rest are removed.
_CONTROLS = dict.fromkeys(c for c in [*range(0x20), *range(0x7F, 0xA0)] if not chr(c).isspace())
# CJK sentences end without a following space (Unicode Sentence_Break=STerm: U+3002, U+FF01, U+FF1F).
_IDEOGRAPHIC_END = r"[\u3002\uff01\uff1f]"
# The closing punctuation a sentence's terminator may be followed by (UAX #29 Sentence_Break=Close: quotation marks
# and closing brackets, among them U+201D, U+2019, U+00BB, U+203A).
_CLOSE = "\"')\\]\u2019\u201d\u00bb\u203a"
_TERMINATED = re.compile(rf"[.!?\u2026]+[{_CLOSE}]*(?=\s)|{_IDEOGRAPHIC_END}")
_IDEOGRAPHIC = re.compile(_IDEOGRAPHIC_END)


def compose(s: str) -> str:
    """The non-whitespace control characters removed, then Unicode NFC (UAX #15), so one text has one form (a removed
    control between a letter and its combining mark leaves them composed). Text a parser has already decoded (DOM
    text) takes this step without the entity decoding."""
    return unicodedata.normalize("NFC", s.translate(_CONTROLS))


def collapse(s: str) -> str:
    """Each run of Unicode White_Space (what `str.split` splits on) one space, the ends trimmed."""
    return " ".join(s.split())


def solid(s: str) -> str:
    """The text with its white space set aside: renditions that break lines or join paragraphs differently compare
    equal."""
    return "".join(s.split())


def uncut(s: str) -> str:
    """The text without the one ellipsis (`ELLIPSES`) that ends it."""
    for ellipsis in ELLIPSES:
        if s.endswith(ellipsis):
            return s.removesuffix(ellipsis)
    return s


def is_cut_of(short: str, long: str, *, word_boundary: bool) -> bool:
    """Whether `long` begins with `short`, or with `short` before the ellipsis that ends it, white space aside; `long`
    may equal it. With `word_boundary`, a cut not marked by an ellipsis must not split a word of `long` (UAX #29
    approximated by letters and digits): "The cat" begins "The cat sat", not "The category"."""
    whole = solid(short)
    cut = uncut(whole)
    if not cut or not solid(long).startswith(cut):
        return False
    if not word_boundary or cut != whole:
        return True
    left, end = len(cut), 0
    while left:
        left -= not long[end].isspace()
        end += 1
    return not (end < len(long) and cut[-1].isalnum() and long[end].isalnum())


def sentences(text: str) -> list[str]:
    """The sentences of `text`, in order (UAX #29 sentence boundaries, approximated): each ends at a full stop, `!`,
    `?` or ellipsis followed by white space and not by a lower-case letter, or at an ideographic full stop."""
    found: list[str] = []
    start = 0
    for match in _TERMINATED.finditer(text):
        rest = text[match.end() :].lstrip()
        if (rest and not rest[0].islower()) or _IDEOGRAPHIC.fullmatch(match.group()):
            found.append(text[start : match.end()].strip())
            start = match.end()
    found.append(text[start:].strip())
    return [sentence for sentence in found if sentence]


def fold_words(text: str, *, digits: bool = True, marks: bool = True) -> list[str]:
    """`text`'s words for comparison: NFKC (UAX #15), Unicode default case folding, split on every character that is
    not a letter (general category L), a mark (M) or, with `digits`, a number (N). Marks continue a word in scripts
    that write vowels as combining characters (UAX #29 WB4); without `marks` they are dropped after NFKD, so diacritics
    fold (a URL slug writes `Café` as `cafe`). Without `digits` a number separates words and is no word itself
    (vocabulary phrases)."""
    kinds = "LMN" if digits else "LM"
    words: list[str] = []
    word: list[str] = []
    for char in unicodedata.normalize("NFKC" if marks else "NFKD", text).casefold():
        kind = unicodedata.category(char)[0]
        if kind == "M" and not marks:
            continue
        if kind in kinds:
            word.append(char)
        elif word:
            words.append("".join(word))
            word = []
    if word:
        words.append("".join(word))
    return words


def fold(text: str, *, marks: bool = True) -> str:
    """`text`'s folded words (`fold_words`) run together: case, punctuation and white space aside."""
    return "".join(fold_words(text, marks=marks))
