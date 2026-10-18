"""What a caller's secret values are shown as, and a stored request with them hidden (D-1432, D-1510).

A request's `fetch` holds the caller's header and cookie values (`services.fetch_options`). Every answer that shows a
stored request, and the job that ends (`db.jobs.transition_job`), replace each value by `REDACTED`, keeping the names.
"""

from collections.abc import Mapping
from typing import Any, Final

# What a capture, a log line or an answer shows for a secret value (pydantic's `SecretStr` rendering).
REDACTED: Final = "**********"
# The members of a request's `fetch` whose values are secrets.
SECRET_MEMBERS: Final = ("headers", "cookies")


def redacted_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """A stored request with its `fetch` secrets shown as `REDACTED`; the other members are as stored."""
    fetch = request.get("fetch")
    if not isinstance(fetch, Mapping):
        return dict(request)
    shown = dict(fetch)
    for member in SECRET_MEMBERS:
        if isinstance(values := fetch.get(member), Mapping):
            shown[member] = dict.fromkeys(values, REDACTED)
    return {**request, "fetch": shown}


def has_secrets(request: Mapping[str, Any]) -> bool:
    """Whether the request's `fetch` holds a secret value that is not already `REDACTED`."""
    fetch = request.get("fetch")
    if not isinstance(fetch, Mapping):
        return False
    return any(
        value != REDACTED
        for member in SECRET_MEMBERS
        if isinstance(values := fetch.get(member), Mapping)
        for value in values.values()
    )
