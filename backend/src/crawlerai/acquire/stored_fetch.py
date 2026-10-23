"""The fetch a capture keeps: the policy it ran under, as `FetchPolicy` serializes it (the caller's request context as
its names and value digest), with every rung tried as `attempts`. The bundle manifest and the `capture` row both hold it
as JSON (`fetch_policy`): it is written by `policy_with_attempts`, parsed as a `StoredFetch` where a manifest or a row
is read, and read in SQL only by the predicates here.
"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import ColumnElement, and_, cast, literal, or_
from sqlalchemy.dialects.postgresql import JSONB

from crawlerai.acquire.types import AttemptRecord, FetchPolicy, PolicyFields
from crawlerai.db.models import Capture, PageKind
from crawlerai.storage.capture_bundle import CaptureManifest

__all__ = [
    "StoredContext",
    "StoredFetch",
    "fetched_as_kind",
    "made_as",
    "policy_with_attempts",
    "stored_fetch",
    "tried_browser",
]


class StoredContext(BaseModel):
    """A `RequestContext` as a capture keeps it: the header and cookie names, each with its value redacted, and the
    keyed digest of the values (`core.context_digest`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    headers: tuple[tuple[str, str], ...] = ()
    cookies: tuple[tuple[str, str], ...] = ()
    digest: str


class StoredFetch(PolicyFields[StoredContext]):
    """The policy a capture was fetched under and every rung tried, in order (the last one kept)."""

    attempts: tuple[AttemptRecord, ...] = ()

    @property
    def tried_browser(self) -> bool:
        return any(attempt.method == "browser" for attempt in self.attempts)


def stored_fetch(manifest: CaptureManifest) -> StoredFetch:
    """The fetch `manifest`'s capture keeps."""
    return StoredFetch.model_validate(manifest.fetch_policy)


def policy_with_attempts(
    fetch_policy: dict[str, JsonValue], attempts: tuple[AttemptRecord, ...]
) -> dict[str, JsonValue]:
    """`fetch_policy` with every rung tried as `attempts`, as the bundle manifest and the `capture` row keep it."""
    stored = StoredFetch.model_validate(fetch_policy).model_copy(update={"attempts": attempts})
    return stored.model_dump(mode="json")


def tried_browser() -> ColumnElement[bool]:
    """The captures whose fetch tried the browser, kept or not (`StoredFetch.tried_browser`)."""
    return Capture.fetch_policy[_key("attempts")].contains([{"method": "browser"}])


def fetched_as_kind(kind: PageKind) -> ColumnElement[bool]:
    """The captures fetched as `kind`, under `memory.remembered_as`: a capture fetched with no page kind is a detail
    page's."""
    stated = Capture.fetch_policy[_key("page_kind")].astext
    return stated == kind if kind == "listing" else or_(stated.is_(None), stated == kind)


def made_as(policy: FetchPolicy) -> ColumnElement[bool]:
    """The captures made the way a fetch under `policy` would be: with its page steps and its request context (names
    and value digest), its screenshot area when it asks for a screenshot, and, for a content-only read, judged by that
    rule or rendered."""
    made = policy.model_dump(mode="json", include={"steps", "context", "screenshot"})
    same = [_stored("steps") == _jsonb(made["steps"]), _stored("context") == _jsonb(made["context"])]
    if policy.screenshot is not None:
        # A screenshot of the viewport does not stand for one of the full page, nor the other way round.
        same.append(_stored("screenshot") == _jsonb(made["screenshot"]))
    if policy.content_only:
        # An HTTP page kept `ok` for a records read may carry its text in a script: the content rule never judged it.
        same.append(or_(_stored("content_only") == _jsonb(True), Capture.method == "browser"))
    return and_(*same)


def _key(name: str) -> str:
    """`name`, a member of the stored fetch: a name it lacks would read as NULL in every row."""
    if name not in StoredFetch.model_fields:
        raise KeyError(f"a stored fetch has no {name!r}")
    return name


def _stored(name: str) -> ColumnElement[Any]:
    return Capture.fetch_policy[_key(name)]


def _jsonb(value: object) -> ColumnElement[Any]:
    """`value` as a JSONB value in SQL: its JSON text, bound as text and cast there (a JSONB-typed bind would encode the
    text again, as a JSON string)."""
    return cast(literal(json.dumps(value)), JSONB)
