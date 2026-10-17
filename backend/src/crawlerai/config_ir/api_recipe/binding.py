"""Parameter binding (SPEC-09 §4.4): read a recipe's parameters from a page, fill its templates with them, and find
the templates of an endpoint request from sample pages deterministically.

Values are compared and passed around percent-decoded (RFC 3986 §2.1) and encoded again where a placeholder stands,
so a value read from the page URL and one read from a JSON document mean the same thing. A binding is accepted only
when its templates reproduce the captured request of every sample page exactly; anything less is `Ambiguous`, the
case role D (§4.5) takes.
"""

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, NamedTuple
from urllib.parse import quote, unquote, urlsplit

from pydantic import JsonValue, ValidationError

from crawlerai.collect import json_doc
from crawlerai.collect.network_match import url_shape
from crawlerai.config_ir.api_recipe.model import (
    PAGE_DATA_KINDS,
    PLACEHOLDER,
    Binder,
    PageDataKind,
    RequestSpec,
    parse_binder,
)
from crawlerai.config_ir.executor import documents
from crawlerai.config_ir.portable_regex import PCRE_FLAGS
from crawlerai.content.page import ParsedPage
from crawlerai.storage.capture_bundle import HeaderList

# The page's JSON documents a `jsonld:` or `js_state:` binder reads, by kind.
PageData = Mapping[PageDataKind, JsonValue]

# RFC 3986 §3.3: a path segment holds pchar; `quote` keeps the unreserved characters, these are the rest of it.
PATH_SAFE: Final = "!$&'()*+,;=:@"
# RFC 3986 §3.4: a query holds pchar, `/` and `?`; `&`, `=` and `+` are encoded in a value because the
# application/x-www-form-urlencoded reading (WHATWG URL §5) takes them as separators or a space.
QUERY_SAFE: Final = "!$'()*,;:@/?"
_DATA_KINDS: Final[dict[str, PageDataKind]] = {"jsonld": "jsonld", "js_state": "js_state"}


@dataclass(frozen=True)
class CapturedRequest:
    method: str
    url: str
    body: str | None = None
    headers: HeaderList = ()  # as the browser sent them, in order; header minimization (§4.6) replays them


@dataclass(frozen=True)
class Sample:
    """One sample page: its URL, the endpoint request the browser made for it, and its JSON documents."""

    page_url: str
    request: CapturedRequest
    page_data: PageData = field(default_factory=dict)


@dataclass(frozen=True)
class Ambiguous:
    """No deterministic binding reproduces every sample; `reason` is the learning job's diagnostic."""

    reason: str


# --- reading and filling ---------------------------------------------------------------------------------------------


def resolve(binder: Binder, page_url: str, page_data: PageData) -> str | None:
    """The value `binder` reads from the page, decoded; `None` when the page has no non-empty value there."""
    kind = _DATA_KINDS.get(binder.kind)
    value = _url_value(binder, _Url.split(page_url)) if kind is None else _data_value(kind, binder.arg, page_data)
    return value or None


def resolve_params(spec: RequestSpec, page_url: str, page_data: PageData) -> dict[str, str] | None:
    """Every parameter of `spec` read from the page; `None` when one has no value there."""
    params = _params_or_missing(spec, page_url, page_data)
    return params if isinstance(params, dict) else None


def _params_or_missing(spec: RequestSpec, page_url: str, page_data: PageData) -> dict[str, str] | str:
    """Every parameter of `spec` read from the page, or the name of the first one without a value there."""
    params: dict[str, str] = {}
    for name, binder in spec.binders.items():
        value = resolve(binder, page_url, page_data)
        if value is None:
            return name
        params[name] = value
    return params


def request_spec(method: str, url: str, params: Mapping[str, str], body: str | None) -> RequestSpec:
    """The spec with these templates and binders and no headers; it fetches the page first exactly when a binder
    reads the page's JSON documents. Raises `ValidationError` when they are not a valid request."""
    reads_page = any(parse_binder(text).kind in _DATA_KINDS for text in params.values())
    return RequestSpec.model_validate(
        {
            "method": method,
            "url": url,
            "params_from_url": params,
            "body": None if body is None else {"template": body},
            "requires_page_fetch": reads_page,
        }
    )


