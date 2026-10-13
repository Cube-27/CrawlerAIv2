"""Eval stores (SPEC-03 §4.2, C1, INV-01). Dev cases live in the main database and object store (`eval/dev/`);
hidden and fresh cases live only in the private database and object store root, which only custodian credentials
reach. Both implement `EvalStore`, and `get_store` picks one for a split.

A capture's bundle is written before the row that names it, so a row never names a missing bundle; a failure in
between leaves an unreferenced object, which nothing reads. Writing the same capture or cache entry again converges.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Literal, Protocol, assert_never
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Table, insert, select, update
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
from crawlerai.storage import open_store
from crawlerai.storage.base import ObjectNotFound, ObjectStore
from crawlerai.storage.capture_bundle import CaptureBundle, decode, dev_eval_capture_key, encode

# The label document of SPEC-03 §4.3, stored as given; SPEC-03 PR 2 adds its model and validation.
Labels = dict[str, JsonValue]
LabelStatus = Literal["draft", "labeled", "checked"]
LabelPass = Literal["labeler", "checker"]


class EvalNotFound(LookupError):
    """No eval page, or no eval capture of this store's split, has the id."""


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

    async def put_labels(self, page_id: EvalPageId, labels: Labels, who: str, pass_: LabelPass) -> None:
        """Store `labels` as `who`'s pass. A labeler pass clears the checker: the labels it checked have changed."""

    async def put_run(self, run: EvalRunRow) -> EvalRunId: ...

    async def latest_run(self, git_sha_on_main: str | None) -> EvalRunRow | None:
        """The latest run of this split, of commit `git_sha_on_main` when given."""

    async def llm_cache_get(self, key: str) -> bytes | None: ...

    async def llm_cache_put(self, key: str, value: bytes) -> None: ...


def get_store(split: Split, settings: Settings) -> EvalStore:
    match split:
        case "dev":
            return DevEvalStore(
                create_async_engine(settings.database_url.get_secret_value()), open_store(settings.object_store)
            )
        case "hidden" | "fresh":
            database_url, object_store = settings.eval_private_database_url, settings.eval_private_object_store
            if database_url is None or object_store is None:
                raise PrivateCredentialsMissing(
                    f"the {split} split needs CRAWLERAI_EVAL_PRIVATE_DATABASE_URL and"
                    " CRAWLERAI_EVAL_PRIVATE_OBJECT_STORE. They are set only for custodians (C1), so this is"
                    " expected on any other machine."
                )
            _check_separate(settings.database_url.get_secret_value(), database_url.get_secret_value())
            if _nested(settings.object_store, object_store):
                raise PrivateStoreNotSeparate("the private object store overlaps the main one")
            return PrivateEvalStore(
                split, create_async_engine(database_url.get_secret_value()), open_store(object_store)
            )
        case _:
            assert_never(split)


def _check_separate(main_url: str, private_url: str) -> None:
    main, private = make_url(main_url), make_url(private_url)
    if (main.host, main.port, main.database) == (private.host, private.port, private.database):
        raise PrivateStoreNotSeparate("the private eval database is the main database")


def _nested(a: str, b: str) -> bool:
    """Whether one object store URL is the other or lies under it."""
    a, b = a.rstrip("/") + "/", b.rstrip("/") + "/"
    return a.startswith(b) or b.startswith(a)


