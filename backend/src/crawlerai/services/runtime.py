"""What the services run with in one process: the database, the fetching rungs, the LLM client and the engine's data
files. The API app and the MCP server's stdio process open one each from the settings (jobs spec)."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from functools import partial

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.acquire.api import fetch_json
from crawlerai.acquire.browser import fetch_browser
from crawlerai.acquire.browser_session import BrowserSession, open_browser
from crawlerai.acquire.browser_tab import Drive, fetch_listing
from crawlerai.acquire.cookie_store import CookieStore
from crawlerai.acquire.host_turns import HostTurns
from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.impersonate import rung_impersonation
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs, adapter_registry
from crawlerai.acquire.session import CookieExport, SiteSessions
from crawlerai.acquire.shared_browser import SharedBrowser
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult, PagedFetch
from crawlerai.collect.run import Adapters
from crawlerai.collect.vocabulary import VocabularyMissing
from crawlerai.config_ir.drift import MARGINS_FILE, DriftMargins, load_margins
from crawlerai.content.fragments import eager_frames
from crawlerai.core.context_digest import configure as configure_context_digest
from crawlerai.core.egress import Egresses
from crawlerai.core.engine_version import ENGINE_VERSION, engine_data_dir
from crawlerai.core.event_loop import quiet_peer_resets
from crawlerai.core.settings import Settings
from crawlerai.llm.client import LLMClient
from crawlerai.llm.providers.from_settings import llm_from_settings
from crawlerai.llm.setup import LLMSetup
from crawlerai.normalize.dispatch import warm
from crawlerai.normalize.locales import iso_3166_alpha2
from crawlerai.resolve.pipeline import EngineData
from crawlerai.search.providers import SearchProvider, configured
from crawlerai.services.fetching import Fetching
from crawlerai.storage import open_store

log = logging.getLogger(__name__)


def load_engine_data(adapters: Adapters) -> EngineData | None:
    """The engine's data files from the engine directory's `data/`, with the process's active `adapters` to read their
    captures, for `records` and replays; None where they are not there (no engine directory, or a tree without
    `crawlerai data fetch`): `records` and replays are then unavailable, and the other formats work."""
    data = engine_data_dir()
    if data is None:
        log.warning("no engine directory: records and replays are unavailable")
        return None
    try:
        return EngineData.load(data, adapters)
    except VocabularyMissing as e:
        log.warning("records and replays are unavailable: %s", e)
        return None


def load_drift_margins() -> DriftMargins | None:
    """The dev-fitted drift margins (learning-configs spec); None when none are fitted, and then no field is
    suspended."""
    data = engine_data_dir()
    return None if data is None else load_margins(data / MARGINS_FILE)


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
async def open_fetching(
    settings: Settings, connector: SafeConnector | None = None, database: AsyncEngine | None = None
) -> AsyncIterator[Fetching]:
    """What a process fetches pages with (acquisition spec): HTTP, the process's one shared browser (launched when a
    render first needs it; the page rung's and the listing rung's alike), the adapters and the process's site sessions,
    all through one SSRF guard; the browser closes with the block. With a `database`, hosts' turns and holds are shared
    with every process through it (`acquire/host_turns.py`), and with a cookie key too, the site sessions keep the
    stored cookie state of temporary browser profiles in it. The cookie key also keys the digest of request contexts
    (`core.context_digest`)."""
    connector = connector or SafeConnector()
    pools = settings.proxy_pools
    key = settings.cookie_key
    if key is not None:
        configure_context_digest(key.get_secret_value())
    store = None if database is None or key is None else CookieStore(database, key.get_secret_value())
    sessions = SiteSessions(store=store)  # this process's site sessions (INV-29's exception)

    async def fetch_in(
        session: BrowserSession, url: str, policy: FetchPolicy, export: CookieExport | None
    ) -> FetchResult:
        return await fetch_browser(
            url,
            policy,
            session=session,
            engine_version=ENGINE_VERSION,
            connector=connector,
            pools=pools,
            export=export,
            sessions=sessions,
        )

    impersonate = await rung_impersonation(settings, browser_rung=True)
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
        SharedBrowser(
            partial(open_browser, settings.browser_profiles, settings.egress_country),
            fetch_in,
            lambda session: session.alive,
        )
    ) as browser:

        async def listing(url: str, policy: FetchPolicy, drive: Drive) -> PagedFetch:
            # A listing with browser actions (owner #52) renders in the shared session too, holding one of its slots.
            return await browser.render(
                lambda session: fetch_listing(
                    url,
                    policy,
                    drive,
                    session=session,
                    engine_version=ENGINE_VERSION,
                    connector=connector,
                    pools=pools,
                    sessions=sessions,
                )
            )

        rungs = Rungs(
            http=http,
            browser=browser.fetch,
            adapters=adapter_registry(settings.disabled_adapters),
            json=json,
            sessions=sessions,
            exporting=browser.fetch,
            listing=listing,
            frames=eager_frames,
        )
        limiter = HostLimiter(shared=None if database is None else HostTurns(database))
        egresses = Egresses(pools, settings.egress_country)
        # A declared country must be a real one: a typo would be recorded as a known egress.
        declared = [pool.country for pool in pools.values()] + [settings.egress_country]
        if not all(country is None or country in iso_3166_alpha2() for country in declared):
            raise ValueError("an egress country is an ISO 3166-1 alpha-2 country code")
        yield Fetching(rungs, connector, open_store(settings.object_store), limiter, egresses)


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
        async with open_fetching(settings, database=engine) as fetching:
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