def render_url(template: str, params: Mapping[str, str]) -> str:
    """`template` with each placeholder replaced by its value, encoded for the path or the query it stands in."""
    path, question, query = template.partition("?")
    return _fill(path, params, PATH_SAFE) + question + _fill(query, params, QUERY_SAFE)


def with_query_value(url: str, name: str, value: str) -> str:
    """`url` with its query items named `name` replaced by one `name=value` at the end, both encoded as a query value
    is (`render_url`)."""
    path, _, query = url.partition("?")
    items = [item for item in query.split("&") if item and unquote(item.partition("=")[0]) != name]
    items.append(f"{quote(name, safe=QUERY_SAFE)}={quote(value, safe=QUERY_SAFE)}")
    return f"{path}?{'&'.join(items)}"


def page_data(page: ParsedPage) -> PageData:
    """The page's JSON documents as `jsonld:` and `js_state:` binders read them: a list per kind, in page order,
    unreadable ones skipped (their collectors report them)."""
    return {kind: documents(kind, page) for kind in PAGE_DATA_KINDS}


def render_body(template: str, params: Mapping[str, str]) -> str:
    """`template` with each placeholder replaced by its value, escaped as JSON string content (RFC 8259 §7)."""
    return PLACEHOLDER.sub(lambda found: json.dumps(params[found[1]], ensure_ascii=False)[1:-1], template)


def _fill(template: str, params: Mapping[str, str], safe: str) -> str:
    return PLACEHOLDER.sub(lambda found: quote(params[found[1]], safe=safe), template)


def _url_value(binder: Binder, url: "_Url") -> str | None:
    if binder.kind == "path":
        index = int(binder.arg)
        return unquote(url.segments[index]) if index < len(url.segments) else None
    if binder.kind == "query":
        return next((unquote(value) for name, value in url.query if value and unquote(name) == binder.arg), None)
    found = re.compile(binder.arg, PCRE_FLAGS).search(url.path)
    return unquote(found[1]) if found is not None and found[1] is not None else None


def _data_value(kind: PageDataKind, query: str, page_data: PageData) -> str | None:
    if kind not in page_data:
        return None
    nodes = json_doc.select(query, page_data[kind])
    return _scalar_text(nodes[0][1]) if len(nodes) == 1 else None


def _scalar_text(value: JsonValue) -> str | None:
    """A string as is and a number as its JSON text (RFC 8259 §6); other values are not parameters."""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return json.dumps(value)
    return None


class _Url(NamedTuple):
    """A URL as binding reads it: the origin, the raw path and its segments after the leading `/`, and the raw query
    items (a value is `None` for an item without `=`)."""

    origin: str
    path: str
    segments: list[str]
    query: list[tuple[str, str | None]]

    @classmethod
    def split(cls, url: str) -> "_Url":
        parts = urlsplit(url)
        items = [item.partition("=") for item in parts.query.split("&")] if parts.query else []
        query = [(name, value if equals else None) for name, equals, value in items]
        segments = parts.path[1:].split("/") if parts.path else []
        return cls(f"{parts.scheme}://{parts.netloc}", parts.path, segments, query)


# --- deterministic binding -------------------------------------------------------------------------------------------


def bind(samples: Sequence[Sample]) -> RequestSpec | Ambiguous:
    """The request spec whose binders reproduce the endpoint request of every sample page (§4.4), with no headers
    yet (§4.6 adds the proven ones); `Ambiguous` when there is none.

    A value of the endpoint request that equals a path segment or query value of the page URL on every sample becomes
    a `path:`/`query:` parameter. A value that varies and appears nowhere in the page URL becomes a `jsonld:`/
    `js_state:` parameter when the same path of the page's JSON documents holds it on every sample. Any other value
    that stays the same is a literal; one that varies makes the binding ambiguous. Telling the two apart needs two
    sample pages at least.
    """
    try:
        return _Binding(samples).spec()
    except _Unbound as unbound:
        return Ambiguous(str(unbound))


