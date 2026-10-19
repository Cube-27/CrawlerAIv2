"""What the services run with in one process: the database, the fetching rungs, the LLM client and the engine's data
files. The API app and the MCP server's stdio process open one each from the settings (jobs spec)."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from functools import partial

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.acquire.api import fetch_json
from crawlerai.acquire.browser import BrowserSession, fetch_browser, open_browser
from crawlerai.acquire.browser_tab import Drive, fetch_listing
from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.impersonate import rung_impersonation
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs, adapter_registry
from crawlerai.acquire.session import CookieExport, SiteSessions
from crawlerai.acquire.shared_browser import SharedBrowser
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult, PagedFetch
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.core.event_loop import quiet_peer_resets
from crawlerai.core.settings import Settings
from crawlerai.llm.client import LLMClient
from crawlerai.llm.providers.from_settings import llm_from_settings
from crawlerai.llm.setup import LLMSetup
from crawlerai.normalize.dispatch import warm
from crawlerai.resolve.pipeline import EngineData
from crawlerai.search.providers import SearchProvider, configured
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
    search: SearchProvider | None = None  # None without a configured provider: search answers 503 (D-1442)


@asynccontextmanager
async def open_fetching(settings: Settings, connector: SafeConnector | None = None) -> AsyncIterator[Fetching]:
    """What a process fetches pages with (acquisition spec): HTTP, the process's one shared browser (launched when a
    fetch first needs it), the adapters and the process's site sessions, all through one SSRF guard; the browser
    closes with the block."""
    connector = connector or SafeConnector()
    pools = settings.proxy_pools

    async def fetch_in(
        session: BrowserSession, url: str, policy: FetchPolicy, export: CookieExport | None
    ) -> FetchResult:
        return await fetch_browser(
            url, policy, session=session, engine_version=ENGINE_VERSION, connector=connector, pools=pools, export=export
        )

    async def listing(url: str, policy: FetchPolicy, drive: Drive) -> PagedFetch:
        # A render with browser actions (owner #52, `learning_render`) is rare, so a browser is launched for each.
        async with open_browser() as session:
            return await fetch_listing(
                url, policy, drive, session=session, engine_version=ENGINE_VERSION, connector=connector, pools=pools
            )

    impersonate = rung_impersonation(settings)
    sessions = SiteSessions()  # this process's site sessions (INV-29's exception), in memory only
    http = partial(
        fetch_http,
        engine_version=ENGINE_VERSION,
        impersonate=impersonate,
        connector=connector,
        pools=pools,
        sessions=sessions,
    )
    json = partial(
        fetch_json,
        engine_version=ENGINE_VERSION,
        impersonate=impersonate,
        connector=connector,
        pools=pools,
        sessions=sessions,
    )
    async with aclosing(
        SharedBrowser(open_browser, fetch_in, lambda session: session.browser.is_connected())
    ) as browser:
        rungs = Rungs(
            http=http,
            browser=browser.fetch,
            adapters=adapter_registry(settings.disabled_adapters),
            conditional=http,
            json=json,
            sessions=sessions,
            exporting=browser.fetch,
            listing=listing,
        )
        yield Fetching(rungs, connector, open_store(settings.object_store), HostLimiter(), frozenset(pools))


def _search(settings: Settings) -> SearchProvider | None:
    return configured(
        settings.search_searxng_url, settings.search_url_template, settings.search_timeout_s, settings.search_fields
    )


@asynccontextmanager
async def open_runtime(settings: Settings) -> AsyncIterator[Runtime]:
    quiet_peer_resets(asyncio.get_running_loop())
    engine = create_async_engine(settings.database_url.get_secret_value())
    llm, setup = llm_from_settings(settings, engine)
    check = asyncio.create_task(setup.verify())
    # The normalizers' all-locale tables are built in the background, not by the first request that extracts.
    warming = asyncio.create_task(asyncio.to_thread(warm))
    try:
        async with open_fetching(settings) as fetching:
            yield Runtime(
                database=engine,
                fetching=fetching,
                llm=llm,
                engine_data=load_engine_data(fetching.rungs.adapters),
                drift_margins=load_drift_margins(),
                llm_setup=setup,
                search=_search(settings),
            )
    finally:
        check.cancel()
        warming.cancel()
        await engine.dispose()
