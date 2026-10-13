"""Which adapter, if any, serves a URL (SPEC-02 §4.4, §4.9).

An adapter ships inactive until the eval report shows it measured on ≥ 3 tenants not used to build it (C6, D-0011),
so the registry answers only for the adapters named active.
"""

from collections.abc import Collection, Iterable

from crawlerai.acquire.api import JsonFetcher
from crawlerai.adapters.base import Adapter
from crawlerai.adapters.greenhouse import Greenhouse


def platform_adapters(fetch: JsonFetcher) -> tuple[Adapter, ...]:
    """Every adapter, active or not, fetching through `fetch`."""
    return (Greenhouse(fetch),)


class Registry:
    def __init__(self, adapters: Iterable[Adapter], active: Collection[str]) -> None:
        adapters = tuple(adapters)
        names = [adapter.name for adapter in adapters]
        if len(set(names)) != len(names):
            raise ValueError(f"adapter names repeat: {sorted(names)}")
        if unknown := sorted(set(active) - set(names)):
            raise ValueError(f"no adapter named {unknown}")
        self._active = tuple(adapter for adapter in adapters if adapter.name in active)

    def detect(self, url: str) -> Adapter | None:
        return next((adapter for adapter in self._active if adapter.detect(url) is not None), None)
