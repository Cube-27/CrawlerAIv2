"""The eval store: the golden set's pages, captures, runs and recorded LLM responses, in the main database and
object store (`eval/dev/`). `EvalStore` is the part the replay harness, the capture commands and the labeling API read.

A capture's bundle is written before the row that names it, so a row never names a missing bundle; a failure in
between leaves an unreferenced object, which nothing reads. Writing the same capture or cache entry again converges.
"""

import asyncio
import re
from typing import Any, Literal, Protocol, assert_never
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Table, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from crawlerai.core.ids import uuid7
from crawlerai.core.settings import Settings
from crawlerai.db.models import (
    Base,
    Capture,
    CaptureId,
    EvalCategory,
    EvalPage,
    EvalPageId,
    EvalRun,
    EvalRunId,
    PageKind,
    Project,
    SchemaId,
    Site,
    Split,
)
from crawlerai.eval.labels import LabelStatus
from crawlerai.storage import open_store
from crawlerai.storage.base import ObjectNotFound, ObjectStore
from crawlerai.storage.capture_bundle import (
    SHA256_PATTERN,
    CaptureBundle,
    decode,
    dev_eval_capture_key,
    encode,
)

# The label document of evaluation spec, stored as given: callers validate it first (`crawlerai.eval.labels`).
Labels = dict[str, JsonValue]
LabelPass = Literal["labeler", "checker"]


class EvalNotFound(LookupError):
    """No eval page, eval capture or eval run of this store's split has the id."""


class LabelsChanged(Exception):
    """The page's labels are no longer the ones the pass was made over: another pass was stored since."""


