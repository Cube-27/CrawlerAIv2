"""Recipe replay (SPEC-09 §4.6, §4.7): send a recipe's request for a captured page over `fetch_json` (so through the
SSRF guard, INV-16) and check that the response reproduces the page's published values through the recipe's map.

Header minimization replays the sample pages; held-out validation replays the held-out ones the same way. A listing
recipe (one with `pagination`) is replayed for its first two pages, the second built by its pagination as serving
builds it (`next_request` of `pagination.py`), and each must give the rows the page's captured calls gave: the same
rows in the same order, each mapped field's raw value equal (Appendix A #59).
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import JsonValue

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.types import FetchResult
from crawlerai.collect import json_doc
from crawlerai.collect.api import read_map
from crawlerai.config_ir.api_recipe.binding import PageData, Sample, render_body, render_url, resolve_params
from crawlerai.config_ir.api_recipe.model import PAGE_URL, Pagination, RequestSpec
from crawlerai.config_ir.api_recipe.pagination import first_request, next_request
from crawlerai.db.models import PageKind
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import equal, normalize
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, HeaderList

# Sends one request: `fetch_json` with the job's policy and engine version.
Replay = Callable[[JsonRequest], Awaitable[FetchResult]]
Scalar = str | int | float
# Renders a page in the browser with network capture (SPEC-02 §4.7), a listing with its browser actions (owner #52):
# the document states kept, none when the page was not reached or may not be fetched. Learning renders the pages whose
# captures hold no calls to learn from.
Render = Callable[[str, PageKind], Awaitable[Sequence[CaptureBundle]]]
# Appendix A #59: a listing recipe is validated on its first two pages, the one the page loaded and the next.
REPLAYED_PAGES: Final = 2


@dataclass(frozen=True)
class ReplayPage:
    """A captured page: its URL, endpoint request and JSON documents, its published values (`record.data`) and the
    normalize context of the page; for a listing, the responses of its first captured calls of the endpoint (pages 1
    and 2, when the page made a second call), which a listing recipe's replay must reproduce."""

    sample: Sample
    values: Mapping[str, JsonValue]
    ctx: Context
    listing: tuple[JsonValue, ...] = ()


def request_for(spec: RequestSpec, page_url: str, page_data: PageData) -> JsonRequest | None:
    """The request `spec` makes for the page; `None` when a parameter has no value there."""
    params = resolve_params(spec, page_url, page_data)
    if params is None:
        return None
    # `{page_url}` is the one placeholder a header value takes (§4.6).
    headers = tuple((name, value.replace(f"{{{PAGE_URL}}}", page_url)) for name, value in spec.headers.items())
    body = None if spec.body is None else render_body(spec.body.template, params)
    return JsonRequest(render_url(spec.url, params), page_url, spec.method, headers, body)


async def reproduces(
    spec: RequestSpec, fields: Mapping[str, str], page: ReplayPage, schema: SchemaDef, replay: Replay
) -> bool:
    """Whether replaying `spec` for `page` reproduces every field `compare` compares there, and at least one."""
    compared = await compare(spec, fields, page, schema, replay)
    return bool(compared) and all(compared.values())


async def compare(
    spec: RequestSpec, fields: Mapping[str, str], page: ReplayPage, schema: SchemaDef, replay: Replay
) -> dict[str, bool]:
    """For each `fields` entry the page has a published value for, whether replaying `spec` for `page` answers JSON
    whose value at its path is `equal` to that value; every entry is false when the request cannot be made or its
    answer is not JSON, and nothing is sent when no field is compared."""
    if spec.pagination is not None:
        return await _compare_listing(spec, spec.pagination, fields, page, replay)
    compared = {name: path for name, path in fields.items() if page.values.get(name) is not None}
    request = request_for(spec, page.sample.page_url, page.sample.page_data)
    if not compared or request is None:
        return dict.fromkeys(compared, False)
    result = await replay(request)
    if result.block_class != "ok":
        return dict.fromkeys(compared, False)
    try:
        document = json_doc.parse(result.bundle.body.decode("utf-8"))
    except ValueError:  # UnicodeDecodeError is a ValueError
        return dict.fromkeys(compared, False)
    return {name: _equal(read_map(path, document), name, page, schema) for name, path in compared.items()}


async def _compare_listing(
    spec: RequestSpec, pagination: Pagination, fields: Mapping[str, str], page: ReplayPage, replay: Replay
) -> dict[str, bool]:
    """For each `fields` entry the captured first page has a value for, whether replaying the listing's first pages
    gives every captured page's rows with the same raw values there."""
    captured = page.listing[:REPLAYED_PAGES]
    wanted = [row_values(pagination.rows, fields, document) for document in captured]
    compared = {name: True for name in fields if wanted and any(v is not None for v in wanted[0][name])}
    bound = request_for(spec, page.sample.page_url, page.sample.page_data)
    request = None if bound is None else first_request(pagination, bound)
    for number, want in enumerate(wanted):
        document = None if request is None else await _replayed(request, replay)
        if request is None or document is None:
            return dict.fromkeys(compared, False)
        got = row_values(pagination.rows, fields, document[0])
        for name in compared:
            compared[name] = compared[name] and got[name] == want[name]
        request = next_request(pagination, request, number + 1, document[0], document[1])
    return compared


async def _replayed(request: JsonRequest, replay: Replay) -> tuple[JsonValue, HeaderList] | None:
    """The replayed response's JSON with its headers; None when it failed or is not JSON."""
    result = await replay(request)
    if result.block_class != "ok":
        return None
    try:
        return json_doc.parse(result.bundle.body.decode("utf-8")), result.bundle.manifest.headers.response
    except ValueError:  # UnicodeDecodeError is a ValueError
        return None


def row_values(rows: str, fields: Mapping[str, str], document: JsonValue) -> dict[str, list[Scalar | None]]:
    """Each field's raw value in every row `rows` selects in `document` (an object row, read relative to it), in row
    order."""
    found: dict[str, list[Scalar | None]] = {name: [] for name in fields}
    for _, row in json_doc.select(rows, document):
        if isinstance(row, dict):
            for name, path in fields.items():
                found[name].append(read_map(path, row))
    return found


def _equal(raw: str | int | float | None, name: str, page: ReplayPage, schema: SchemaDef) -> bool:
    if raw is None:
        return False
    spec = schema.fields[name]
    result = normalize(raw, spec, page.ctx)
    return isinstance(result, Ok) and equal(result.value, page.values[name], spec)