def _check_llm_key(key: str) -> str:
    # sha256(role, model, prompt, schema) in hex (SPEC-03 §4.5); the key becomes part of an object key.
    if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
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

    @abstractmethod
    async def _capture_key(self, conn: AsyncConnection, capture_id: CaptureId) -> str | None:
        """The object key of this store's capture `capture_id`, if it has one."""

    async def list_pages(self, schema_name: str | None = None, status: LabelStatus | None = None) -> list[EvalPageRow]:
        page = self._page.c
        query = select(self._page).where(page.split == self._split).order_by(page.id)
        if schema_name is not None:
            query = query.where(page.schema_name == schema_name)
        if status is not None:
            query = query.where(page.labels["status"].astext == status)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(query)).mappings().all()
        return [_page_row(row) for row in rows]

    async def get_page(self, page_id: EvalPageId) -> EvalPageRow:
        query = select(self._page).where(self._page.c.id == page_id, self._page.c.split == self._split)
        async with self._engine.connect() as conn:
            row = (await conn.execute(query)).mappings().one_or_none()
        if row is None:
            raise EvalNotFound(f"no {self._split} eval page {page_id}")
        return _page_row(row)

    async def get_bundle(self, capture_id: CaptureId) -> CaptureBundle:
        """Raise `EvalNotFound` for an unknown capture, `ObjectNotFound` for a missing bundle and `CorruptBundle`
        for unreadable bytes: replay counts each as a dropped page (SPEC-03 §4.11)."""
        async with self._engine.connect() as conn:
            key = await self._capture_key(conn, capture_id)
        if key is None:
            raise EvalNotFound(f"no {self._split} eval capture {capture_id}")
        blob = await asyncio.to_thread(self._objects.get, key)
        return await asyncio.to_thread(decode, blob)

    async def put_page(self, page: EvalPageRow) -> EvalPageId:
        if page.split != self._split:
            raise ValueError(f"a {page.split} page cannot be stored in the {self._split} store")
        async with self._engine.begin() as conn:
            if await self._capture_key(conn, page.capture_id) is None:
                raise EvalNotFound(f"no {self._split} eval capture {page.capture_id}")
            await conn.execute(insert(self._page).values(page.model_dump()))
        return page.id

    async def put_labels(self, page_id: EvalPageId, labels: Labels, who: str, pass_: LabelPass) -> None:
        match pass_:
            case "labeler":
                people = {"labeler": who, "checker": None}
            case "checker":
                people = {"checker": who}
            case _:
                assert_never(pass_)
        page = self._page.c
        query = (
            update(self._page)
            .where(page.id == page_id, page.split == self._split)
            .values(labels=labels, **people)
            .returning(page.id)
        )
        async with self._engine.begin() as conn:
            if (await conn.execute(query)).one_or_none() is None:
                raise EvalNotFound(f"no {self._split} eval page {page_id}")

    async def put_run(self, run: EvalRunRow) -> EvalRunId:
        if run.split != self._split:
            raise ValueError(f"a {run.split} run cannot be stored in the {self._split} store")
        async with self._engine.begin() as conn:
            await conn.execute(insert(self._run).values(run.model_dump()))
        return run.id

    async def latest_run(self, git_sha_on_main: str | None) -> EvalRunRow | None:
        run = self._run.c
        query = select(self._run).where(run.split == self._split).order_by(run.created_at.desc(), run.id.desc())
        if git_sha_on_main is not None:
            query = query.where(run.git_sha == git_sha_on_main)
        async with self._engine.connect() as conn:
            row = (await conn.execute(query.limit(1))).mappings().one_or_none()
        if row is None:
            return None
        return EvalRunRow.model_validate({name: row[name] for name in EvalRunRow.model_fields})


def _page_row(row: Any) -> EvalPageRow:
    return EvalPageRow.model_validate({name: row[name] for name in EvalPageRow.model_fields})


class DevEvalStore(_SqlEvalStore):
    """Dev cases: `eval_page` and `eval_run` in the main database, captures in `capture` with no expiry, bundles at
    `eval/dev/{capture_id}.bundle.zst` and LLM responses at `eval/dev/llm/{key}.json` in the main store."""

    _page = Base.metadata.tables[EvalPage.__tablename__]
    _run = Base.metadata.tables[EvalRun.__tablename__]

    def __init__(self, engine: AsyncEngine, objects: ObjectStore) -> None:
        super().__init__("dev", engine, objects)

    async def _capture_key(self, conn: AsyncConnection, capture_id: CaptureId) -> str | None:
        # A dev eval capture never expires (SPEC-01 §4.4); a production capture is not an eval capture.
        query = select(Capture.object_key).where(Capture.id == capture_id, Capture.expires_at.is_(None))
        return (await conn.execute(query)).scalar_one_or_none()

    async def put_capture(self, bundle: CaptureBundle, category: EvalCategory) -> CaptureId:
        """`category` is kept on the page (`put_page`); the main database records sites without one."""
        key = dev_eval_capture_key(bundle.manifest.capture_id)
        blob = await asyncio.to_thread(encode, bundle)
        await asyncio.to_thread(self._objects.put, key, blob)
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
                .values(site_id=site_id, expires_at=None, **_capture_columns(bundle, key, len(blob)))
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

    async def _capture_key(self, conn: AsyncConnection, capture_id: CaptureId) -> str | None:
        query = select(EvalCapture.object_key).where(EvalCapture.id == capture_id, EvalCapture.split == self._split)
        return (await conn.execute(query)).scalar_one_or_none()

    async def put_capture(self, bundle: CaptureBundle, category: EvalCategory) -> CaptureId:
        key = f"{self._split}/{bundle.manifest.capture_id}.bundle.zst"
        blob = await asyncio.to_thread(encode, bundle)
        await asyncio.to_thread(self._objects.put, key, blob)
        async with self._engine.begin() as conn:
            await conn.execute(
                pg_insert(EvalCapture)
                .values(
                    split=self._split, host=_host(bundle), category=category, **_capture_columns(bundle, key, len(blob))
                )
                .on_conflict_do_nothing(index_elements=[EvalCapture.id])
            )
        return CaptureId(bundle.manifest.capture_id)

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