class _Row(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EvalPageRow(_Row):
    id: EvalPageId = Field(default_factory=lambda: EvalPageId(uuid7()))
    capture_id: CaptureId
    split: Split
    schema_id: SchemaId
    schema_name: str
    page_kind: PageKind
    category: EvalCategory
    labels: Labels = Field(default_factory=dict)
    labeler: str | None = None
    checker: str | None = None
    config_snapshot: dict[str, JsonValue] | None = None


class EvalRunRow(_Row):
    id: EvalRunId = Field(default_factory=lambda: EvalRunId(uuid7()))
    split: Split
    engine_version: str
    git_sha: str
    metrics: dict[str, JsonValue]


class EvalStore(Protocol):
    @property
    def split(self) -> Split: ...

    async def list_pages(
        self, schema_name: str | None = None, status: LabelStatus | None = None
    ) -> list[EvalPageRow]: ...

    async def get_page(self, page_id: EvalPageId) -> EvalPageRow: ...

    async def get_bundle(self, capture_id: CaptureId) -> CaptureBundle: ...

    async def put_capture(self, bundle: CaptureBundle, category: EvalCategory) -> CaptureId: ...

    async def put_page(self, page: EvalPageRow) -> EvalPageId: ...

    async def put_labels(
        self, page_id: EvalPageId, labels: Labels, who: str | None, pass_: LabelPass, *, expected: Labels
    ) -> None:
        """Store `labels` as `who`'s pass over the page's labels `expected`, or raise `LabelsChanged` when the page
        holds others by then. A labeler pass clears the checker: the labels it checked have changed. `who` is None
        only for a pre-fill draft, which no person made."""

    async def put_run(self, run: EvalRunRow) -> EvalRunId: ...

    async def get_run(self, run_id: EvalRunId) -> EvalRunRow: ...

    async def llm_cache_get(self, key: str) -> bytes | None: ...

    async def llm_cache_put(self, key: str, value: bytes) -> None: ...

    async def aclose(self) -> None:
        """Close the store's database connections."""


def dev_store(settings: Settings) -> "DevEvalStore":
    return DevEvalStore(
        create_async_engine(settings.database_url.get_secret_value()), open_store(settings.object_store)
    )


def _check_llm_key(key: str) -> str:
    # sha256(role, model, prompt, schema) in hex (evaluation spec); the key becomes part of an object key.
    if not re.fullmatch(SHA256_PATTERN, key):
        raise ValueError(f"invalid LLM cache key {key!r}: expected a lowercase hex sha256")
    return key


def _capture_columns(bundle: CaptureBundle, object_key: str, size_bytes: int) -> dict[str, Any]:
    """The `capture` columns that come from the bundle alone."""
    manifest = bundle.manifest
    return {
        "id": manifest.capture_id,
        "url": manifest.url,
        "fetched_at": manifest.fetched_at,
        "method": manifest.method,
        "status_code": manifest.status_code,
        "final_url": manifest.final_url,
        "block_class": manifest.block_class,
        "object_key": object_key,
        "html_sha256": manifest.html_sha256,
        "size_bytes": size_bytes,
        # The fetchers record the whole fetch as `total` (acquisition spec).
        "duration_ms": manifest.timings_ms["total"],
        "fetch_policy": manifest.fetch_policy,
    }


def _host(bundle: CaptureBundle) -> str:
    host = urlsplit(bundle.manifest.url).hostname  # lowercased
    if not host:
        raise ValueError("the capture URL has no host")
    return host


def _row[R: _Row](model: type[R], row: Any) -> R:
    """`model` from a table row, which may have columns the model leaves out (`created_at`)."""
    return model.model_validate({name: row[name] for name in model.model_fields})


class DevEvalStore:
    """The golden set: `eval_page` and `eval_run` in the main database, captures in `capture` with no expiry, bundles at
    `eval/dev/{capture_id}.bundle.zst` and LLM responses at `eval/dev/llm/{key}.json` in the main store."""

    _page: Table = Base.metadata.tables[EvalPage.__tablename__]
    _run: Table = Base.metadata.tables[EvalRun.__tablename__]

    def __init__(self, engine: AsyncEngine, objects: ObjectStore) -> None:
        self._split: Split = "dev"
        self._engine = engine
        self._objects = objects

    @property
    def split(self) -> Split:
        return self._split

    async def _put_bundle(self, key: str, bundle: CaptureBundle) -> int:
        """Encode and write the bundle off the event loop (it compresses, and the store is synchronous); its size."""

        def write() -> int:
            blob = encode(bundle)
            self._objects.put(key, blob)
            return len(blob)

        return await asyncio.to_thread(write)

    async def aclose(self) -> None:
        await self._engine.dispose()

    async def list_pages(self, schema_name: str | None = None, status: LabelStatus | None = None) -> list[EvalPageRow]:
        page = self._page.c
        query = select(self._page).where(page.split == self._split).order_by(page.id)
        if schema_name is not None:
            query = query.where(page.schema_name == schema_name)
        if status is not None:
            query = query.where(page.labels["status"].astext == status)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(query)).mappings().all()
        return [_row(EvalPageRow, row) for row in rows]

    async def get_page(self, page_id: EvalPageId) -> EvalPageRow:
        query = select(self._page).where(self._page.c.id == page_id, self._page.c.split == self._split)
        async with self._engine.connect() as conn:
            row = (await conn.execute(query)).mappings().one_or_none()
        if row is None:
            raise EvalNotFound(f"no {self._split} eval page {page_id}")
        return _row(EvalPageRow, row)

    async def get_bundle(self, capture_id: CaptureId) -> CaptureBundle:
        """Raise `EvalNotFound` for an unknown capture, `ObjectNotFound` for a missing bundle and `CorruptBundle`
        for unreadable bytes: replay counts each as a dropped page (evaluation spec)."""
        async with self._engine.connect() as conn:
            key = await self._capture_key(conn, capture_id)
        if key is None:
            raise EvalNotFound(f"no {self._split} eval capture {capture_id}")
        return await asyncio.to_thread(lambda: decode(self._objects.get(key)))

    async def put_page(self, page: EvalPageRow) -> EvalPageId:
        async with self._engine.begin() as conn:
            if await self._capture_key(conn, page.capture_id) is None:
                raise EvalNotFound(f"no {self._split} eval capture {page.capture_id}")
            await conn.execute(insert(self._page).values(page.model_dump()))
        return page.id

    async def put_labels(
        self, page_id: EvalPageId, labels: Labels, who: str | None, pass_: LabelPass, *, expected: Labels
    ) -> None:
        match pass_:
            case "labeler":
                people = {"labeler": who, "checker": None}
            case "checker":
                people = {"checker": who}
            case _:
                assert_never(pass_)
        page = self._page.c
        # Compare-and-set: the update applies only over the labels the pass was made over (jsonb equality).
        query = (
            update(self._page)
            .where(page.id == page_id, page.split == self._split, page.labels == expected)
            .values(labels=labels, **people)
            .returning(page.id)
        )
        async with self._engine.begin() as conn:
            if (await conn.execute(query)).one_or_none() is None:
                exists = select(page.id).where(page.id == page_id, page.split == self._split)
                if (await conn.execute(exists)).one_or_none() is None:
                    raise EvalNotFound(f"no {self._split} eval page {page_id}")
                raise LabelsChanged(f"the labels of {self._split} eval page {page_id} changed since they were read")

    async def put_run(self, run: EvalRunRow) -> EvalRunId:
        async with self._engine.begin() as conn:
            await conn.execute(insert(self._run).values(run.model_dump()))
        return run.id

    async def get_run(self, run_id: EvalRunId) -> EvalRunRow:
        query = select(self._run).where(self._run.c.id == run_id, self._run.c.split == self._split)
        async with self._engine.connect() as conn:
            row = (await conn.execute(query)).mappings().one_or_none()
        if row is None:
            raise EvalNotFound(f"no {self._split} eval run {run_id}")
        return _row(EvalRunRow, row)

    async def _capture_key(self, conn: AsyncConnection, capture_id: CaptureId) -> str | None:
        # A dev eval capture is stored under `eval/dev/` and never expires (persistence-storage spec). A production
        # capture, even one written without an expiry, is not an eval capture.
        key = dev_eval_capture_key(capture_id)
        query = select(Capture.object_key).where(
            Capture.id == capture_id, Capture.object_key == key, Capture.expires_at.is_(None)
        )
        return (await conn.execute(query)).scalar_one_or_none()

    async def pages_by_url(self) -> dict[str, EvalPageRow]:
        """The pages by the URL their capture requested, in page order; the first page wins for a URL captured twice."""
        page = self._page.c
        query = (
            select(self._page, Capture.url.label("capture_url"))
            .join(Capture, Capture.id == page.capture_id)
            .where(page.split == self._split)
            .order_by(page.id)
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(query)).mappings().all()
        found: dict[str, EvalPageRow] = {}
        for row in rows:
            found.setdefault(row["capture_url"], _row(EvalPageRow, row))
        return found

    async def page_urls(self) -> set[str]:
        """The URLs of this split's pages' captures, as they were requested."""
        page = self._page.c
        query = select(Capture.url).distinct().join(self._page, page.capture_id == Capture.id)
        async with self._engine.connect() as conn:
            return set((await conn.execute(query.where(page.split == self._split))).scalars())

    async def put_capture(self, bundle: CaptureBundle, category: EvalCategory) -> CaptureId:
        """`category` is kept on the page (`put_page`); the main database records sites without one."""
        key = dev_eval_capture_key(bundle.manifest.capture_id)
        size_bytes = await self._put_bundle(key, bundle)
        host = _host(bundle)
        async with self._engine.begin() as conn:
            default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
            await conn.execute(
                pg_insert(Site)
                .values(project_id=default_project, host=host)
                .on_conflict_do_nothing(index_elements=[Site.host])
            )
            site_id = (await conn.execute(select(Site.id).where(Site.host == host))).scalar_one()
            await conn.execute(
                pg_insert(Capture)
                .values(site_id=site_id, expires_at=None, **_capture_columns(bundle, key, size_bytes))
                .on_conflict_do_nothing(index_elements=[Capture.id])
            )
        return CaptureId(bundle.manifest.capture_id)

    async def llm_cache_get(self, key: str) -> bytes | None:
        try:
            return await asyncio.to_thread(self._objects.get, _dev_llm_key(key))
        except ObjectNotFound:
            return None

    async def llm_cache_put(self, key: str, value: bytes) -> None:
        # One object per key, written whole (`ObjectStore.put`), so a reader sees all of it or a miss.
        await asyncio.to_thread(self._objects.put, _dev_llm_key(key), value)


def _dev_llm_key(key: str) -> str:
    return f"eval/dev/llm/{_check_llm_key(key)}.json"
