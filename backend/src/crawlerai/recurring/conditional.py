"""Conditional GET (SPEC-11 §4.2, ARCHITECTURE §14): a page fetched with the validators it last answered with is
`unchanged` when it answers 304, and nothing of it is downloaded or stored."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from crawlerai.acquire.rungs import with_attempts
from crawlerai.acquire.types import AttemptRecord, FetchResult, Validators
from crawlerai.storage.capture_bundle import HeaderList

__all__ = ["Unchanged", "fetch_unless_unchanged", "received"]

# RFC 9110 §15.4.5: 304 Not Modified, the answer to a conditional GET whose condition is false.
_NOT_MODIFIED = 304


@dataclass(frozen=True)
class Unchanged:
    """A page that answered 304: the task's outcome is `unchanged`, and there is no bundle to store."""

    attempts: tuple[AttemptRecord, ...]
    duration_ms: int


async def fetch_unless_unchanged(
    fetch: Callable[[Validators | None], Awaitable[FetchResult]], validators: Validators | None, *, has_record: bool
) -> FetchResult | Unchanged:
    """`fetch` the page with `validators`, the ones stored for it (`crawlerai.recurring.state`). A 304 is `Unchanged`,
    unless there is no record of the page to stand for it (`has_record`): then the stored state has drifted, and the
    page is fetched once more without validators (§4.6). The result lists the attempts of both fetches."""
    result = await fetch(validators)
    if validators is None or result.bundle.manifest.status_code != _NOT_MODIFIED:
        return result
    if has_record:
        return Unchanged(attempts=result.attempts, duration_ms=result.duration_ms)
    again = await fetch(None)
    return with_attempts(again, result.attempts + again.attempts, result.duration_ms + again.duration_ms)


def received(result: FetchResult) -> Validators:
    """The validators of the response kept: its ETag (RFC 9110 §8.8.3) and Last-Modified (§8.8.2). Both are
    singleton fields; when one is repeated, the last value received is used."""
    headers = result.bundle.manifest.headers.response
    return Validators(etag=_last(headers, "etag"), last_modified=_last(headers, "last-modified"))


def _last(headers: HeaderList, name: str) -> str | None:
    # RFC 9110 §5.1: field names are case-insensitive.
    values = [value for field, value in headers if field.lower() == name]
    return values[-1] if values else None
