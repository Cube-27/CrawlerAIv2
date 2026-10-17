"""Which adapter, if any, serves a URL or reads a capture (SPEC-02 §4.4, §4.9; SPEC-15 §4.2, §4.7).

Every registered adapter is active unless the deployment disables it (`CRAWLERAI_DISABLED_ADAPTERS`, owner 2026-10-16);
the registry answers only for the active ones.

A platform on tenants' own hosts (SPEC-15) can only tell a host is not its own from the host's answer. A host that
answered an adapter without the platform's signal (`NOT_PLATFORM`) is declined for that adapter for a while, so a
site that is not the platform's gets at most one adapter request per window from this process.
"""

import time
from collections import OrderedDict
from collections.abc import Callable, Collection, Iterable
from typing import Final
from urllib.parse import urlsplit

from crawlerai.acquire.api import JsonFetcher
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.ashby import Ashby
from crawlerai.adapters.base import NOT_PLATFORM, Adapter, AdapterMatch, PageRefs, Referring
from crawlerai.adapters.greenhouse import Greenhouse
from crawlerai.adapters.lever import Lever
from crawlerai.adapters.oracle_recruiting import OracleRecruiting
from crawlerai.adapters.recruitee import Recruitee
from crawlerai.adapters.rippling import Rippling
from crawlerai.adapters.shopify import Shopify
from crawlerai.adapters.smartrecruiters import SmartRecruiters
from crawlerai.adapters.workable import Workable
from crawlerai.adapters.workday import Workday
from crawlerai.db.models import PageKind

# How long a host stays declined, and how many declined hosts are remembered (the oldest is forgotten first).
DECLINE_SECONDS: Final = 24 * 60 * 60
MAX_DECLINED: Final = 10_000


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
    )


class Registry:
    def __init__(
        self, adapters: Iterable[Adapter], active: Collection[str], *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        adapters = tuple(adapters)
        names = [adapter.name for adapter in adapters]
        if len(set(names)) != len(names):
            raise ValueError(f"adapter names repeat: {sorted(names)}")
        if unknown := sorted(set(active) - set(names)):
            raise ValueError(f"no adapter named {unknown}")
        self._active = tuple(adapter for adapter in adapters if adapter.name in active)
        self._clock = clock
        self._declined: OrderedDict[tuple[str, str], float] = OrderedDict()  # (adapter, host) -> until

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

    def referred(self, refs: Callable[[], PageRefs], kind: PageKind | None) -> str | None:
        """The platform page URL the page with `refs` (read only when an active adapter refers) stands for, by the
        first active adapter whose `referred` names one it has not declined the host of (SPEC-15 §4.2)."""
        referring = [adapter for adapter in self._active if isinstance(adapter, Referring)]
        if not referring:
            return None
        page = refs()
        for adapter in referring:
            url = adapter.referred(page, kind)
            if url is not None and self.would_serve(url):
                return url
        return None

    def would_serve(self, url: str) -> bool:
        """Whether `serve` would ask an adapter for `url`: an active one detects it and has not declined its host."""
        return self._serving(url) is not None

    async def serve(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult | None:
        """The answer of the active adapter that detects `url` and has not declined its host, requested with `send`;
        None when there is none."""
        adapter = self._serving(url)
        if adapter is None:
            return None
        result = await adapter.fetch(url, policy, send)
        if result.attempts[-1].error == NOT_PLATFORM:
            self._decline(adapter, urlsplit(url).hostname or "")
        return result

    def _serving(self, url: str) -> Adapter | None:
        host = urlsplit(url).hostname or ""
        return next((a for a in self._active if a.detect(url) is not None and not self._is_declined(a, host)), None)

    def _is_declined(self, adapter: Adapter, host: str) -> bool:
        until = self._declined.get((adapter.name, host))
        if until is None:
            return False
        if until > self._clock():
            return True
        del self._declined[(adapter.name, host)]
        return False

    def _decline(self, adapter: Adapter, host: str) -> None:
        key = (adapter.name, host)
        self._declined[key] = self._clock() + DECLINE_SECONDS
        self._declined.move_to_end(key)
        while len(self._declined) > MAX_DECLINED:
            self._declined.popitem(last=False)
