"""API discovery (SPEC-09 §4.3, ARCHITECTURE §7.2 step 1): from the learning sample's browser captures, the endpoints
whose JSON responses carry the page's published values on every sample page, each with a JSONPath per field.

A captured body is read only when the capture recorded the method of the request behind it and the response was a
success (RFC 9110 §15.3): a recipe can only replay such a request. Bodies group into endpoints by
request method, URL shape (`binding.url_shape`: path segments may vary, they are what binding parameterizes) and
request body shape; on each page the best-scoring body of a group stands for it.

A body scores one point per required field (§10, required groups included) whose published value is `equal` to a
reading of the body, and one per other field with a visible leaf of its type (§4.3). A reading is one scalar leaf,
or for money, two scalar members of one object joined with `+` (§4.2, atomic money). A field's map path is the first
path, in the first page's document order, that reads its value on every sample page; an endpoint is a candidate when
the map holds a required field. Candidates come best first; the first is the one a recipe is bound from (one
endpoint per config, D-0035).
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import JsonValue

from crawlerai.collect import json_doc
from crawlerai.collect.api import joined_raw, map_paths
from crawlerai.config_ir.api_recipe.binding import CapturedRequest, UrlShape, url_shape
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import equal, normalize
from crawlerai.resolve.evidence import required_fields
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, NetworkBody

Scalar = str | int | float
# (method, URL shape, request body shape): what the requests of one endpoint share across pages.
_EndpointKey = tuple[str, UrlShape, tuple[str, ...] | None]
# RFC 9110 §15.3: the 2xx class.
_SUCCESS: Final = range(200, 300)


@dataclass(frozen=True)
class DiscoverySample:
    """One sample page: its browser capture with network bodies, its published values (`record.data`) and the
    normalize context of the page."""

    bundle: CaptureBundle
    values: Mapping[str, JsonValue]
    ctx: Context


@dataclass(frozen=True)
class EndpointCandidate:
    """An endpoint found on every sample page: its request on each (in sample order, for binding), the JSONPath of
    each field it carries (a `map` entry of the recipe) and its score summed over the pages."""

    requests: tuple[CapturedRequest, ...]
    map: dict[str, str]
    score: int


def discover(samples: Sequence[DiscoverySample], schema: SchemaDef) -> list[EndpointCandidate]:
    """The candidate endpoints of `samples`, best first (by score; ties keep the first page's capture order)."""
    if not samples:
        return []
    required = required_fields(schema)
    pages = [_bodies(sample, schema, required) for sample in samples]
    candidates: list[EndpointCandidate] = []
    for key in pages[0]:
        if all(key in page for page in pages[1:]):
            candidate = _candidate([page[key] for page in pages], schema, required)
            if candidate is not None:
                candidates.append(candidate)
    return sorted(candidates, key=lambda candidate: -candidate.score)


def endpoint_request(bundle: CaptureBundle, endpoint: EndpointCandidate) -> CapturedRequest | None:
    """The request to `endpoint` a capture holds a readable answer to, the first in capture order; `None` when it holds
    none. Held-out validation reads the captures that hold one (§4.7)."""
    key = _key(endpoint.requests[0])
    for entry, data in zip(bundle.manifest.network_bodies, bundle.network, strict=True):
        readable = _readable(entry, data)
        if readable is not None and _key(readable[0]) == key:
            return readable[0]
    return None


@dataclass(frozen=True)
class _Reading:
    """A value a body offers a field: the map path that gives it and the raw value."""

    path: str
    raw: Scalar


# The readings of a body that normalize as one field's type, each with its normalized value.
_Normalized = list[tuple[_Reading, JsonValue]]


@dataclass(frozen=True)
class _Body:
    request: CapturedRequest
    hits: dict[str, dict[str, None]]  # field -> the map paths that read its published value, in document order
    score: int


def _candidate(bodies: list[_Body], schema: SchemaDef, required: frozenset[str]) -> EndpointCandidate | None:
    paths: dict[str, str] = {}
    for name in schema.fields:
        shared = [
            path for path in bodies[0].hits.get(name, {}) if all(path in body.hits.get(name, {}) for body in bodies)
        ]
        if shared:
            paths[name] = shared[0]
    if not required & paths.keys():
        return None
    return EndpointCandidate(
        requests=tuple(body.request for body in bodies), map=paths, score=sum(body.score for body in bodies)
    )


def _bodies(sample: DiscoverySample, schema: SchemaDef, required: frozenset[str]) -> dict[_EndpointKey, _Body]:
    """The page's readable bodies, the best-scoring one per endpoint, in capture order of first appearance."""
    page = ParsedPage.of(sample.bundle)
    best: dict[_EndpointKey, _Body] = {}
    for entry, data in zip(sample.bundle.manifest.network_bodies, sample.bundle.network, strict=True):
        readable = _readable(entry, data)
        if readable is None:
            continue
        request, document = readable
        body = _scored(request, document, page, sample, schema, required)
        key = _key(request)
        if key not in best or body.score > best[key].score:
            best[key] = body
    return best


def _readable(entry: NetworkBody, data: bytes) -> tuple[CapturedRequest, JsonValue] | None:
    if entry.method is None or entry.status not in _SUCCESS:
        return None
    try:
        document = json_doc.parse(data.decode("utf-8"))
    except ValueError:  # UnicodeDecodeError is a ValueError
        return None
    return CapturedRequest(entry.method.upper(), entry.url, entry.request_body, entry.request_headers or ()), document


def _key(request: CapturedRequest) -> _EndpointKey:
    return request.method, url_shape(request.url), _body_shape(request.body)


def _body_shape(body: str | None) -> tuple[str, ...] | None:
    """The paths of a JSON request body's values with every array index written `[*]`, or the body itself when it
    is not JSON: requests to one URL that send differently shaped bodies (one GraphQL URL, many queries) differ."""
    if body is None:
        return None
    try:
        document = json_doc.parse(body)
    except ValueError:
        return (body,)
    leaves = {path for path, value in json_doc.nodes(document, wildcard=True) if not isinstance(value, (dict, list))}
    return tuple(sorted(leaves))


def _scored(
    request: CapturedRequest,
    document: JsonValue,
    page: ParsedPage,
    sample: DiscoverySample,
    schema: SchemaDef,
    required: frozenset[str],
) -> _Body:
    leaves = [_Reading(path, raw) for path, raw in json_doc.scalars(document)]
    # Each leaf is normalized once per field: for equality with the published value and for the visible-type count.
    typed = {name: _normalized(leaves, spec, sample.ctx) for name, spec in schema.fields.items()}
    hits = _field_hits(typed, document, sample, schema)
    matched = required & hits.keys()
    others = [name for name in schema.fields if name not in matched]
    used = {leaf for name in matched for path in hits[name] for leaf in map_paths(path)}
    visible = {r.path for r in leaves if others and r.path not in used and page.visible_values.visible(str(r.raw))}
    shown = [name for name in others if any(reading.path in visible for reading, _ in typed[name])]
    return _Body(request, hits, len(matched) + len(shown))


def _field_hits(
    typed: Mapping[str, _Normalized], document: JsonValue, sample: DiscoverySample, schema: SchemaDef
) -> dict[str, dict[str, None]]:
    """Each published field's map paths in the body; money also reads joined member pairs."""
    money = any(spec.type is FieldType.MONEY for spec in schema.fields.values())
    pairs = list(_member_pairs(document)) if money else []
    hits: dict[str, dict[str, None]] = {}
    for name, spec in schema.fields.items():
        if name not in sample.values:
            continue
        joined = _normalized(pairs, spec, sample.ctx) if spec.type is FieldType.MONEY else []
        if paths := _hits(typed[name] + joined, sample.values[name], spec):
            hits[name] = paths
    return hits


def _normalized(readings: list[_Reading], spec: FieldSpec, ctx: Context) -> _Normalized:
    return [
        (reading, result.value) for reading in readings if isinstance(result := normalize(reading.raw, spec, ctx), Ok)
    ]


def _hits(readings: _Normalized, value: JsonValue, spec: FieldSpec) -> dict[str, None]:
    """The map paths, in document order, whose reading is `equal` to `value`."""
    return dict.fromkeys(reading.path for reading, normalized in readings if equal(normalized, value, spec))


def _member_pairs(document: JsonValue) -> Iterator[_Reading]:
    """The ordered pairs of scalar members of one object that may join into one money value (`+`, §4.2), in
    document order: one member holds a digit and the other none.

    SPEC-04 money text reading (`normalize/money.py`, `_AMOUNT_RUN`): a money value holds exactly one run of amount
    digits, so a joined pair is an amount member and a currency member without digits. Two digit-free members state
    no amount, and two amounts are two runs (a range or a list). So an object gives amounts x digit-free members
    pairs, not the square of its size.
    """
    for path, value in json_doc.nodes(document):
        if isinstance(value, dict):
            members = [(json_doc.member(path, key), child) for key, child in value.items() if json_doc.is_scalar(child)]
            yield from _amount_pairs(members)


def _amount_pairs(members: list[tuple[str, Scalar]]) -> Iterator[_Reading]:
    amounts = [member for member in members if _has_digit(member[1])]
    plain = [member for member in members if not _has_digit(member[1])]
    for first, a in members:
        for second, b in plain if _has_digit(a) else amounts:
            yield _Reading(f"{first}+{second}", joined_raw([a, b]))


def _has_digit(value: Scalar) -> bool:
    return not isinstance(value, str) or any(c.isdigit() for c in value)
