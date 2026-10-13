"""Header minimization by replay (SPEC-09 §4.6, ARCHITECTURE §7.2 step 2: "headers proven necessary by replay").

A recipe starts with `Accept: application/json` alone. When its replay does not reproduce every sample page, the
headers the browser sent with the endpoint request are added one at a time, in the order sent, and the first whose
addition makes the replay pass is kept; the others are dropped. So a kept header is one the replay was shown to need.

Some captured headers are never sent: the ones the client sets itself, credentials, values that look like tokens and
values that differ between sample pages (a recipe's header is a constant, or the page URL as `{page_url}`). When the
replay needs one of those, or more than one added header, the recipe is not learnable and the site stays on the
browser rung (§2: cookie handoff, tokens and signed requests are §22).
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import ValidationError

from crawlerai.config_ir.api_recipe.model import CLIENT_FIELDS, CREDENTIAL_FIELDS, PAGE_URL, RequestSpec
from crawlerai.config_ir.api_recipe.replay import Replay, ReplayPage, reproduces
from crawlerai.schemas.types import SchemaDef

# RFC 8259 §11: the JSON media type, the one header a recipe starts with.
_ACCEPT: Final = {"Accept": "application/json"}
# A value looks like a token when one of its items (RFC 9110 §5.6.1, §5.6.6: items split at commas, parameters at
# semicolons, words at whitespace; RFC 7515 §7.1: the parts of a JWS compact serialization split at dots) is 20 or more
# characters of one base64 alphabet (RFC 4648 §4 standard, §5 URL- and filename-safe; hex, §8, is in both), padding
# allowed.
_ITEM_SEPARATORS: Final = re.compile(r"[\s,;.]+")
_TOKEN: Final = re.compile(r"(?:[A-Za-z0-9+/]{20,}|[A-Za-z0-9_-]{20,})={0,2}")
_NO_SINGLE_HEADER: Final = "no single captured header makes the replay reproduce the sample values"


@dataclass(frozen=True)
class Proven:
    """The spec with the headers its replay was shown to need; `headers_tried` counts the captured headers replayed."""

    spec: RequestSpec
    headers_tried: int


@dataclass(frozen=True)
class NotLearnable:
    """No header set the recipe may keep makes the replay pass; `reason` is the learning job's diagnostic."""

    reason: str
    headers_tried: int


async def minimize(
    spec: RequestSpec, fields: Mapping[str, str], pages: Sequence[ReplayPage], schema: SchemaDef, replay: Replay
) -> Proven | NotLearnable:
    """The smallest header set (§4.6) with which replaying `spec` reproduces the `fields` map on every page of
    `pages`; their captured requests give the headers to try, in the order the first page's request sent them."""
    base = _with_headers(spec, _ACCEPT)
    if base is not None and await _passes(base, fields, pages, schema, replay):
        return Proven(base, 0)
    candidates, withheld = _candidates(pages)
    for tried, (name, value) in enumerate(candidates, start=1):
        # RFC 9110 §5.1: field names are case-insensitive; a captured Accept replaces the recipe's.
        trial = _with_headers(spec, {name: value} if name.lower() == "accept" else {**_ACCEPT, name: value})
        if trial is not None and await _passes(trial, fields, pages, schema, replay):
            return Proven(trial, tried)
    if withheld:
        return NotLearnable(
            "the replay needs a header a recipe never keeps (a credential, a token or a per-page value): "
            + ", ".join(withheld),
            len(candidates),
        )
    return NotLearnable(_NO_SINGLE_HEADER, len(candidates))


async def _passes(
    spec: RequestSpec, fields: Mapping[str, str], pages: Sequence[ReplayPage], schema: SchemaDef, replay: Replay
) -> bool:
    for page in pages:
        if not await reproduces(spec, fields, page, schema, replay):
            return False
    return True


def _with_headers(spec: RequestSpec, headers: dict[str, str]) -> RequestSpec | None:
    """`spec` with `headers`; `None` when a captured value is not one a recipe can hold (a brace, RFC 6570)."""
    try:
        return RequestSpec.model_validate({**spec.model_dump(), "headers": headers})
    except ValidationError:
        return None


def _candidates(pages: Sequence[ReplayPage]) -> tuple[list[tuple[str, str]], list[str]]:
    """The captured headers to try, as (name, recipe value), and the names of those never sent."""
    candidates: list[tuple[str, str]] = []
    withheld: list[str] = []
    seen: set[str] = set()
    for name, _ in pages[0].sample.request.headers if pages else ():
        key = name.lower()
        # RFC 9113 §8.3: a name starting with `:` is an HTTP/2 pseudo-header, not a field.
        if key in seen or key in CLIENT_FIELDS or key.startswith(":"):
            continue
        seen.add(key)
        value = _constant(key, pages)
        if value is None or key in CREDENTIAL_FIELDS or _token_like(value):
            withheld.append(name)
        else:
            candidates.append((name, value))
    return candidates, withheld


def _constant(key: str, pages: Sequence[ReplayPage]) -> str | None:
    """The field's value on every page, with the page's own URL written `{page_url}`; `None` when it differs."""
    values = {_recipe_value(key, page) for page in pages}
    return values.pop() if len(values) == 1 else None


def _recipe_value(key: str, page: ReplayPage) -> str | None:
    value = next((v for name, v in page.sample.request.headers if name.lower() == key), None)
    return f"{{{PAGE_URL}}}" if value == page.sample.page_url else value


def _token_like(value: str) -> bool:
    return any(_TOKEN.fullmatch(item) for item in _ITEM_SEPARATORS.split(value))
