"""What every type normalizer shares (SPEC-04 §4.3, ARCHITECTURE §9): the result union, the context and the
normalizer signature.

The type modules import this module and nothing else from `crawlerai.normalize`; the dispatcher
(`crawlerai.normalize.dispatch`) imports the type modules. `.importlinter` keeps both directions.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, JsonValue

from crawlerai.schemas.types import FieldSpec


@dataclass(frozen=True, slots=True)
class Ok:
    """The normalized value, in the type's JSON form (the form labels and records store)."""

    value: JsonValue


@dataclass(frozen=True, slots=True)
class Ambiguous:
    """The input reads as more than one value and the context does not settle which (C7: decline, never guess)."""

    reason: str
    options: tuple[JsonValue, ...]


@dataclass(frozen=True, slots=True)
class Invalid:
    """The input is not a value of the type."""

    reason: str


NormalizeResult = Ok | Ambiguous | Invalid

# A string from the DOM or an LLM, or a JSON value from a structured source (JSON-LD, an API). Each normalizer
# documents the forms it accepts.
Raw = JsonValue


# Unicode general category Cs (U+D800 to U+DFFF): a lone surrogate is not a Unicode scalar value, so no UTF-8 string
# holds it. JSON text may still carry one as an escape (RFC 8259 §8.2), and `json.loads` keeps it.
_SURROGATE = re.compile(r"[\ud800-\udfff]")


def has_surrogate(s: str) -> bool:
    """Whether `s` holds a lone surrogate; such a string is not text, and a normalizer declines it."""
    return _SURROGATE.search(s) is not None


class Context(BaseModel):
    """Evidence from the page and the request, and nothing else (§9, C7): never a host table, never a default.

    `base_url` and `page_url` resolve and check URLs: the document base URL (`<base href>` resolved against the final
    URL, else the final URL; HTML Standard, "document base URL") and the final URL itself. Either is `None` when the
    value does not come from a page.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    html_lang: str | None = None
    og_locale: str | None = None
    hreflang: tuple[str, ...] = ()
    page_currencies: tuple[str, ...] = ()  # ISO 4217 codes stated in the page's structured data
    cctld_territory: str | None = None  # from the URL's ccTLD through CLDR territory data; None for gTLDs
    request_locale: str | None = None  # the caller's hint
    captured_at: datetime  # for relative dates
    base_url: str | None = None
    page_url: str | None = None


class Normalizer(Protocol):
    """One field type's normalizer: a pure function of its arguments (no I/O, no clock). It never raises on bad
    input; a `spec` of a type it does not handle is a programming error and raises `TypeError` (§4.7)."""

    def __call__(self, raw: Raw, spec: FieldSpec, ctx: Context, /) -> NormalizeResult: ...
