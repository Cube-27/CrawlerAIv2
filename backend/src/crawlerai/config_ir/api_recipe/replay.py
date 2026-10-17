"""Recipe replay (SPEC-09 §4.6, §4.7): send a recipe's request for a captured page over `fetch_json` (so through the
SSRF guard, INV-16) and check that the response reproduces the page's published values through the recipe's map.

Header minimization replays the sample pages; held-out validation replays the held-out ones the same way.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from pydantic import JsonValue

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.types import FetchResult
from crawlerai.collect import json_doc
from crawlerai.collect.api import read_map
from crawlerai.config_ir.api_recipe.binding import PageData, Sample, render_body, render_url, resolve_params
from crawlerai.config_ir.api_recipe.model import PAGE_URL, RequestSpec
from crawlerai.db.models import JobId
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import equal, normalize
from crawlerai.schemas.types import SchemaDef

# Sends one request: `fetch_json` with the job's policy and engine version.
Replay = Callable[[JsonRequest], Awaitable[FetchResult]]
# A learning run's `Replay`, for its job (whose usage the requests count as) and the site's proxy pool (D-1381).
Replays = Callable[[JobId, str | None], Replay]


@dataclass(frozen=True)
class ReplayPage:
    """A captured page: its URL, endpoint request and JSON documents, its published values (`record.data`) and the
    normalize context of the page."""

    sample: Sample
    values: Mapping[str, JsonValue]
    ctx: Context


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


def _equal(raw: str | int | float | None, name: str, page: ReplayPage, schema: SchemaDef) -> bool:
    if raw is None:
        return False
    spec = schema.fields[name]
    result = normalize(raw, spec, page.ctx)
    return isinstance(result, Ok) and equal(result.value, page.values[name], spec)
