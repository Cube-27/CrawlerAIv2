"""Header minimization by replay (adapters spec: "headers proven necessary by replay").

A recipe starts with `Accept: application/json` alone. When its replay does not reproduce every sample page, the
headers the browser sent with the endpoint request are added one at a time, in the order sent, and the first whose
addition makes the replay pass is kept; the others are dropped. So a kept header is one the replay was shown to need.

Some captured headers are never sent: the ones the client sets itself, credentials, values that look like tokens and
values that differ between sample pages (a recipe's header is a constant, or the page URL as `{page_url}`). When the
replay needs one of those, or more than one added header, the recipe is not learnable and the site stays on the
browser rung (§2: cookie handoff, tokens and signed requests are §22).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import ValidationError

from crawlerai.config_ir.api_recipe.model import CLIENT_FIELDS, CREDENTIAL_FIELDS, PAGE_URL, RequestSpec, token_like
from crawlerai.config_ir.api_recipe.replay import Replay, ReplayPage, reproduces
from crawlerai.schemas.types import SchemaDef

# RFC 8259 §11: the JSON media type, the one header a recipe starts with.
_ACCEPT: Final = {"Accept": "application/json"}
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
        if value is None or key in CREDENTIAL_FIELDS or token_like(value):
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
