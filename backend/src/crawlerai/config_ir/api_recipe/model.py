"""The API recipe (SPEC-09 §4.2, ARCHITECTURE §7.2, §12.1): how to fetch the JSON document a page's values come
from, with its parameters bound from the page, and where each field sits in that document.

A recipe is data that our interpreters run, never code (§18). A document that validates here names a binder for every
placeholder and uses every binder, keeps the request's scheme and host fixed, carries no credentials, and writes its
JSONPaths in the subset the engine reads (`select` of `json_doc`). Site strings (the endpoint URL, a binder regex)
live in recipe documents only (C3); this module holds none.
"""

import json
import re
from collections.abc import Callable, Sequence
from typing import Annotated, Final, Literal, NamedTuple, Self, get_args
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from crawlerai.collect import json_doc
from crawlerai.config_ir.portable_regex import PCRE_FLAGS, check_pattern
from crawlerai.db.models import CaptureId
from crawlerai.schemas.types import NAME_PATTERN, Name

# Where a binder reads a parameter's value: a path segment, a query value or a regex group of the page URL, or a
# scalar in one of the page's JSON documents (the two need the HTML page fetched first, §4.4).
BinderKind = Literal["path", "query", "regex", "jsonld", "js_state"]
PageDataKind = Literal["jsonld", "js_state"]
PAGE_DATA_KINDS: Final = frozenset(get_args(PageDataKind))

# `{name}`: a parameter's place in the URL, the body or a header value (RFC 6570 level 1 expression syntax).
PLACEHOLDER: Final = re.compile(rf"\{{({NAME_PATTERN})\}}")
# The page's own URL, the one value a header may template (§4.6: `Referer`); never a parameter name.
PAGE_URL: Final = "page_url"
# Path segment indexes count from 0 and have one spelling: no leading zero.
_INDEX: Final = re.compile(r"0|[1-9][0-9]*")
# RFC 9110 §5.6.2: a field name is a token.
_TOKEN: Final = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
# Fields that carry credentials: RFC 9110 §11.6.2 and §11.7.2, RFC 6265 §5.4. A recipe that needs one is not
# learnable (§4.6), so a recipe never holds one.
CREDENTIAL_FIELDS: Final = frozenset({"authorization", "proxy-authorization", "cookie"})
# Fields the HTTP client sets for the connection it makes, never part of a recipe: Host (RFC 9110 §7.2), the content
# length and transfer coding of the body (§8.6, RFC 9112 §6.1), the connection options (RFC 9110 §7.6.1: Connection,
# Keep-Alive, TE, Upgrade, Proxy-Connection) and the content codings the client decodes (RFC 9110 §12.5.3).
CLIENT_FIELDS: Final = frozenset(
    {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "te",
        "upgrade",
        "proxy-connection",
        "accept-encoding",
    }
)
# §4.2: a money field joins the amount and currency paths with `+`; each part starts at the root `$` (RFC 9535 §2.2).
_JOIN: Final = re.compile(r"\+(?=\$)")


class Binder(NamedTuple):
    kind: BinderKind
    arg: str

    def __str__(self) -> str:
        return f"{self.kind}:{self.arg}"


def parse_binder(text: str) -> Binder:
    """`path:<index>`, `query:<name>`, `regex:<pattern with one group>`, `jsonld:<query>` or `js_state:<query>`;
    raises `ValueError` for anything else."""
    name, _, arg = text.partition(":")
    for kind, check in _BINDER_CHECKS.items():
        if kind == name:
            check(arg)
            return Binder(kind, arg)
    raise ValueError(f"not a binder kind: {name!r}")


def _path_index(arg: str) -> None:
    if _INDEX.fullmatch(arg) is None:
        raise ValueError(f"not a path segment index: {arg!r}")


def _query_name(arg: str) -> None:
    if not arg:
        raise ValueError("a query binder names a query parameter")


def _one_group_regex(arg: str) -> None:
    check_pattern(arg)
    if re.compile(arg, PCRE_FLAGS).groups != 1:
        raise ValueError(f"a regex binder has exactly one capturing group: {arg!r}")


def _engine_jsonpath(arg: str) -> None:
    json_doc.select(arg, None)  # raises for a query outside the subset the engine reads


_BINDER_CHECKS: Final[dict[BinderKind, Callable[[str], None]]] = {
    "path": _path_index,
    "query": _query_name,
    "regex": _one_group_regex,
    "jsonld": _engine_jsonpath,
    "js_state": _engine_jsonpath,
}


def _check_binder(text: str) -> str:
    parse_binder(text)
    return text


def _check_jsonpath(path: str) -> str:
    _engine_jsonpath(path)
    return path


def map_paths(path: str) -> list[str]:
    """The JSONPaths a map entry joins with `+`, in order."""
    return _JOIN.split(path)


def joined_raw(parts: Sequence[str | int | float]) -> str:
    """The raw value of a map entry that joins its parts with `+`: their texts separated by a space, a number as its
    JSON text (RFC 8259 §6), so the money normalizer reads an amount and a currency as one value."""
    return " ".join(part if isinstance(part, str) else json.dumps(part) for part in parts)


