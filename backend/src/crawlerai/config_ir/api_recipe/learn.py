"""Recipe learning (SPEC-09 §2 "integration into SPEC-08 learning", ARCHITECTURE §7.2): the API recipe a learning run
gives its config, from the run's sample and held-out pages.

Discovery (§4.3) reads the sample pages' browser captures; the best endpoint candidate is the one a recipe is bound
from (one endpoint per config, D-0035). Its request is bound deterministically (§4.4), or by role D when that is
ambiguous (§4.5), its headers are proven by replay (§4.6), and it is validated on the held-out pages whose captures
hold an answer of the same endpoint (§4.7: held-out browser captures with network bodies). A page's values are what
the engine published from it (`record.data`), as everywhere in learning.

A run always ends with a recipe or the reason it has none, so that the config's validation report says which
(D-0583): a listing (its recipe needs `pagination`, which nothing discovers, D-0604), no endpoint carrying a required
field on every sample page (with whether the sample had network bodies at all, which only browser captures hold), or
the step a recipe failed. Replays go through `replay`,
which sends them through the SSRF guard (INV-16).
"""

import asyncio
from collections.abc import Mapping, Sequence

from crawlerai.config_ir.api_recipe.binding import Ambiguous, CapturedRequest, Sample, bind, page_data
from crawlerai.config_ir.api_recipe.discovery import (
    DiscoverySample,
    EndpointCandidate,
    discover,
    endpoint_request,
)
from crawlerai.config_ir.api_recipe.headers import NotLearnable, Proven, minimize
from crawlerai.config_ir.api_recipe.model import BoundBy
from crawlerai.config_ir.api_recipe.replay import Replay, ReplayPage
from crawlerai.config_ir.api_recipe.role_d import Rejected, bind_by_role_d
from crawlerai.config_ir.api_recipe.validate import HeldOutReplay, RecipeValidated, refused, validate_recipe
from crawlerai.config_ir.held_out import StoredPage
from crawlerai.db.models import JobId
from crawlerai.llm.client import LLMClient
from crawlerai.schemas.types import SchemaDef


async def learn_recipe(
    client: LLMClient,
    sample: Sequence[StoredPage],
    held_out: Sequence[StoredPage],
    schema: SchemaDef,
    replay: Replay,
    *,
    job_id: JobId,
) -> RecipeValidated:
    """The recipe learned from `sample` and validated on `held_out`, or why there is none. An LLM failure of role D
    propagates, as role A's does."""
    if schema.page_kind == "listing":
        return refused("listing: a listing recipe needs pagination, which is not discovered (D-0604)")
    # Parsing the network bodies and the pages is CPU work: a thread keeps the event loop serving meanwhile.
    found = await asyncio.to_thread(_discover, sample, schema)
    if found is None:
        return refused(_no_endpoint(sample))
    endpoint, pages = found
    bound = await _proven(client, endpoint.map, pages, schema, replay, job_id)
    if isinstance(bound, str):
        return refused(bound)
    proven, bound_by = bound
    held = await asyncio.to_thread(_held_out, held_out, endpoint)
    return await validate_recipe(proven, bound_by, endpoint.map, held, schema, replay)


def _discover(sample: Sequence[StoredPage], schema: SchemaDef) -> tuple[EndpointCandidate, list[ReplayPage]] | None:
    """The best endpoint of the sample, with each sample page as replay reads it."""
    samples = [DiscoverySample(page.bundle, page.held_out.facts.published, page.held_out.ctx) for page in sample]
    candidates = discover(samples, schema)
    if not candidates:
        return None
    endpoint = candidates[0]
    return endpoint, [_replay_page(page, request) for page, request in zip(sample, endpoint.requests, strict=True)]


def _no_endpoint(sample: Sequence[StoredPage]) -> str:
    if not any(page.bundle.network for page in sample):
        # Network bodies come with browser captures only (SPEC-02 §4.7); an HTTP capture has none to discover from.
        return "no_network_bodies: no sample page has network responses to discover an endpoint from"
    return "no_endpoint: no JSON response carries a required field's published value on every sample page"


def _held_out(held_out: Sequence[StoredPage], endpoint: EndpointCandidate) -> list[HeldOutReplay]:
    return [
        HeldOutReplay(page.held_out.capture_id, _replay_page(page, request))
        for page in held_out
        if (request := endpoint_request(page.bundle, endpoint)) is not None
    ]


def _replay_page(page: StoredPage, request: CapturedRequest) -> ReplayPage:
    # The page URL is the one the page was requested at, which serving binds from (§4.8).
    sample = Sample(page.bundle.manifest.url, request, page_data(page.held_out.page))
    return ReplayPage(sample, page.held_out.facts.published, page.held_out.ctx)


async def _proven(
    client: LLMClient,
    fields: Mapping[str, str],
    pages: Sequence[ReplayPage],
    schema: SchemaDef,
    replay: Replay,
    job_id: JobId,
) -> tuple[Proven, BoundBy] | str:
    """The bound request with the headers its replay proved, and what bound it; else why there is none."""
    spec = bind([page.sample for page in pages])
    if isinstance(spec, Ambiguous):
        proven = await bind_by_role_d(client, spec, fields, pages, schema, replay, job_id=job_id)
        bound_by: BoundBy = "role_d"
    else:
        proven = await minimize(spec, fields, pages, schema, replay)
        bound_by = "deterministic"
    if isinstance(proven, NotLearnable):
        return f"not_learnable: {proven.reason}"
    if isinstance(proven, Rejected):
        return "role_d_rejected: " + "; ".join(proven.diagnostics)
    return proven, bound_by
