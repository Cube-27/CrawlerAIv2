"""The names an item's attributes state, and the run of their words a block shows (listings spec, "Rows from blocks"):
WCAG 2.1 SC 2.5.3 (Label in Name) has a component's accessible name hold its visible label, so a stated name is
checked against the block's shown lines (`collect.items.align`)."""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from crawlerai.normalize.strings import fold, uncut

_LINE: Final = re.compile(r"[^\n]+")
_TOKEN: Final = re.compile(r"\S+")


@dataclass(frozen=True, slots=True)
class Word:
    """A word of a block's shown text: its folded form (`strings.fold`), its span of the cleaned text, whether it
    starts or ends its line, and whether its line ends in an ellipsis that cut it short."""

    key: str
    start: int
    end: int
    first: bool
    last: bool
    cut: bool


@dataclass(frozen=True, slots=True)
class Stated:
    """A name the item's attributes state and the run of its words the block shows: WCAG 2.1 SC 2.5.3 (Label in Name)
    has the accessible name hold the visible label, here one or several whole lines of the block in order, folded
    (`strings.fold`: case and punctuation aside), the last of them possibly cut short by an ellipsis
    (`strings.ELLIPSES`: a truncated display of the name); leading words the block shows as lines of their own apart
    from the run are left out of `text` (`_lines_before`). `lead` and `trail` are the folded words before and after
    the shown run (none shown: the whole name is neither); `xpath` is the shown run's innermost element, else the
    stating element's; `shown_at` is the shown run's span of the cleaned text."""

    text: str
    xpath: str
    covered: int = 0
    start: int = 0
    end: int = 0
    lead: str = ""
    trail: str = ""
    cut: bool = False  # the shown run ends in a word an ellipsis cut short: the name goes on past it
    shown_at: tuple[int, int] = (0, 0)

    @property
    def shown(self) -> bool:
        return self.covered > 0

    @classmethod
    def of(cls, text: str, xpath: str, words: Sequence[Word], holding: Callable[[int, int], str]) -> "Stated":
        keys = [(key, m.start(), m.end()) for m in _TOKEN.finditer(text) if (key := fold(m.group()))]
        folded = [key for key, _, _ in keys]
        best = max(
            ((_run(folded, i, words, j), i, j) for j, w in enumerate(words) if w.first for i in range(len(keys))),
            key=lambda found: (found[0], -found[1]),
            default=(0, 0, 0),
        )
        covered, i, j = best
        if not covered:
            return cls(text, xpath)
        start, end = keys[i][1], keys[i + covered - 1][2]
        # Leading words the block shows as whole lines of their own apart from the run (a designer line, a size line,
        # then the product line) are another statement the name joins (Accessible Name Computation 1.2: an `alt` may
        # join several), not part of the run's label: the name is the run on.
        if i and _lines_before(folded[:i], words, j):
            text, start, end = text[start:], 0, end - start
        shown_at = (words[j].start, words[j + covered - 1].end)
        return cls(
            text,
            holding(*shown_at),
            covered,
            start,
            end,
            fold(text[:start]),
            fold(text[end:]),
            words[j + covered - 1].cut,
            shown_at,
        )

    def trimmed(self, *, lead: bool, trail: bool) -> str:
        """The name without its unshown leading and trailing words, as asked."""
        return self.text[self.start if lead else 0 : self.end if trail else len(self.text)].strip()


def _run(keys: Sequence[str], i: int, words: Sequence[Word], j: int) -> int:
    """How many of the stated words from `i` the block's words from `j` show in order, up to the end of a line: a word
    matches by its folded form, or by its start when it is the cut-short last word of a line, which ends the run."""
    count = whole = 0
    while i + count < len(keys) and j + count < len(words):
        key, word = keys[i + count], words[j + count]
        prefix = word.cut and word.last and key != word.key and key.startswith(word.key)
        if key != word.key and not prefix:
            break
        count += 1
        whole = count if word.last else whole
        if prefix:
            break
    return whole


def _lines_before(keys: Sequence[str], words: Sequence[Word], j: int) -> bool:
    """Whether whole lines of the block before its word `j`, not running on into it, show all of `keys` in order and
    nothing else; a line an ellipsis cut short goes on, so it is no such line."""
    return any(
        words[k].first and _run(keys, 0, words, k) == len(keys) and not any(w.cut for w in words[k : k + len(keys)])
        for k in range(j - len(keys) - 1, -1, -1)
    )


def words(text: str, start: int, end: int) -> list[Word]:
    """The words of `text[start:end]` (a block's shown text, `ParsedPage.cleaned_text`), line by line; a line ending in
    an ellipsis is read without it, its last word cut short."""
    found: list[Word] = []
    for line in _LINE.finditer(text, start, end):
        body = line.group().rstrip()
        whole, body = body, uncut(body)
        cut = body != whole
        keyed = [(m, key) for m in _TOKEN.finditer(body) if (key := fold(m.group()))]
        found.extend(
            Word(key, line.start() + m.start(), line.start() + m.end(), i == 0, i == len(keyed) - 1, cut)
            for i, (m, key) in enumerate(keyed)
        )
    return found


def same(values: Iterable[str]) -> str:
    """The one value every item of `values` is, when it is not empty; else empty."""
    distinct = set(values)
    return distinct.pop() if len(distinct) == 1 else ""


def continues(stated: str, name: str) -> bool:
    """Whether the stated name begins with `name`, word by word, folded (`strings.fold`)."""
    keys, start = _keys(stated), _keys(name)
    return bool(start) and keys[: len(start)] == start


def _keys(text: str) -> list[str]:
    return [key for m in _TOKEN.finditer(text) if (key := fold(m.group()))]