def read_map(path: str, document: JsonValue) -> str | int | float | None:
    """The raw value a map entry reads in `document`: the one scalar its path selects, or its joined parts'
    `joined_raw`; `None` when a part selects anything but exactly one scalar."""
    parts: list[str | int | float] = []
    for part in map_paths(path):
        nodes = json_doc.select(part, document)
        if len(nodes) != 1 or not json_doc.is_scalar(value := nodes[0][1]):
            return None
        parts.append(value)
    return parts[0] if len(parts) == 1 else joined_raw(parts)


def _check_map_path(path: str) -> str:
    for part in map_paths(path):
        _engine_jsonpath(part)
    return path


def _check_url_template(url: str) -> str:
    outside = PLACEHOLDER.sub("", url)
    if "{" in outside or "}" in outside:
        raise ValueError("a brace outside a {name} placeholder")  # RFC 3986 §2: not a URL character
    raw = urlsplit(url)
    if "{" in raw.scheme + raw.netloc:
        raise ValueError("the scheme and host are fixed; placeholders go in the path or query")
    filled = urlsplit(PLACEHOLDER.sub("x", url))
    if filled.scheme not in ("http", "https") or not filled.hostname or filled.fragment:
        raise ValueError("an absolute http(s) URL without a fragment")
    return url


def _check_header_value(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise ValueError("a field value holds no line break")  # RFC 9110 §5.5
    if any(name != PAGE_URL for name in PLACEHOLDER.findall(value)):
        raise ValueError(f"{{{PAGE_URL}}} is the only placeholder a header value takes")
    return value


BinderText = Annotated[str, AfterValidator(_check_binder)]
UrlTemplate = Annotated[str, AfterValidator(_check_url_template)]
HeaderName = Annotated[str, StringConstraints(pattern=rf"^{_TOKEN.pattern}$")]
HeaderValue = Annotated[str, AfterValidator(_check_header_value)]
EngineJsonPath = Annotated[str, AfterValidator(_check_jsonpath)]
MapPath = Annotated[str, AfterValidator(_check_map_path)]


def _not_page_url(name: str) -> str:
    if name == PAGE_URL:
        raise ValueError(f"{PAGE_URL} is the page URL, not a parameter")
    return name


ParamName = Annotated[Name, AfterValidator(_not_page_url)]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RequestBody(_Model):
    """A JSON request body with `{name}` placeholders; a value is written JSON-escaped where its placeholder stands."""

    template: str = Field(min_length=1)


class Pagination(_Model):
    """§4.8: the listing's next request sets query parameter `name` to `start`, `start + step`, ... until `rows`
    selects nothing."""

    kind: Literal["param"]
    name: str = Field(min_length=1)
    start: int = Field(ge=0)
    step: int = Field(ge=1)
    rows: EngineJsonPath


class RequestSpec(_Model):
    """The request half of a recipe: what deterministic binding (§4.4) and role D (§4.5) produce."""

    method: Literal["GET", "POST"]
    url: UrlTemplate
    params_from_url: dict[ParamName, BinderText] = {}
    headers: dict[HeaderName, HeaderValue] = {}
    body: RequestBody | None = None
    pagination: Pagination | None = None
    requires_page_fetch: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.body is not None and self.method != "POST":
            raise ValueError("only a POST carries a body")  # RFC 9110 §9.3.1: a GET body has no defined meaning
        used = set(PLACEHOLDER.findall(self.url + (self.body.template if self.body else "")))
        if used != set(self.params_from_url):
            raise ValueError(f"placeholders {sorted(used)} and binders {sorted(self.params_from_url)} differ")
        names = [name.lower() for name in self.headers]
        if len(set(names)) != len(names):
            raise ValueError("a header named twice")  # RFC 9110 §5.1: field names are case-insensitive
        if CREDENTIAL_FIELDS.intersection(names):
            raise ValueError("a recipe carries no credentials")
        if CLIENT_FIELDS.intersection(names):
            raise ValueError("a recipe carries no field the HTTP client sets itself")
        if self.requires_page_fetch != self.reads_page_data:
            raise ValueError("requires_page_fetch is true exactly when a binder reads the page's JSON documents")
        return self

    @property
    def binders(self) -> dict[str, Binder]:
        return {name: parse_binder(text) for name, text in self.params_from_url.items()}

    @property
    def reads_page_data(self) -> bool:
        return any(binder.kind in PAGE_DATA_KINDS for binder in self.binders.values())


class Proof(_Model):
    """How the recipe was accepted: the held-out captures it reproduced (§4.7), the headers replay tried (§4.6) and
    what bound it."""

    validated_on: list[CaptureId] = Field(min_length=1)
    headers_tried: int = Field(ge=0)
    bound_by: Literal["deterministic", "role_d"]


class ApiRecipe(RequestSpec):
    map: dict[Name, MapPath] = Field(min_length=1)
    proof: Proof