class _Unbound(Exception):
    pass


class _Binding:
    def __init__(self, samples: Sequence[Sample]) -> None:
        if len(samples) < 2:
            raise _Unbound("binding needs two sample pages to tell parameters from constants")
        methods = {sample.request.method.upper() for sample in samples}
        if len(methods) != 1 or not methods <= {"GET", "POST"}:
            raise _Unbound(f"the sample requests use methods {sorted(methods)}, not one of GET and POST")
        self.samples = samples
        self.method = methods.pop()
        self.params: dict[str, str] = {}  # binder text -> parameter name

    def spec(self) -> RequestSpec:
        url = self._url_template()
        body = self._body_template()
        params = {name: text for text, name in self.params.items()}
        try:
            spec = request_spec(self.method, url, params, body)
        except ValidationError as error:
            raise _Unbound(f"the bound templates are not a valid request: {error.errors()[0]['msg']}") from None
        for number, sample in enumerate(self.samples):
            if (problem := mismatch(spec, sample)) is not None:
                raise _Unbound(f"the bound templates do not reproduce the request of sample page {number}: {problem}")
        return spec

    def _url_template(self) -> str:
        urls = [_Url.split(sample.request.url) for sample in self.samples]
        first = urls[0]
        # The endpoint URL shape (`network_match.url_shape`) is what binding templates: only its parts may vary.
        if len({url_shape(sample.request.url) for sample in self.samples}) > 1:
            raise _Unbound("the endpoint URL's host, path length or query names differ between sample pages")
        segments = [
            _placeholder_or(self._param([unquote(url.segments[i]) for url in urls], f"path segment {i}"), literal)
            for i, literal in enumerate(first.segments)
        ]
        query = [self._query_item(urls, i, name, value) for i, (name, value) in enumerate(first.query)]
        path = "/" + "/".join(segments) if first.path else ""
        return first.origin + path + ("?" + "&".join(query) if query else "")

    def _query_item(self, urls: list[_Url], index: int, name: str, value: str | None) -> str:
        if value is None:
            return name
        values = [unquote(url.query[index][1] or "") for url in urls]
        return f"{name}={_placeholder_or(self._param(values, f'query value {name!r}'), value)}"

    def _body_template(self) -> str | None:
        bodies = [sample.request.body for sample in self.samples]
        if all(body is None for body in bodies):
            return None
        if any(body is None for body in bodies):
            raise _Unbound("some sample requests have a body and some do not")
        documents = [_parse_body(body) for body in bodies if body is not None]
        markers: dict[str, str] = {}
        for path, leaf in json_doc.scalars(documents[0]):
            name = self._param([_leaf_text(path, document) for document in documents], f"body value {path}")
            if name is not None:
                markers[path] = _marker(name, number=not isinstance(leaf, str))
        return _body_with_placeholders(documents[0], markers)

    def _param(self, values: list[str], where: str) -> str | None:
        """The parameter that binds `values` (one per sample page), or `None` when they are one literal; raises when
        they vary and nothing binds them."""
        varies = len(set(values)) > 1
        text = next(self._url_binders(values), None)
        if text is None and varies:
            text = next(self._data_binders(values), None)
        if text is not None:
            return self.params.setdefault(text, f"p{len(self.params) + 1}")
        if varies:
            raise _Unbound(f"{where} varies between sample pages and no page value binds it")
        return None

    def _url_binders(self, values: list[str]) -> Iterator[str]:
        first = _Url.split(self.samples[0].page_url)
        candidates = [Binder("path", str(i)) for i in range(len(first.segments))]
        candidates += [Binder("query", unquote(name)) for name, _ in first.query if name]
        yield from (str(binder) for binder in candidates if self._binds(binder, values))

    def _data_binders(self, values: list[str]) -> Iterator[str]:
        for kind, document in self.samples[0].page_data.items():
            for path, leaf in json_doc.scalars(document):
                binder = _binder_or_none(f"{kind}:{path}")
                if _scalar_text(leaf) == values[0] and binder is not None and self._binds(binder, values):
                    yield str(binder)

    def _binds(self, binder: Binder, values: list[str]) -> bool:
        return all(
            resolve(binder, sample.page_url, sample.page_data) == value
            for sample, value in zip(self.samples, values, strict=True)
        )


