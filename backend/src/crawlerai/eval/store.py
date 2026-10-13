"""Eval stores (SPEC-03 §4.2, C1, INV-01). Dev cases live in the main database and object store (`eval/dev/`);
hidden and fresh cases live only in the private database and object store root, which only custodian credentials
reach. Both implement `EvalStore`, and `get_store` picks one for a split.

A capture's bundle is written before the row that names it, so a row never names a missing bundle; a failure in
between leaves an unreferenced object, which nothing reads. Writing the same capture or cache entry again converges.
"""

import asyncio
import re
from abc import ABC, abstractmethod
from typing import Any, Literal, Protocol, assert_never
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Select, Table, delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import make_url
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
    PrivateSplit,
    Project,
    SchemaId,
    Site,
    Split,
)
from crawlerai.db.private_models import EvalCapture, EvalLlmCache, PrivateBase, PrivateEvalPage, PrivateEvalRun
from crawlerai.eval.labels import LabelStatus
from crawlerai.storage import open_store
from crawlerai.storage.base import ObjectNotFound, ObjectStore
from crawlerai.storage.capture_bundle import (
    SHA256_PATTERN,
    CaptureBundle,
    decode,
    dev_eval_capture_key,
    encode,
    private_eval_capture_key,
)

# The label document of SPEC-03 §4.3, stored as given: callers validate it first (`crawlerai.eval.labels`).
Labels = dict[str, JsonValue]
LabelPass = Literal["labeler", "checker"]


class EvalNotFound(LookupError):
    """No eval page, eval capture or eval run of this store's split has the id."""


class LabelsChanged(Exception):
    """The page's labels are no longer the ones the pass was made over: another pass was stored since."""


class PrivateCredentialsMissing(Exception):
    """The private eval settings are empty. That is the normal state everywhere but on custodian machines and in the
    protected CI job (C1)."""


class PrivateStoreNotSeparate(Exception):
    """The private eval settings name the main database, or an object root overlapping the main one (INV-01)."""


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

    async def latest_run(self, git_sha_on_main: str | None) -> EvalRunRow | None:
        """The latest run of this split, of commit `git_sha_on_main` when given."""

    async def llm_cache_get(self, key: str) -> bytes | None: ...

    async def llm_cache_put(self, key: str, value: bytes) -> None: ...

    async def aclose(self) -> None:
        """Close the store's database connections."""


def get_store(split: Split, settings: Settings) -> "DevEvalStore | PrivateEvalStore":
    match split:
        case "dev":
            return dev_store(settings)
        case "hidden" | "fresh":
            return private_store(split, settings)
        case _:
            assert_never(split)


def dev_store(settings: Settings) -> "DevEvalStore":
    return DevEvalStore(
        create_async_engine(settings.database_url.get_secret_value()), open_store(settings.object_store)
    )


def private_store(split: PrivateSplit, settings: Settings) -> "PrivateEvalStore":
    database_url, object_store = settings.eval_private_database_url, settings.eval_private_object_store
    if database_url is None or object_store is None:
        raise PrivateCredentialsMissing(
            f"the {split} split needs CRAWLERAI_EVAL_PRIVATE_DATABASE_URL and"
            " CRAWLERAI_EVAL_PRIVATE_OBJECT_STORE. They are set only for custodians (C1), so this is"
            " expected on any other machine."
        )
    # A sanity check against misconfiguration; what keeps `app` out is the role grant (init.sql).
    if _same_database(settings.database_url.get_secret_value(), database_url.get_secret_value()):
        raise PrivateStoreNotSeparate("the private eval database is the main database")
    if _nested(settings.object_store, object_store):
        raise PrivateStoreNotSeparate("the private object store overlaps the main one")
    return PrivateEvalStore(split, create_async_engine(database_url.get_secret_value()), open_store(object_store))


def _same_database(a_url: str, b_url: str) -> bool:
    a, b = make_url(a_url), make_url(b_url)
    return (a.host, a.port, a.database) == (b.host, b.port, b.database)


def _nested(a: str, b: str) -> bool:
    """Whether one object store URL is the other or lies under it."""
    a, b = a.rstrip("/") + "/", b.rstrip("/") + "/"
    return a.startswith(b) or b.startswith(a)


