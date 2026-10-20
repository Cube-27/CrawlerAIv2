"""Which adapter, if any, serves a URL or reads a capture (acquisition spec; adapters spec).

Every platform adapter runs unless the deployment disables it (`CRAWLERAI_DISABLED_ADAPTERS`, owner 2026-10-16); the
caller builds the registry from the running ones (`acquire.rungs.adapter_registry`).

A platform on tenants' own hosts (adapters spec) can only tell a host is not its own from the host's answer. A host that
answered an adapter without the platform's signal (`NOT_PLATFORM`) is declined for that adapter for a while, so a
site that is not the platform's gets at most one adapter request per window. A registry remembers the declines it
made for as long as it lives; the processes that fetch take one per page (`for_host`) from the declines stored on the
page's site row (`site.adapter_declined`, D-1384) and store the ones it made back (`declined_for`), so the window holds
across processes and restarts.

A page-scoped adapter (`PageScoped`, a storefront collection) is never asked on the page's own turn: it serves a page
already fetched, with that page's references (`serve` with `page`), so `would_serve` names it only for such a page.
"""

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Final
from urllib.parse import urlsplit

from crawlerai.acquire.api import JsonFetcher
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.adp import ADP
from crawlerai.adapters.ashby import Ashby
from crawlerai.adapters.bamboohr import BambooHR
from crawlerai.adapters.base import NOT_PLATFORM, Adapter, AdapterMatch, PageRefs, PageScoped, Referring
from crawlerai.adapters.greenhouse import Greenhouse
from crawlerai.adapters.lever import Lever
from crawlerai.adapters.oracle_recruiting import OracleRecruiting
from crawlerai.adapters.personio import Personio
from crawlerai.adapters.recruitee import Recruitee
from crawlerai.adapters.rippling import Rippling
from crawlerai.adapters.shopify import Shopify
from crawlerai.adapters.smartrecruiters import SmartRecruiters
from crawlerai.adapters.teamtailor import Teamtailor
from crawlerai.adapters.ukg import UltiPro
from crawlerai.adapters.workable import Workable
from crawlerai.adapters.workday import Workday
from crawlerai.db.models import PageKind

# How long a host stays declined.
DECLINE_FOR: Final = timedelta(hours=24)


def platform_adapters() -> tuple[Adapter, ...]:
    """Every adapter, active or not."""
    return (
        Greenhouse(),
        Lever(),
        Shopify(),
        Workday(),
        OracleRecruiting(),
        Ashby(),
        SmartRecruiters(),
        Recruitee(),
        Workable(),
        Rippling(),
        BambooHR(),
        Teamtailor(),
        UltiPro(),
        Personio(),
        ADP(),
    )


def _now() -> datetime:
    return datetime.now(UTC)


class Registry:
    def __init__(self, adapters: Iterable[Adapter], *, clock: Callable[[], datetime] = _now) -> None:
        """A registry of `adapters`, each of which runs (the caller leaves out the disabled ones)."""
        self._active = tuple(adapters)
        names = [adapter.name for adapter in self._active]
        if len(set(names)) != len(names):
            raise ValueError(f"adapter names repeat: {sorted(names)}")
        self._clock = clock
        self._declined: dict[tuple[str, str], datetime] = {}  # (adapter, host) -> until

    def for_host(self, host: str, stored: Mapping[str, str]) -> "Registry":
        """A registry of the same active adapters knowing the declines `stored` for `host` (adapter name -> the ISO 8601
        time until which it is declined, as `site.adapter_declined` holds them), and none it made itself."""
        registry = Registry(self._active, clock=self._clock)
        for name, until in stored.items():
            registry._declined[(name, host)] = datetime.fromisoformat(until)
        return registry

    def declined_for(self, host: str) -> dict[str, str]:
        """The declines this registry holds for `host` that still run, as `for_host` reads them."""
        now = self._clock()
        held = self._declined.items()
        return {name: until.isoformat() for (name, declined), until in held if declined == host and until > now}

    def detect(self, url: str) -> Adapter | None:
        """The active adapter that detects `url`."""
        return next((a for a in self._active if a.detect(url) is not None), None)

    def reader(self, url: str, endpoint: str) -> tuple[Adapter, AdapterMatch] | None:
        """The active adapter that reads an `api` capture of the page at `url` whose final URL is `endpoint`, with its
        match: one that detects the page and fetches from that endpoint (INV-39)."""
        for adapter in self._active:
            if (match := adapter.detect(url)) is not None and adapter.serves(match, endpoint):
                return adapter, match
        return None

    def referred(self, refs: Callable[[], PageRefs], kind: PageKind | None, types: tuple[str, ...]) -> str | None:
        """The platform page URL the page with `refs` (read only when an active adapter refers) stands for, read for
        the schema.org `types`, by the first active adapter whose `referred` names one it has not declined the host of
        (adapters spec)."""
        referring = [adapter for adapter in self._active if isinstance(adapter, Referring)]
        if not referring:
            return None
        page = refs()
        for adapter in referring:
            url = adapter.referred(page, kind, types)
            if url is not None and self.would_serve(url):
                return url
        return None

    def would_serve(self, url: str, *, fetched: bool = False) -> bool:
        """Whether `serve` would ask an adapter for `url`: an active one detects it and has not declined its host; a
        page-scoped one only for a page already `fetched`."""
        return self._serving(url, fetched=fetched) is not None

    async def serve(
        self, url: str, policy: FetchPolicy, send: JsonFetcher, page: Callable[[], PageRefs] | None = None
    ) -> FetchResult | None:
        """The answer of the active adapter that detects `url` and has not declined its host, requested with `send`;
        None when there is none. A page-scoped adapter serves only a fetched page, whose references `page` reads."""
        adapter = self._serving(url, fetched=page is not None)
        if adapter is None:
            return None
        if isinstance(adapter, PageScoped) and page is not None:
            result = await adapter.fetch_listed(url, page(), policy, send)
        else:
            result = await adapter.fetch(url, policy, send)
        if result.attempts[-1].error == NOT_PLATFORM:
            self._decline(adapter, urlsplit(url).hostname or "")
        return result

    def _serving(self, url: str, *, fetched: bool) -> Adapter | None:
        host = urlsplit(url).hostname or ""
        return next(
            (
                a
                for a in self._active
                if a.detect(url) is not None
                and not self._is_declined(a, host)
                and (fetched or not isinstance(a, PageScoped))
            ),
            None,
        )

    def _is_declined(self, adapter: Adapter, host: str) -> bool:
        until = self._declined.get((adapter.name, host))
        return until is not None and until > self._clock()

    def _decline(self, adapter: Adapter, host: str) -> None:
        self._declined[(adapter.name, host)] = self._clock() + DECLINE_FOR
