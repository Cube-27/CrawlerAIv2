"""What the services run with in one process: the database, the fetching rungs, the LLM client and the engine's data
files. The API app and the MCP server's stdio process open one each from the settings (SPEC-10 §4.7)."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.acquire.api import fetch_json
from crawlerai.acquire.browser import fetch_browser, open_browser
from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs, adapter_registry
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.core.event_loop import quiet_peer_resets
from crawlerai.core.settings import Settings
from crawlerai.llm.client import LLMClient
from crawlerai.llm.providers.from_settings import llm_from_settings
from crawlerai.llm.setup import LLMSetup
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services.fetching import Fetching
from crawlerai.services.scrape_steps import load_drift_margins, load_engine_data
from crawlerai.storage import open_store


@dataclass(frozen=True)
class Runtime:
    database: AsyncEngine
    fetching: Fetching
    llm: LLMClient
    engine_data: EngineData | None  # None without the data files: no `records`
    drift_margins: DriftMargins | None
    llm_setup: LLMSetup  # checked in the background from when `open_runtime` opens (`crawlerai.llm.setup`)


def fetching_from_settings(settings: Settings) -> Fetching:
    """The rungs the services fetch with, all through one SSRF guard."""
    connector = SafeConnector()
    pools = settings.proxy_pools

    async def browser(url: str, policy: FetchPolicy) -> FetchResult:
        # The browser is a rung of last resort here (ARCHITECTURE §7.1), so it is launched per fetch rather than kept
        # running beside every API process.
        async with open_browser() as session:
            return await fetch_browser(
                url, policy, session=session, engine_version=ENGINE_VERSION, connector=connector, pools=pools
            )

    http = partial(
        fetch_http, engine_version=ENGINE_VERSION, impersonate=settings.impersonate, connector=connector, pools=pools
    )
    json = partial(fetch_json, engine_version=ENGINE_VERSION, connector=connector)
    rungs = Rungs(http=http, browser=browser, adapters=adapter_registry(settings.adapters), conditional=http, json=json)
    return Fetching(rungs, connector, open_store(settings.object_store), HostLimiter())


@asynccontextmanager
async def open_runtime(settings: Settings) -> AsyncIterator[Runtime]:
    quiet_peer_resets(asyncio.get_running_loop())
    engine = create_async_engine(settings.database_url.get_secret_value())
    llm, setup = llm_from_settings(settings, engine)
    check = asyncio.create_task(setup.verify())
    fetching = fetching_from_settings(settings)
    try:
        yield Runtime(
            database=engine,
            fetching=fetching,
            llm=llm,
            engine_data=load_engine_data(fetching.rungs.adapters),
            drift_margins=load_drift_margins(),
            llm_setup=setup,
        )
    finally:
        check.cancel()
        await engine.dispose()
