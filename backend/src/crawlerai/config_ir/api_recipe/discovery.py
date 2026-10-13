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
from itertools import chain, permutations
from typing import Final, TypeGuard

from pydantic import JsonValue

from crawlerai.collect import json_doc
from crawlerai.config_ir.api_recipe.binding import CapturedRequest, UrlShape, url_shape
from crawlerai.config_ir.api_recipe.model import joined_raw, map_paths
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
    pages = [_bodies(sample, schema) for sample in samples]
    candidates: list[EndpointCandidate] = []
    for key in pages[0]:
        found = [page.get(key) for page in pages]
        bodies = [body for body in found if body is not None]
        if len(bodies) == len(pages) and (candidate := _candidate(bodies, schema)) is not None:
            candidates.append(candidate)
    return sorted(candidates, key=lambda candidate: -candidate.score)


@dataclass(frozen=True)
class _Reading:
    """A value a body offers a field: the map path that gives it and the raw value."""

    path: str
    raw: Scalar


@dataclass(frozen=True)
class _Body:
    request: CapturedRequest
    hits: dict[str, list[str]]  # field -> the map paths that read its published value
    score: int


def _candidate(bodies: list[_Body], schema: SchemaDef) -> EndpointCandidate | None:
    paths: dict[str, str] = {}
    for name in schema.fields:
        shared = [
            path for path in bodies[0].hits.get(name, []) if all(path in body.hits.get(name, []) for body in bodies)
        ]
        if shared:
            paths[name] = shared[0]
    if not required_fields(schema) & paths.keys():
        return None
    return EndpointCandidate(
        requests=tuple(body.request for body in bodies), map=paths, score=sum(body.score for body in bodies)
    )


def _bodies(sample: DiscoverySample, schema: SchemaDef) -> dict[_EndpointKey, _Body]:
    """The page's readable bodies, the best-scoring one per endpoint, in capture order of first appearance."""
    page = ParsedPage.of(sample.bundle)
    best: dict[_EndpointKey, _Body] = {}
    for entry, data in zip(sample.bundle.manifest.network_bodies, sample.bundle.network, strict=True):
        request, document = _readable(entry, data)
        if request is None:
            continue
        body = _scored(request, document, page, sample, schema)
        key = _key(request)
        if key not in best or body.score > best[key].score:
            best[key] = body
    return best


def _readable(entry: NetworkBody, data: bytes) -> tuple[CapturedRequest, JsonValue] | tuple[None, None]:
    if entry.method is None or entry.status not in _SUCCESS:
        return None, None
    try:
        document = json_doc.parse(data.decode("utf-8"))
    except ValueError:  # UnicodeDecodeError is a ValueError
        return None, None
    return CapturedRequest(entry.method.upper(), entry.url, entry.request_body), document


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
    return tuple(
        sorted({path for path, value in _nodes(document, wildcard=True) if not isinstance(value, (dict, list))})
    )


def _scored(
    request: CapturedRequest, document: JsonValue, page: ParsedPage, sample: DiscoverySample, schema: SchemaDef
) -> _Body:
    leaves = [_Reading(path, raw) for path, raw in json_doc.scalars(document)]
    hits = {
        name: paths
        for name, spec in schema.fields.items()
        if name in sample.values and (paths := _hits(document, leaves, sample.values[name], spec, sample.ctx))
    }
    matched = required_fields(schema) & hits.keys()
    used = {leaf for name in matched for path in hits[name] for leaf in map_paths(path)}
    visible = [r for r in leaves if r.path not in used and page.visible_values.visible(str(r.raw))]
    typed = [
        name for name, spec in schema.fields.items() if name not in matched and _any_typed(visible, spec, sample.ctx)
    ]
    return _Body(request, hits, len(matched) + len(typed))


def _hits(document: JsonValue, leaves: list[_Reading], value: JsonValue, spec: FieldSpec, ctx: Context) -> list[str]:
    """The map paths, in document order, whose reading normalizes to a value `equal` to `value`."""
    readings: Iterator[_Reading] = iter(leaves)
    if spec.type is FieldType.MONEY:
        readings = chain(leaves, _member_pairs(document))
    return [reading.path for reading in readings if _reads(reading.raw, value, spec, ctx)]


def _reads(raw: Scalar, value: JsonValue, spec: FieldSpec, ctx: Context) -> bool:
    result = normalize(raw, spec, ctx)
    return isinstance(result, Ok) and equal(result.value, value, spec)


def _any_typed(readings: list[_Reading], spec: FieldSpec, ctx: Context) -> bool:
    return any(isinstance(normalize(reading.raw, spec, ctx), Ok) for reading in readings)


def _member_pairs(document: JsonValue) -> Iterator[_Reading]:
    """Every ordered pair of distinct scalar members of one object, joined (`+`, §4.2)."""
    for path, value in _nodes(document):
        if isinstance(value, dict):
            scalars = [(json_doc.member(path, key), child) for key, child in value.items() if _is_scalar(child)]
            for (first, a), (second, b) in permutations(scalars, 2):
                yield _Reading(f"{first}+{second}", joined_raw([a, b]))


def _nodes(document: JsonValue, *, wildcard: bool = False) -> Iterator[tuple[str, JsonValue]]:
    """Every node of `document` with its normalized path, in document order; with `wildcard`, array indices are
    written `[*]`. Iterative, like `json_doc.scalars`."""
    stack: list[tuple[str, JsonValue]] = [(json_doc.ROOT, document)]
    while stack:
        path, value = stack.pop()
        yield path, value
        children: list[tuple[str, JsonValue]] = []
        if isinstance(value, dict):
            children = [(json_doc.member(path, key), child) for key, child in value.items()]
        elif isinstance(value, list):
            children = [(f"{path}[{'*' if wildcard else i}]", child) for i, child in enumerate(value)]
        stack.extend(reversed(children))


def _is_scalar(value: JsonValue) -> TypeGuard[Scalar]:
    return isinstance(value, (str, int, float)) and not isinstance(value, bool)
