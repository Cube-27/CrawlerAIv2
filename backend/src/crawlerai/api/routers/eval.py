"""Labeling endpoints (SPEC-03 §4.10), mounted only with `CRAWLERAI_EVAL_UI=true`.

They serve the dev split only. Hidden and fresh cases never reach the main API (C1, INV-01): the backend holds a
`DevEvalStore` and nothing else, and a request naming another split is refused before any store is touched.

Labels are validated before anything is stored (`parse_labels`), and every error comes back with its field and
reason as an RFC 9457 problem (§4.11). SPEC-07 PR 2 adds API-key auth.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated, Literal, Protocol, assert_never, get_args
from urllib.parse import urljoin

from fastapi import APIRouter, Body, Depends, FastAPI, Header, Query, Request, Response
from pydantic import Field, JsonValue
from selectolax.lexbor import LexborHTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.api.dto import PROBLEM_RESPONSE, Model
from crawlerai.api.problems import ProblemError, invalid, not_found
from crawlerai.content.html import remove_scripting_attributes
from crawlerai.core.capture import BlockClass
from crawlerai.core.settings import Settings
from crawlerai.db.models import CaptureId, EvalCategory, EvalPageId, PageKind, SchemaDef, SchemaId
from crawlerai.eval.cli import Captured, EvalCliError, Outcome, PageRequest, Skipped, check_urls, run_capture
from crawlerai.eval.labels import (
    InvalidLabels,
    LabelError,
    Labels,
    LabelStatus,
    field_specs,
    parse_labels,
    same_person,
)
from crawlerai.eval.store import DevEvalStore, EvalNotFound, EvalPageRow, EvalStore, LabelPass, LabelsChanged
from crawlerai.schemas.types import FieldSpec
from crawlerai.storage import open_store
from crawlerai.storage.base import ObjectNotFound
from crawlerai.storage.capture_bundle import CaptureBundle, CorruptBundle, decode_body, sha256_hex

# `POST /capture` fetches within the request, one polite fetch at a time, so a request stays short.
MAX_CAPTURE_URLS = 20


class LabelingBackend(Protocol):
    @property
    def store(self) -> EvalStore: ...

    async def schema_fields(self, schema_id: SchemaId) -> dict[str, FieldSpec]: ...

    async def capture(self, requests: Sequence[PageRequest], page_kind: PageKind) -> list[Outcome]: ...


class DevLabelingBackend:
    """The dev store, `schema_def` in the main database, and `eval capture` into dev. Private settings, even when
    present, are never read."""

    def __init__(self, settings: Settings, engine: AsyncEngine) -> None:
        self._settings = settings
        self._engine = engine
        self._store = DevEvalStore(self._engine, open_store(settings.object_store))

    @property
    def store(self) -> DevEvalStore:
        return self._store

    async def schema_fields(self, schema_id: SchemaId) -> dict[str, FieldSpec]:
        async with self._engine.connect() as conn:
            fields: dict[str, JsonValue] = (
                await conn.execute(select(SchemaDef.fields).where(SchemaDef.id == schema_id))
            ).scalar_one()
        return field_specs(fields)

    async def capture(self, requests: Sequence[PageRequest], page_kind: PageKind) -> list[Outcome]:
        return await run_capture(self._settings, "dev", requests, page_kind)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Runs inside the app's lifespan, which owns the database engine (`api.app`).
    app.state.labeling_backend = DevLabelingBackend(Settings(), app.state.database)
    yield


def labeling_backend(request: Request) -> LabelingBackend:
    backend: LabelingBackend = request.app.state.labeling_backend
    return backend


Backend = Annotated[LabelingBackend, Depends(labeling_backend)]

# Request validation answers with a problem (`api.problems`), declared here in place of FastAPI's own 422 body.
router = APIRouter(prefix="/v1/eval", tags=["eval"], lifespan=_lifespan, responses={422: PROBLEM_RESPONSE})


def _invalid(detail: str, errors: Sequence[LabelError] = ()) -> ProblemError:
    return invalid(detail, [(e.path, e.reason) for e in errors])


def _not_found(page_id: EvalPageId) -> ProblemError:
    return not_found(f"no dev eval page {page_id}")


def _labels_changed(status: int) -> ProblemError:
    return ProblemError(
        status, "labels_changed", "Labels changed", "another pass was stored since the page was read; reload it"
    )


def _not_implemented(detail: str) -> ProblemError:
    return ProblemError(501, "not_implemented", "Not implemented", detail)


def _etag(page: EvalPageRow) -> str:
    """A strong entity tag of the page's stored labels (RFC 9110 §8.8.3): sha256 of their canonical JSON."""
    canonical = json.dumps(page.labels, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f'"{sha256_hex(canonical.encode())}"'


def _if_match(header: str, etag: str) -> bool:
    """RFC 9110 §13.1.1: `*`, or a list of entity tags one of which strongly matches. A weak tag never does."""
    return header.strip() == "*" or etag in (tag.strip() for tag in header.split(","))


_STATUSES: dict[str, LabelStatus] = {status: status for status in get_args(LabelStatus)}


def _status(page: EvalPageRow) -> LabelStatus | None:
    """The stored labels' status; None for a page not labeled yet."""
    status = page.labels.get("status")
    return _STATUSES.get(status) if isinstance(status, str) else None


class PageSummary(Model):
    id: EvalPageId
    capture_id: CaptureId
    split: Literal["dev"]
    schema_name: str
    page_kind: PageKind
    category: EvalCategory
    status: LabelStatus | None  # None: not labeled yet
    labeler: str | None
    checker: str | None

    @classmethod
    def of(cls, page: EvalPageRow) -> "PageSummary":
        return cls(
            id=page.id,
            capture_id=page.capture_id,
            split="dev",
            schema_name=page.schema_name,
            page_kind=page.page_kind,
            category=page.category,
            status=_status(page),
            labeler=page.labeler,
            checker=page.checker,
        )


class PageDetail(PageSummary):
    labels: Labels | None
    fields: dict[str, FieldSpec]  # the page's schema fields, which its labels label
    url: str
    final_url: str
    bundle_html: str  # sanitized; see `sanitize_html`
    text: str | None  # the cleaned text that `text:` locators index; arrives with SPEC-05 PR 1


class NormalizeRequest(Model):
    field: str
    raw_text: str


class CaptureRequest(Model):
    split: Literal["dev"]
    schema_name: str = Field(alias="schema")
    page_kind: PageKind
    category: EvalCategory
    urls: list[str] = Field(min_length=1, max_length=MAX_CAPTURE_URLS)


class CapturedOut(Model):
    kind: Literal["captured"] = "captured"
    n: int  # the URL's position in the request, from 1
    capture_id: CaptureId
    page_id: EvalPageId
    status_code: int
    block_class: BlockClass
    error: str | None


class SkippedOut(Model):
    kind: Literal["skipped"] = "skipped"
    n: int
    reason: str


class CaptureResponse(Model):
    outcomes: list[Annotated[CapturedOut | SkippedOut, Field(discriminator="kind")]]


@router.get("/pages")
async def list_pages(
    backend: Backend,
    split: Literal["dev"] = "dev",  # §4.10's filter; the API serves no other split (C1)
    status: LabelStatus | None = None,
    schema_name: Annotated[str | None, Query(alias="schema")] = None,
) -> list[PageSummary]:
    return [PageSummary.of(page) for page in await backend.store.list_pages(schema_name, status)]


# The labels' entity tag, which `PUT labels` takes back as `If-Match` so a pass never overwrites one it didn't see.
_ETAG = {"ETag": {"description": "Entity tag of the stored labels (RFC 9110 §8.8.3)", "schema": {"type": "string"}}}


@router.get("/pages/{page_id}", response_model=PageDetail, responses={200: {"headers": _ETAG}, 404: PROBLEM_RESPONSE})
async def get_page(page_id: EvalPageId, backend: Backend, response: Response) -> PageDetail:
    try:
        page = await backend.store.get_page(page_id)
    except EvalNotFound as e:
        raise _not_found(page_id) from e
    try:
        bundle, fields = await asyncio.gather(
            backend.store.get_bundle(page.capture_id), backend.schema_fields(page.schema_id)
        )
    except (ObjectNotFound, CorruptBundle) as e:
        # The page's row exists but its stored capture is missing or damaged: the server's fault, not the request's.
        detail = f"the capture {page.capture_id} of dev eval page {page.id} cannot be read"
        raise ProblemError(500, "capture_unreadable", "Capture unreadable", detail) from e
    response.headers["ETag"] = _etag(page)
    return PageDetail(
        **PageSummary.of(page).model_dump(),
        labels=Labels.model_validate(page.labels) if page.labels else None,
        fields=fields,
        url=bundle.manifest.url,
        final_url=bundle.manifest.final_url,
        bundle_html=await asyncio.to_thread(sanitize_html, bundle),  # parsing is synchronous
        text=None,
    )


# The body is read as plain JSON so that `parse_labels` reports every error with its path (§4.11); the document
# still declares it as `Labels`, so the generated client types it.
_LABELS_BODY = {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Labels"}}}, "required": True}


@router.put(
    "/pages/{page_id}/labels",
    response_model=PageSummary,
    responses={
        200: {"headers": _ETAG},
        404: PROBLEM_RESPONSE,
        409: PROBLEM_RESPONSE,
        412: PROBLEM_RESPONSE,
    },
    openapi_extra={"requestBody": _LABELS_BODY},
)
async def put_labels(
    page_id: EvalPageId,
    labels: Annotated[dict[str, JsonValue], Body()],
    backend: Backend,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> PageSummary:
    """Store one pass of labels (§16.2). `status` `draft` or `labeled` is the labeler's pass and clears any check;
    `checked` is the checker's pass over a labeled page, by someone other than its labeler.

    With `If-Match` set to the `ETag` of the page as read, a pass over labels that have changed since is refused
    with 412 (RFC 9110 §13.1.1); a pass that races another store between this request's read and write is 409."""
    try:
        page = await backend.store.get_page(page_id)
    except EvalNotFound as e:
        raise _not_found(page_id) from e
    if if_match is not None and not _if_match(if_match, _etag(page)):
        raise _labels_changed(412)
    try:
        parsed = parse_labels(labels, page.page_kind, await backend.schema_fields(page.schema_id))
    except InvalidLabels as e:
        raise _invalid("the labels are invalid", e.errors) from e
    match _pass(parsed, page):
        case LabelError() as error:
            raise _invalid("the labels are invalid", [error])
        case (who, pass_):
            # A checker pass keeps the labeler's name as stored (`_pass` matches it casefolded).
            stored = parsed.model_dump(mode="json") | ({"labeler": page.labeler} if parsed.status == "checked" else {})
            try:
                await backend.store.put_labels(page.id, stored, who, pass_, expected=page.labels)
            except LabelsChanged as e:
                raise _labels_changed(409) from e
            # As the store records it: a labeler pass clears the checker.
            people = {pass_: who} | ({"checker": None} if parsed.status != "checked" else {})
            updated = page.model_copy(update={"labels": stored, **people})
            response.headers["ETag"] = _etag(updated)
            return PageSummary.of(updated)


def _pass(labels: Labels, page: EvalPageRow) -> tuple[str, LabelPass] | LabelError:
    """Whose pass the labels are and which pass it is, or why they may not be stored over `page`'s."""
    if labels.status != "checked":
        if labels.labeler is None:
            return LabelError("labeler", "a labeler pass names its labeler")
        return labels.labeler, "labeler"
    if _status(page) not in ("labeled", "checked"):
        return LabelError("status", "only a labeled page can be checked")
    if page.labeler is None or labels.labeler is None or not same_person(labels.labeler, page.labeler):
        return LabelError("labeler", f"a checker pass keeps the page's labeler ({page.labeler})")
    if labels.checker is None:  # `parse_labels` refuses a checked page without a checker
        return LabelError("checker", "a checker pass names its checker")
    return labels.checker, "checker"


@router.post("/pages/{page_id}/normalize", status_code=200, responses={501: PROBLEM_RESPONSE})
async def normalize(page_id: EvalPageId, body: NormalizeRequest) -> None:
    """The field type's normalized value for `raw_text`, or its reason to decline. The normalizers arrive with
    SPEC-04 PRs 2 to 8."""
    raise _not_implemented("the type normalizers are not built yet (SPEC-04)")


@router.post("/pages/{page_id}/prefill", status_code=200, responses={501: PROBLEM_RESPONSE})
async def prefill(page_id: EvalPageId) -> None:
    """Store a `draft` filled by the LLM pre-fill hook. The hook arrives with SPEC-06."""
    raise _not_implemented("the LLM pre-fill hook is not built yet (SPEC-06)")


@router.post("/capture", response_model=CaptureResponse)
async def capture(body: CaptureRequest, backend: Backend) -> CaptureResponse:
    """`crawlerai eval capture` into dev (§4.4): fetch each URL and store it as an unlabeled dev page."""
    try:
        check_urls(body.urls)
        outcomes = await backend.capture(
            [PageRequest(n, url, body.schema_name, body.category) for n, url in enumerate(body.urls, start=1)],
            body.page_kind,
        )
    except EvalCliError as e:
        raise _invalid(str(e)) from e
    return CaptureResponse(outcomes=[_outcome(outcome) for outcome in outcomes])


def _outcome(outcome: Outcome) -> CapturedOut | SkippedOut:
    match outcome:
        case Captured():
            return CapturedOut(**asdict(outcome))
        case Skipped():
            return SkippedOut(**asdict(outcome))
        case _:
            assert_never(outcome)


# HTML elements that run script or embed another browsing context (HTML Living Standard §4.8, §4.12.1), and the
# `meta http-equiv` pragmas, which can refresh or redirect the document (§4.2.5.3).
_ACTIVE = "script, iframe, frame, frameset, object, embed, meta[http-equiv]"


def sanitize_html(bundle: CaptureBundle) -> str:
    """The captured page, safe to show in a sandboxed `srcdoc` iframe: no script or embedded content, no event
    handler attributes (HTML §8.1.8.2: `on*`), no `javascript:` URLs (HTML §7.11.1), and one `<base href>` at the
    capture's final URL, or at the page's own base resolved against it, so relative images load (D-0012)."""
    tree = LexborHTMLParser(decode_body(bundle))
    base_url = bundle.manifest.final_url
    page_base = tree.css_first("base[href]")
    if page_base is not None:
        base_url = urljoin(base_url, page_base.attributes.get("href") or "")
    for node in tree.css(f"{_ACTIVE}, base"):
        node.decompose()
    if tree.root is not None:
        remove_scripting_attributes(tree.root)
    head, base = tree.head, LexborHTMLParser("<base>").css_first("base")
    if head is None or base is None:
        raise RuntimeError("the HTML parser creates `head` in every document")
    base.attrs["href"] = base_url
    head.insert_child(base)
    return tree.html or ""