def _check_llm_key(key: str) -> str:
    # sha256(role, model, prompt, schema) in hex (SPEC-03 §4.5); the key becomes part of an object key.
    if not re.fullmatch(SHA256_PATTERN, key):
        raise ValueError(f"invalid LLM cache key {key!r}: expected a lowercase hex sha256")
    return key


def _capture_columns(bundle: CaptureBundle, object_key: str, size_bytes: int) -> dict[str, Any]:
    """The columns `capture` and `eval_capture` share, from the bundle alone."""
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
        # The fetchers record the whole fetch as `total` (SPEC-02 §4.2).
        "duration_ms": manifest.timings_ms["total"],
        "fetch_policy": manifest.fetch_policy,
    }


def _host(bundle: CaptureBundle) -> str:
    host = urlsplit(bundle.manifest.url).hostname  # lowercased
    if not host:
        raise ValueError("the capture URL has no host")
    return host


class _SqlEvalStore(ABC):
    """What both stores share: pages and runs in one database, bundles and LLM responses in one object store."""

    _page: Table
    _run: Table

    def __init__(self, split: Split, engine: AsyncEngine, objects: ObjectStore) -> None:
        self._split: Split = split
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

    @abstractmethod
    async def _capture_key(self, conn: AsyncConnection, capture_id: CaptureId) -> str | None:
        """The object key of this store's capture `capture_id`, if it has one."""

    @abstractmethod
    def _hosts_query(self) -> Select[str]:
        """The distinct hosts of this split's pages' captures."""

    async def hosts(self) -> set[str]:
        """The hosts of this split's pages' captures. For comparing splits only: callers never print them (C1)."""
        async with self._engine.connect() as conn:
            return set((await conn.execute(self._hosts_query())).scalars())

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
        for unreadable bytes: replay counts each as a dropped page (SPEC-03 §4.11)."""
        async with self._engine.connect() as conn:
            key = await self._capture_key(conn, capture_id)
        if key is None:
            raise EvalNotFound(f"no {self._split} eval capture {capture_id}")
        return await asyncio.to_thread(lambda: decode(self._objects.get(key)))

    async def put_page(self, page: EvalPageRow) -> EvalPageId:
        if page.split != self._split:
            raise ValueError(f"a {page.split} page cannot be stored in the {self._split} store")
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
        if run.split != self._split:
            raise ValueError(f"a {run.split} run cannot be stored in the {self._split} store")
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

    async def latest_run(self, git_sha_on_main: str | None) -> EvalRunRow | None:
        run = self._run.c
        query = select(self._run).where(run.split == self._split).order_by(run.created_at.desc(), run.id.desc())
        if git_sha_on_main is not None:
            query = query.where(run.git_sha == git_sha_on_main)
        async with self._engine.connect() as conn:
            row = (await conn.execute(query.limit(1))).mappings().one_or_none()
        if row is None:
            return None
        return _row(EvalRunRow, row)


def _row[R: _Row](model: type[R], row: Any) -> R:
    """`model` from a table row, which may have columns the model leaves out (`created_at`)."""
    return model.model_validate({name: row[name] for name in model.model_fields})


class DevEvalStore(_SqlEvalStore):
    """Dev cases: `eval_page` and `eval_run` in the main database, captures in `capture` with no expiry, bundles at
    `eval/dev/{capture_id}.bundle.zst` and LLM responses at `eval/dev/llm/{key}.json` in the main store."""

    _page = Base.metadata.tables[EvalPage.__tablename__]
    _run = Base.metadata.tables[EvalRun.__tablename__]

    def __init__(self, engine: AsyncEngine, objects: ObjectStore) -> None:
        super().__init__("dev", engine, objects)

    async def _capture_key(self, conn: AsyncConnection, capture_id: CaptureId) -> str | None:
        # A dev eval capture is stored under `eval/dev/` and never expires (SPEC-01 §4.4). A production capture,
        # even one written without an expiry, is not an eval capture.
        key = dev_eval_capture_key(capture_id)
        query = select(Capture.object_key).where(
            Capture.id == capture_id, Capture.object_key == key, Capture.expires_at.is_(None)
        )
        return (await conn.execute(query)).scalar_one_or_none()

    def _hosts_query(self) -> Select[str]:
        page = self._page.c
        return (
            select(Site.host)
            .distinct()
            .join(Capture, Capture.site_id == Site.id)
            .join(self._page, page.capture_id == Capture.id)
            .where(page.split == self._split)
        )

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


class PrivateEvalStore(_SqlEvalStore):
    """Hidden or fresh cases (C1): the private database's tables, bundles at `{split}/{capture_id}.bundle.zst` and
    LLM responses at `llm/{key}.json` in the private object store root. The LLM cache is shared by both splits."""

    _page = PrivateBase.metadata.tables[PrivateEvalPage.__tablename__]
    _run = PrivateBase.metadata.tables[PrivateEvalRun.__tablename__]

    def __init__(self, split: PrivateSplit, engine: AsyncEngine, objects: ObjectStore) -> None:
        super().__init__(split, engine, objects)
        self._private_split = split

    async def _capture_key(self, conn: AsyncConnection, capture_id: CaptureId) -> str | None:
        query = select(EvalCapture.object_key).where(EvalCapture.id == capture_id, EvalCapture.split == self._split)
        return (await conn.execute(query)).scalar_one_or_none()

    async def put_capture(self, bundle: CaptureBundle, category: EvalCategory) -> CaptureId:
        key = private_eval_capture_key(self._private_split, bundle.manifest.capture_id)
        size_bytes = await self._put_bundle(key, bundle)
        async with self._engine.begin() as conn:
            await conn.execute(
                pg_insert(EvalCapture)
                .values(
                    split=self._split,
                    host=_host(bundle),
                    category=category,
                    **_capture_columns(bundle, key, size_bytes),
                )
                .on_conflict_do_nothing(index_elements=[EvalCapture.id])
            )
        return CaptureId(bundle.manifest.capture_id)

    def _hosts_query(self) -> Select[str]:
        page = self._page.c
        return (
            select(EvalCapture.host)
            .distinct()
            .join(self._page, (page.capture_id == EvalCapture.id) & (page.split == EvalCapture.split))
            .where(EvalCapture.split == self._split)
        )

    async def pages_by_host(self) -> dict[str, list[EvalPageRow]]:
        """This split's pages grouped by the host of their capture, in page order. Hosts are for grouping only: callers
        never print them (C1)."""
        page = self._page.c
        query = (
            select(self._page, EvalCapture.host)
            .join(EvalCapture, (EvalCapture.id == page.capture_id) & (EvalCapture.split == page.split))
            .where(page.split == self._split)
            .order_by(page.id)
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(query)).mappings().all()
        sites: dict[str, list[EvalPageRow]] = {}
        for row in rows:
            sites.setdefault(row["host"], []).append(_row(EvalPageRow, row))
        return sites

    async def remove_page(self, page_id: EvalPageId) -> None:
        """Delete the page, and its capture and bundle once no page of this split names the capture. Removing a
        missing page is a no-op, so an interrupted move can be re-run."""
        page = self._page.c
        async with self._engine.begin() as conn:
            capture_id = (
                await conn.execute(
                    delete(self._page).where(page.id == page_id, page.split == self._split).returning(page.capture_id)
                )
            ).scalar_one_or_none()
            if capture_id is None:
                return
            still_named = select(page.id).where(page.capture_id == capture_id).exists()
            object_key = (
                await conn.execute(
                    delete(EvalCapture)
                    .where(EvalCapture.id == capture_id, EvalCapture.split == self._split, ~still_named)
                    .returning(EvalCapture.object_key)
                )
            ).scalar_one_or_none()
        # After the row: a failure here leaves an unreferenced object, which nothing reads.
        if object_key is not None:
            await asyncio.to_thread(self._objects.delete, object_key)

    async def llm_cache_get(self, key: str) -> bytes | None:
        query = select(EvalLlmCache.object_key).where(EvalLlmCache.key == _check_llm_key(key))
        async with self._engine.connect() as conn:
            object_key = (await conn.execute(query)).scalar_one_or_none()
        if object_key is None:
            return None
        return await asyncio.to_thread(self._objects.get, object_key)

    async def llm_cache_put(self, key: str, value: bytes) -> None:
        object_key = f"llm/{_check_llm_key(key)}.json"
        await asyncio.to_thread(self._objects.put, object_key, value)
        async with self._engine.begin() as conn:
            await conn.execute(
                pg_insert(EvalLlmCache)
                .values(key=key, object_key=object_key, size_bytes=len(value))
                .on_conflict_do_update(index_elements=[EvalLlmCache.key], set_={"size_bytes": len(value)})
            )
