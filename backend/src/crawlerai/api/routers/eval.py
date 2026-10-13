"""Labeling endpoints (SPEC-03 §4.10), mounted only with `CRAWLERAI_EVAL_UI=true`.

They serve the dev split only. Hidden and fresh cases never reach the main API (C1, INV-01): the backend holds a
`DevEvalStore` and nothing else, and a request naming another split is refused before any store is touched.

Labels are validated before anything is stored (`parse_labels`), and every error comes back with its field and
reason as an RFC 9457 problem (§4.11). SPEC-07 moves the problem model to `api.dto` and adds API-key auth.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict
from email.message import Message
from typing import Annotated, Literal, Protocol, assert_never, get_args
from urllib.parse import urljoin

from fastapi import APIRouter, Body, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from selectolax.lexbor import LexborHTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.core.capture import BlockClass
from crawlerai.core.settings import Settings
from crawlerai.db.models import CaptureId, EvalCategory, EvalPageId, PageKind, SchemaDef, SchemaId
from crawlerai.eval.cli import Captured, EvalCliError, Outcome, PageRequest, Skipped, check_urls, run_capture
from crawlerai.eval.labels import FieldShape, InvalidLabels, LabelError, Labels, LabelStatus, field_shapes, parse_labels
from crawlerai.eval.store import DevEvalStore, EvalNotFound, EvalPageRow, EvalStore, LabelPass
from crawlerai.storage import open_store
from crawlerai.storage.capture_bundle import CaptureBundle

# `POST /capture` fetches within the request, one polite fetch at a time, so a request stays short.
MAX_CAPTURE_URLS = 20


class LabelingBackend(Protocol):
    @property
    def store(self) -> EvalStore: ...

    async def schema_fields(self, schema_id: SchemaId) -> dict[str, FieldShape]: ...

    async def capture(self, requests: Sequence[PageRequest], page_kind: PageKind) -> list[Outcome]: ...

    async def aclose(self) -> None: ...


class DevLabelingBackend:
    """The dev store, `schema_def` in the main database, and `eval capture` into dev. Private settings, even when
    present, are never read."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine = create_async_engine(settings.database_url.get_secret_value())
        self._store = DevEvalStore(self._engine, open_store(settings.object_store))

    @property
    def store(self) -> DevEvalStore:
        return self._store

    async def schema_fields(self, schema_id: SchemaId) -> dict[str, FieldShape]:
        async with self._engine.connect() as conn:
            fields: dict[str, JsonValue] = (
                await conn.execute(select(SchemaDef.fields).where(SchemaDef.id == schema_id))
            ).scalar_one()
        return field_shapes(fields)

    async def capture(self, requests: Sequence[PageRequest], page_kind: PageKind) -> list[Outcome]:
        return await run_capture(self._settings, "dev", requests, page_kind)

    async def aclose(self) -> None:
        await self._engine.dispose()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    backend = DevLabelingBackend(Settings())
    app.state.labeling_backend = backend
    try:
        yield
    finally:
        await backend.aclose()


def labeling_backend(request: Request) -> LabelingBackend:
    backend: LabelingBackend = request.app.state.labeling_backend
    return backend


Backend = Annotated[LabelingBackend, Depends(labeling_backend)]

router = APIRouter(prefix="/v1/eval", tags=["eval"], lifespan=_lifespan)


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FieldErrorOut(_Model):
    field: str  # dotted path in the request body; "" for the whole document
    reason: str


class Problem(_Model):
    """RFC 9457 problem details (SPEC-07 §4.3)."""

    type: str
    title: str
    status: int
    detail: str
    errors: list[FieldErrorOut] = []


def _problem(status: int, type_: str, title: str, detail: str, errors: Sequence[LabelError] = ()) -> JSONResponse:
    problem = Problem(
        type=type_,
        title=title,
        status=status,
        detail=detail,
        errors=[FieldErrorOut(field=e.path, reason=e.reason) for e in errors],
    )
    return JSONResponse(problem.model_dump(), status_code=status, media_type="application/problem+json")


def _invalid(detail: str, errors: Sequence[LabelError] = ()) -> JSONResponse:
    return _problem(422, "validation", "Invalid request", detail, errors)


def _not_found(page_id: EvalPageId) -> JSONResponse:
    return _problem(404, "not_found", "Not found", f"no dev eval page {page_id}")


_STATUSES: dict[str, LabelStatus] = {status: status for status in get_args(LabelStatus)}


def _status(page: EvalPageRow) -> LabelStatus | None:
    """The stored labels' status; None for a page not labeled yet."""
    status = page.labels.get("status")
    return _STATUSES.get(status) if isinstance(status, str) else None


class PageSummary(_Model):
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
    url: str
    final_url: str
    bundle_html: str  # sanitized; see `sanitize_html`
    text: str | None  # the cleaned text that `text:` locators index; arrives with SPEC-05 PR 1


class NormalizeRequest(_Model):
    field: str
    raw_text: str


class CaptureRequest(_Model):
    split: Literal["dev"]
    schema_name: str = Field(alias="schema")
    page_kind: PageKind
    category: EvalCategory
    urls: list[str] = Field(min_length=1, max_length=MAX_CAPTURE_URLS)


class CapturedOut(_Model):
    kind: Literal["captured"] = "captured"
    n: int  # the URL's position in the request, from 1
    capture_id: CaptureId
    page_id: EvalPageId
    status_code: int
    block_class: BlockClass
    error: str | None


class SkippedOut(_Model):
    kind: Literal["skipped"] = "skipped"
    n: int
    reason: str


class CaptureResponse(_Model):
    outcomes: list[Annotated[CapturedOut | SkippedOut, Field(discriminator="kind")]]


_PROBLEM = {"model": Problem, "content": {"application/problem+json": {}}}


