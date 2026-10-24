"""The platform a fetched page shows (`adapters.platforms`), read once per fetch: the product JSON join (`rungs`) and
the site's memory (`memory`) both ask it of one page."""

from snowcrawl.acquire.types import FetchResult
from snowcrawl.adapters.platforms import platform_of
from snowcrawl.core.derived import held


def platform_shown(result: FetchResult) -> str | None:
    """The platform whose signal the page shows (`platform_of`), kept with the body and response headers it was read
    from: a copy of the result with the same capture body (its attempts, a joined data call) reads it again from
    neither."""
    bundle = result.bundle
    headers = bundle.manifest.headers.response
    return held(result, "_platform", (bundle.body, headers), lambda: platform_of(bundle.text, headers))