def _placeholder_or(name: str | None, literal: str) -> str:
    return literal if name is None else "{" + name + "}"


def mismatch(spec: RequestSpec, sample: Sample) -> str | None:
    """Why `spec` does not reproduce the endpoint request of `sample` (its method, URL and JSON body), or `None` when
    it does: `method_mismatch(got, want)`, `no_value(<param>)`, `url_mismatch(got, want)` or `body_mismatch(...)`."""
    if spec.method != sample.request.method.upper():
        return f"method_mismatch({spec.method}, {sample.request.method})"
    params = _params_or_missing(spec, sample.page_url, sample.page_data)
    if isinstance(params, str):
        return f"no_value({params})"
    if (url := render_url(spec.url, params)) != sample.request.url:
        return f"url_mismatch({url}, {sample.request.url})"
    return _body_mismatch(spec, params, sample.request.body)


def _body_mismatch(spec: RequestSpec, params: Mapping[str, str], captured: str | None) -> str | None:
    if spec.body is None or captured is None:
        return None if spec.body is None and captured is None else "body_mismatch(a body on one side only)"
    rendered = render_body(spec.body.template, params)
    try:
        same = _canonical(json_doc.parse(rendered)) == _canonical(json_doc.parse(captured))
    except ValueError:  # a value that is not a JSON number filled a number's place
        return "body_mismatch(a body is not JSON)"
    return None if same else f"body_mismatch({rendered}, {captured})"


def _canonical(document: JsonValue) -> str:
    # Python compares `true == 1` and `1 == 1.0`; their JSON texts differ (RFC 8259 §3, §6).
    return json.dumps(document, sort_keys=True)


def _binder_or_none(text: str) -> Binder | None:
    """A normalized path whose names hold a quote or backslash is outside the subset `select` reads."""
    try:
        return parse_binder(text)
    except ValueError:
        return None


def _parse_body(body: str) -> JsonValue:
    try:
        return json_doc.parse(body)
    except ValueError:
        raise _Unbound("a sample request body is not JSON") from None


def _leaf_text(path: str, document: JsonValue) -> str:
    try:
        nodes = json_doc.select(path, document)
    except ValueError:
        nodes = []
    text = _scalar_text(nodes[0][1]) if len(nodes) == 1 else None
    if text is None:
        raise _Unbound(f"the request body has no value at {path} on every sample page")
    return text


def _marker(name: str, *, number: bool) -> str:
    # NUL is not text a JSON body carries unescaped (RFC 8259 §7), so a marker never meets a real value.
    return f"\x00{'N' if number else 'S'}{name}\x00"


def _body_with_placeholders(document: JsonValue, markers: Mapping[str, str]) -> str:
    """`document` as JSON text with the value at each marked path replaced by its placeholder: `"{name}"` for a
    string, a bare `{name}` for a number."""
    text = json.dumps(_marked(document, json_doc.ROOT, markers), ensure_ascii=False, separators=(",", ":"))
    for marker in markers.values():
        number, name = marker[1] == "N", marker[2:-1]
        text = text.replace(json.dumps(marker), "{" + name + "}" if number else '"{' + name + '}"')
    return text


def _marked(value: JsonValue, path: str, markers: Mapping[str, str]) -> JsonValue:
    if isinstance(value, dict):
        return {key: _marked(child, json_doc.member(path, key), markers) for key, child in value.items()}
    if isinstance(value, list):
        return [_marked(child, f"{path}[{i}]", markers) for i, child in enumerate(value)]
    return markers.get(path, value)