@router.get("/pages", response_model=list[PageSummary])
async def list_pages(
    backend: Backend,
    split: Literal["dev"] = "dev",  # §4.10's filter; the API serves no other split (C1)
    status: LabelStatus | None = None,
    schema_name: Annotated[str | None, Query(alias="schema")] = None,
) -> list[PageSummary]:
    return [PageSummary.of(page) for page in await backend.store.list_pages(schema_name, status)]


@router.get("/pages/{page_id}", response_model=PageDetail, responses={404: _PROBLEM})
async def get_page(page_id: EvalPageId, backend: Backend) -> PageDetail | JSONResponse:
    try:
        page = await backend.store.get_page(page_id)
    except EvalNotFound:
        return _not_found(page_id)
    bundle = await backend.store.get_bundle(page.capture_id)
    return PageDetail(
        **PageSummary.of(page).model_dump(),
        labels=Labels.model_validate(page.labels) if page.labels else None,
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
    responses={404: _PROBLEM, 422: _PROBLEM},
    openapi_extra={"requestBody": _LABELS_BODY},
)
async def put_labels(
    page_id: EvalPageId, labels: Annotated[dict[str, JsonValue], Body()], backend: Backend
) -> PageSummary | JSONResponse:
    """Store one pass of labels (§16.2). `status` `draft` or `labeled` is the labeler's pass and clears any check;
    `checked` is the checker's pass over a labeled page, by someone other than its labeler."""
    try:
        page = await backend.store.get_page(page_id)
    except EvalNotFound:
        return _not_found(page_id)
    try:
        parsed = parse_labels(labels, page.page_kind, await backend.schema_fields(page.schema_id))
    except InvalidLabels as e:
        return _invalid("the labels are invalid", e.errors)
    match _pass(parsed, page):
        case LabelError() as error:
            return _invalid("the labels are invalid", [error])
        case (who, pass_):
            stored = parsed.model_dump(mode="json")
            await backend.store.put_labels(page.id, stored, who, pass_)
            # As the store records it: a labeler pass clears the checker.
            people = {pass_: who} | ({"checker": None} if parsed.status != "checked" else {})
            return PageSummary.of(page.model_copy(update={"labels": stored, **people}))


def _pass(labels: Labels, page: EvalPageRow) -> tuple[str, LabelPass] | LabelError:
    """Whose pass the labels are and which pass it is, or why they may not be stored over `page`'s."""
    if labels.status != "checked":
        if labels.labeler is None:
            return LabelError("labeler", "a labeler pass names its labeler")
        return labels.labeler, "labeler"
    if _status(page) not in ("labeled", "checked"):
        return LabelError("status", "only a labeled page can be checked")
    if labels.labeler != page.labeler:
        return LabelError("labeler", f"a checker pass keeps the page's labeler ({page.labeler})")
    if labels.checker is None:  # `parse_labels` refuses a checked page without a checker
        return LabelError("checker", "a checker pass names its checker")
    return labels.checker, "checker"


@router.post("/pages/{page_id}/normalize", status_code=200, responses={501: _PROBLEM})
async def normalize(page_id: EvalPageId, body: NormalizeRequest) -> JSONResponse:
    """The field type's normalized value for `raw_text`, or its reason to decline. The normalizers arrive with
    SPEC-04 PRs 2 to 8."""
    return _problem(501, "not_implemented", "Not implemented", "the type normalizers are not built yet (SPEC-04)")


@router.post("/pages/{page_id}/prefill", status_code=200, responses={501: _PROBLEM})
async def prefill(page_id: EvalPageId) -> JSONResponse:
    """Store a `draft` filled by the LLM pre-fill hook. The hook arrives with SPEC-06."""
    return _problem(501, "not_implemented", "Not implemented", "the LLM pre-fill hook is not built yet (SPEC-06)")


@router.post("/capture", response_model=CaptureResponse, responses={422: _PROBLEM})
async def capture(body: CaptureRequest, backend: Backend) -> CaptureResponse | JSONResponse:
    """`crawlerai eval capture` into dev (§4.4): fetch each URL and store it as an unlabeled dev page."""
    try:
        check_urls(body.urls)
        outcomes = await backend.capture(
            [PageRequest(n, url, body.schema_name, body.category) for n, url in enumerate(body.urls, start=1)],
            body.page_kind,
        )
    except EvalCliError as e:
        return _invalid(str(e))
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
    tree = LexborHTMLParser(_decode(bundle))
    base_url = bundle.manifest.final_url
    page_base = tree.css_first("base[href]")
    if page_base is not None:
        base_url = urljoin(base_url, page_base.attributes.get("href") or "")
    for node in tree.css(f"{_ACTIVE}, base"):
        node.decompose()
    for node in tree.root.traverse() if tree.root is not None else ():
        for name, value in list(node.attributes.items()):
            if name.lower().startswith("on") or (value or "").strip().lower().startswith("javascript:"):
                del node.attrs[name]
    head, base = tree.head, LexborHTMLParser("<base>").css_first("base")
    if head is None or base is None:
        raise RuntimeError("the HTML parser creates `head` in every document")
    base.attrs["href"] = base_url
    head.insert_child(base)
    return tree.html or ""


def _decode(bundle: CaptureBundle) -> str:
    """The body as text, in the charset its Content-Type names (RFC 9110 §8.3.2), else UTF-8 (the HTML default,
    §13.2.3.2); undecodable bytes become U+FFFD."""
    header = Message()
    for name, value in bundle.manifest.headers.response:
        if name.lower() == "content-type":
            header["content-type"] = value
            break
    try:
        return bundle.body.decode(header.get_content_charset() or "utf-8", errors="replace")
    except LookupError:  # a charset Python doesn't know
        return bundle.body.decode("utf-8", errors="replace")
