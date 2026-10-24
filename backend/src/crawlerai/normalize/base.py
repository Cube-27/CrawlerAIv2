"""What every type normalizer shares: the result union, the context and the
normalizer signature.

The type modules import this module and nothing else from `crawlerai.normalize`; the dispatcher
(`crawlerai.normalize.dispatch`) imports the type modules. `.importlinter` keeps both directions.
"""

import html
import re
from collections.abc import Hashable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, JsonValue

from crawlerai.schemas.types import FieldSpec

# Money: where a value's currency came from when the value itself does not state it. `page` is a
# page-level declaration, `locale` the page's language and region narrowing a shared sign, `url` the territory its URL
# names (a locale path segment, a country subdomain or the ccTLD), `unknown` none (the currency is null). Weakest last.
Basis = Literal["page", "locale", "url", "symbol", "unknown"]
BASES: tuple[Basis, ...] = ("page", "locale", "url", "symbol", "unknown")


@dataclass(frozen=True, slots=True)
class Ok:
    """The normalized value, in the type's JSON form (the form labels and records store).

    `reasons` reports the parts of a list or object that declined and were dropped, each as
    `<path>: <reason>` (`[2]: empty`, `address.locality: no_match`); a scalar has none. `basis` is the weaker evidence
    a part of the value rests on (`Basis`), `None` when the raw value states it all. `checked` is whether the raw value
    shows the type's checked syntax, so that its normalizing is evidence of the type: money text
    without a currency sign is only a number. `stated` is the value as the page states it, when that differs from
    `value` (a URL as written, relative or not in canonical form): the published form, while `value` is what equality,
    identity and resolution read; `None` when `value` is as stated.
    """

    value: JsonValue
    reasons: tuple[str, ...] = ()
    basis: Basis | None = None
    checked: bool = True
    stated: JsonValue = None

    @property
    def published(self) -> JsonValue:
        """The value as it publishes: `stated` when the page states it otherwise, else `value`."""
        return self.value if self.stated is None else self.stated


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


# HTML Standard §13.1.4 character references, each closed by `;`: named, decimal and hexadecimal (any leading zeros),
# its `&` itself written escaped any number of times (`&amp;amp;`, `&#38;#39;`).
_REFERENCE = re.compile(
    r"&(?:amp;|#0*38;|#[xX]0*26;)*([A-Za-z][A-Za-z\d]{1,31};|#0*\d{1,7};|#[xX]0*[\dA-Fa-f]{1,6};)", re.ASCII
)


def decoded_references(s: str) -> str:
    """`s` with its character references (HTML Standard §13.1.4) decoded, a reference whose `&` is itself escaped
    (`&amp;amp;`, `&amp;#39;`) as the character it finally names: that is text its producer HTML-escaped twice (once
    more as it wrote the value into a script or an attribute), and the page shows it decoded. Only references closed by
    `;` are read, so a URL's query (`?a=1&reg=2`) is never taken for one. One pass over `s`."""
    return _REFERENCE.sub(lambda m: html.unescape("&" + m.group(1)), s)


class Context(BaseModel):
    """Evidence from the page and the request, and nothing else (C7): never a host table, never a default.

    `base_url` and `page_url` resolve and check URLs: the document base URL (`<base href>` resolved against the final
    URL, else the final URL; HTML Standard, "document base URL") and the final URL itself. Either is `None` when the
    value does not come from a page. `request_url` is the URL the page was requested at, which the money rules read
    beside the final URL for the territory it names.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    html_lang: str | None = None
    og_locale: str | None = None
    hreflang: tuple[str, ...] = ()
    page_currencies: tuple[str, ...] = ()  # ISO 4217 codes stated in the page's structured data
    # ISO 4217 codes the page declares page-wide in its own name (OGP, its platform's documented currency global), and
    # those its state documents hold in anonymous members, which a third party's script config can also hold.
    declared_currencies: tuple[str, ...] = ()
    state_currencies: tuple[str, ...] = ()
    # The CLDR decimal symbol every unambiguous amount the page writes uses (`page_convention` of `collect.currencies`),
    # which settles the reading of an amount the conventions read differently (`numbers.readings`); None when they
    # do not agree or the page writes none.
    page_convention: str | None = None
    in_language: tuple[str, ...] = ()  # schema.org `inLanguage` written in the page's JSON-LD, as written
    content_language: tuple[str, ...] = ()  # RFC 9110 §8.5 Content-Language and its HTML pragma, as written
    cctld_territory: str | None = None  # from the URL's ccTLD through CLDR territory data; None for gTLDs
    request_locale: str | None = None  # the caller's hint
    captured_at: datetime  # for relative dates
    base_url: str | None = None
    page_url: str | None = None
    request_url: str | None = None


class Normalizer(Protocol):
    """One field type's normalizer: a pure function of its arguments (no I/O, no clock). It never raises on bad
    input; a `spec` of a type it does not handle is a programming error and raises `TypeError`."""

    def __call__(self, raw: Raw, spec: FieldSpec, ctx: Context, /) -> NormalizeResult: ...


class Equality(Protocol):
    """One field type's equality of two normalized values, used by the resolver's agreement rule.
    It is reflexive and symmetric for every JSON value, and never raises on values of another shape."""

    def __call__(self, a: JsonValue, b: JsonValue, spec: FieldSpec, /) -> bool: ...


class EqualityKey(Protocol):
    """One field type's equality as a key: `equal(a, b)` exactly when the keys of `a` and `b` are
    equal, so values group by hashing instead of comparing every pair. Only a type whose equality is an equivalence
    relation has one (location's is not transitive)."""

    def __call__(self, value: JsonValue, spec: FieldSpec, /) -> Hashable: ...


def frozen(value: JsonValue) -> Hashable:
    """A hashable stand-in for a JSON value, equal to another's exactly when the values are `==` (lists as tuples,
    objects as sets of their members)."""
    if isinstance(value, list):
        return tuple(frozen(v) for v in value)
    if isinstance(value, dict):
        return frozenset((k, frozen(v)) for k, v in value.items())
    return value


def raw_key(value: JsonValue) -> Hashable:
    """The key of a value that only equals itself: tagged, so it never meets a type's own key form."""
    return ("raw", frozen(value))
