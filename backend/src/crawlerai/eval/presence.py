"""Whether a capture shows a value: the golden-set report's coverage ceiling and disagreement kinds, and label
re-keying (evaluation spec, "Presence, disagreement kinds and cost", "Label re-keying").

A value is looked for as written in the capture's document: its markup, attribute values and inline JSON as well as
its text, with character references decoded (HTML Standard §13.5), JSON's escaped solidus read as `/` (RFC 8259 §7),
case folded and white space collapsed. Only values with a written form are looked for: strings, a URL's path, a
location's text, a list's items. A number, an amount or a date can be written in too many forms to search, so their
presence is unknown (`None`), never guessed.
"""

import html
import re
from urllib.parse import unquote, urlsplit

from pydantic import JsonValue

from crawlerai.schemas.types import FieldSpec, FieldType

# A value this short occurs anywhere by chance, so finding it says nothing.
_MIN_CHARS = 3
# A long text is looked for by its opening: markup inside it (paragraphs, inline elements) splits the rest.
_OPENING_CHARS = 60
_TAG = re.compile(r"<[^>]*>")
_SPACE = re.compile(r"\s+")
_SEARCHED_AS_TEXT = frozenset({FieldType.TEXT, FieldType.LONG_TEXT, FieldType.IDENTIFIER})
_SEARCHED_AS_URL = frozenset({FieldType.URL, FieldType.IMAGE_URL})


class Capture:
    """A capture's document, searchable for written values."""

    def __init__(self, document: str) -> None:
        unescaped = html.unescape(document.replace("\\/", "/"))
        # The markup as written, and its text with the tags taken out, so a value split by inline markup is found.
        self._haystack = f"{_folded(unescaped)}\n{_folded(_TAG.sub(' ', unescaped))}"

    def shows_text(self, text: str) -> bool | None:
        folded = _folded(text)
        if len(folded) < _MIN_CHARS:
            return None
        return folded[:_OPENING_CHARS] in self._haystack

    def shows_url(self, url: str) -> bool | None:
        """Whether the capture names the URL's path (as written or percent-decoded); a root path says nothing."""
        try:
            path = urlsplit(url).path
        except ValueError:
            return None
        if len(path.strip("/")) < _MIN_CHARS:
            return None
        return any(form.casefold() in self._haystack for form in {path, unquote(path)})

    def shows(self, value: JsonValue, spec: FieldSpec) -> bool | None:
        """Whether the capture shows `value`, a normalized value of `spec`'s type; `None` when unknown."""
        if spec.type is FieldType.LIST and spec.item is not None and isinstance(value, list):
            found = [self.shows(item, spec.item) for item in value]
            return True if True in found else (False if False in found else None)
        if spec.type in _SEARCHED_AS_TEXT and isinstance(value, str):
            return self.shows_text(value)
        if spec.type in _SEARCHED_AS_URL and isinstance(value, str):
            return self.shows_url(value)
        if spec.type is FieldType.LOCATION and isinstance(value, dict) and isinstance(value.get("text"), str):
            return self.shows_text(str(value["text"]))
        return None


def _folded(text: str) -> str:
    return _SPACE.sub(" ", text.casefold()).strip()
