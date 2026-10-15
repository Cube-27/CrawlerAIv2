"""The locator format (SPEC-05 §4.3): where on the capture a candidate's raw value came from, as
`<scheme>:<address>`. Collectors write it, the pipeline re-checks `text:` locators (INV-12) and induction (SPEC-08)
reads it, so every locator a candidate carries parses here (INV-22).

The address parts are separated by `:`; the last part takes the rest of the string, since XPath, JSONPath, CSS
selectors and meta property names (`og:title`) may hold `:` themselves. `js_state` has two open-ended parts and is
split after the first `script[n]` step, the step `ParsedPage` ends a script's path with.
"""

import re
from typing import Annotated, Literal, NamedTuple, cast

from pydantic import AfterValidator

from crawlerai.schemas.types import NAME_PATTERN

Scheme = Literal["jsonld", "microdata", "meta", "js_state", "xhr", "adapter", "api", "config", "text"]

# An index into a list the capture holds (script blocks, network bodies, config steps): ASCII digits without a leading
# zero, so that each index has one spelling.
_INDEX = r"(0|[1-9][0-9]*)"
# RFC 9535 §2.2: a JSONPath query starts with the root identifier `$`.
_JSONPATH = r"(\$.*)"
# XPath 1.0 §2: an absolute location path starts with `/`.
_XPATH = r"(/.+)"
# A name the engine assigned (an adapter, an API recipe id): no `:` and no whitespace.
_ASSIGNED_NAME = r"([^:\s]+)"
_INDEXED_JSONPATH = re.compile(rf"{_INDEX}:{_JSONPATH}", re.DOTALL)
_NAMED_JSONPATH = re.compile(rf"{_ASSIGNED_NAME}:{_JSONPATH}", re.DOTALL)

_ADDRESS: dict[str, re.Pattern[str]] = {
    # The nth `application/ld+json` block, then a path in the block as written (SPEC-05 §4.3).
    "jsonld": _INDEXED_JSONPATH,
    # The element carrying the `itemprop`.
    "microdata": re.compile(_XPATH, re.DOTALL),
    # HTML Standard, the meta element: a `name` or `property` value; OpenGraph names hold `:` but no whitespace.
    "meta": re.compile(r"(\S+)"),
    "js_state": re.compile(rf"(/.*?script\[[1-9][0-9]*\]):{_JSONPATH}", re.DOTALL),
    # The nth captured network body in the bundle.
    "xhr": _INDEXED_JSONPATH,
    "adapter": _NAMED_JSONPATH,
    "api": _NAMED_JSONPATH,
    # A schema field name, the step index, then the step's selector.
    "config": re.compile(rf"({NAME_PATTERN}):{_INDEX}:(.+)", re.DOTALL),
    # `[start, end)` character offsets into the cleaned text.
    "text": re.compile(rf"{_INDEX}-{_INDEX}"),
}


class InvalidLocator(ValueError):
    pass


class Locator(NamedTuple):
    scheme: Scheme
    parts: tuple[str, ...]

    def __str__(self) -> str:
        separator = "-" if self.scheme == "text" else ":"
        return f"{self.scheme}:{separator.join(self.parts)}"


def parse_locator(text: str) -> Locator:
    scheme, _, address = text.partition(":")
    pattern = _ADDRESS.get(scheme)
    match = pattern.fullmatch(address) if pattern is not None else None
    if match is None:
        raise InvalidLocator(f"not a locator: {text!r}")
    locator = Locator(cast(Scheme, scheme), match.groups())
    if scheme == "text" and int(locator.parts[0]) >= int(locator.parts[1]):
        raise InvalidLocator(f"empty or reversed text span: {text!r}")  # an empty span holds no value
    return locator


def format_locator(scheme: Scheme, *parts: str) -> str:
    """The locator of `parts` under `scheme`; raises `InvalidLocator` unless it parses back to them."""
    text = str(Locator(scheme, parts))
    if parse_locator(text).parts != parts:
        raise InvalidLocator(f"parts do not fit the {scheme} address: {parts!r}")
    return text


def _check_locator(text: str) -> str:
    parse_locator(text)
    return text


# A string in the locator format, checked when a model is built (INV-22).
LocatorText = Annotated[str, AfterValidator(_check_locator)]
