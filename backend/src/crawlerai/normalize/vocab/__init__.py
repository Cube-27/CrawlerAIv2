"""Vocabularies for the normalizers (SPEC-04 §4.1, §4.4, ARCHITECTURE §9, C4): the shipped data, its tokenizer and
its matcher.

Two kinds, each a directory with a `JUSTIFICATION.md` that names its source:
- `schema/<Enumeration>.json`: a schema.org enumeration's member names, as a JSON array.
- `type/<name>/<language>.json`: a language-tagged type vocabulary, a JSON object from code to its phrases. Each
  phrase is stored in token form (`tokens`), so the file reads as what is matched.

Everything is read once, at import, so a normalizer that uses it stays a pure function.
"""

import json
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable

from crawlerai.normalize.base import Context

Tokens = tuple[str, ...]


def tokens(text: str) -> Tokens:
    """`text` as a sequence of words (SPEC-04 §4.4): NFKC, casefold, split on every character that is not a letter.

    A word is a run of Unicode letters (general category L) and marks (M): marks continue a word in scripts that write
    vowels as combining characters (UAX #29 treats them as part of the preceding letter). NFKC (UAX #15) folds
    compatibility forms such as fullwidth letters; `casefold` is Unicode default case folding.
    """
    words: list[str] = []
    word: list[str] = []
    for char in unicodedata.normalize("NFKC", text).casefold():
        if unicodedata.category(char)[0] in "LM":
            word.append(char)
        elif word:
            words.append("".join(word))
            word = []
    if word:
        words.append("".join(word))
    return tuple(words)


@dataclass(frozen=True, slots=True)
class Entries:
    """One language's phrases of one type vocabulary, each with its code."""

    phrases: Mapping[str, str]

    @classmethod
    def of(cls, codes: Mapping[str, Iterable[str]]) -> "Entries":
        """Entries from code → phrases, the file form. A phrase must be in token form, so it matches exactly as
        written, and belongs to one code: a phrase under two codes would make every input that holds it ambiguous."""
        phrases: dict[str, str] = {}
        for code, listed in codes.items():
            for phrase in listed:
                if not phrase or " ".join(tokens(phrase)) != phrase:
                    raise ValueError(f"vocabulary phrase {phrase!r} is not in token form")
                if phrases.setdefault(phrase, code) != code:
                    raise ValueError(f"vocabulary phrase {phrase!r} is listed under two codes")
        return cls(phrases)

    def find(self, words: Tokens) -> frozenset[str]:
        """The codes whose phrase is a contiguous run of `words` (SPEC-04 §4.4: token sequences, never substrings).

        Where one match lies inside a longer one, the longer wins ("longest match"); matches at separate places all
        count, so two members in one input both show.
        """
        matches: list[tuple[int, int, str]] = []
        for phrase, code in self.phrases.items():
            needle = tuple(phrase.split(" "))
            n = len(needle)
            matches.extend((i, i + n, code) for i in range(len(words) - n + 1) if words[i : i + n] == needle)
        return frozenset(
            code
            for start, end, code in matches
            if not any(s <= start and end <= e and e - s > end - start for s, e, _ in matches)
        )


def schema_members(enumeration: str) -> frozenset[str] | None:
    """The member names of a schema.org enumeration, or `None` when none is shipped."""
    return _SCHEMA.get(enumeration)


def type_vocabulary(name: str) -> Mapping[str, Entries] | None:
    """A type vocabulary's entries by language (BCP 47 primary subtag), or `None` when none is shipped."""
    return _TYPE.get(name)


def context_languages(ctx: Context) -> frozenset[str]:
    """The languages the page states for itself, as lowercase primary language subtags (RFC 5646 §2.2.1).

    `html_lang` is a BCP 47 tag (HTML Standard, the `lang` attribute); `og_locale` is `language_TERRITORY` (Open Graph
    protocol); `request_locale` is the caller's tag. `hreflang` names alternate pages, not this one, so it is not read.
    """
    tags = (ctx.html_lang, ctx.og_locale, ctx.request_locale)
    return frozenset(tag.strip().replace("_", "-").split("-")[0].lower() for tag in tags if tag and tag.strip())


def _load_schema(directory: Traversable) -> dict[str, frozenset[str]]:
    return {
        e.name.removesuffix(".json"): frozenset(json.loads(e.read_text(encoding="utf-8")))
        for e in _json_files(directory)
    }


def _load_type(directory: Traversable) -> dict[str, dict[str, Entries]]:
    return {
        vocabulary.name: {
            e.name.removesuffix(".json"): Entries.of(json.loads(e.read_text(encoding="utf-8")))
            for e in _json_files(vocabulary)
        }
        for vocabulary in directory.iterdir()
        if vocabulary.is_dir()
    }


def _json_files(directory: Traversable) -> Iterable[Traversable]:
    return sorted((e for e in directory.iterdir() if e.name.endswith(".json")), key=lambda e: e.name)


_ROOT = files(__name__)
_SCHEMA = _load_schema(_ROOT / "schema")
_TYPE = _load_type(_ROOT / "type")
