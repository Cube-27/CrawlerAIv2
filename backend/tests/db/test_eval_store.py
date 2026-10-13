"""The `EvalStore` contract (SPEC-03 §4.2), run against the dev store and a private store over throwaway databases
and temporary object roots. Synthetic data only: `.test` hosts, made-up bundles (C1, C9)."""

import hashlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, insert, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.core.ids import uuid7
from crawlerai.db.models import Capture, CaptureId, EvalPage, EvalPageId, EvalRun, SchemaDef, SchemaId, Site, Split
from crawlerai.db.private_models import PrivateBase
from crawlerai.eval.store import (
    DevEvalStore,
    EvalNotFound,
    EvalPageRow,
    EvalRunRow,
    EvalStore,
    PrivateEvalStore,
)
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

HOST = "shop.eval-store.example.test"
SCHEMA_NAME = "eval_store_detail"


@dataclass
class Case:
    store: EvalStore
    root: Path  # the store's object root
    other_root: Path  # the other kind of store's object root, which must stay empty
    schema_id: SchemaId


@pytest.fixture(params=["dev", "hidden"])
def split_url(request: pytest.FixtureRequest, database_url: str) -> tuple[Split, str]:
    """The private database is requested only for the private store, so the dev store runs without one."""
    if request.param == "dev":
        return "dev", database_url
    return "hidden", request.getfixturevalue("private_database_url")


@pytest.fixture
async def case(split_url: tuple[Split, str], tmp_path: Path) -> AsyncIterator[Case]:
    split, url = split_url
    engine = create_async_engine(url)
    main_root, private_root = tmp_path / "main", tmp_path / "private"
    if split == "dev":
        async with engine.begin() as conn:
            schema_id: SchemaId = (
                await conn.execute(
                    insert(SchemaDef)
                    .values(name=SCHEMA_NAME, version=1, page_kind="detail", fields={}, origin="user", status="active")
                    .returning(SchemaDef.id)
                )
            ).scalar_one()
        yield Case(DevEvalStore(engine, FsStore(main_root)), main_root, private_root, schema_id)
        async with engine.begin() as conn:
            await conn.execute(delete(EvalPage))
            await conn.execute(delete(EvalRun))
            await conn.execute(delete(Capture).where(Capture.object_key.like("eval/dev/%")))
            await conn.execute(delete(Site).where(Site.host == HOST))
            await conn.execute(delete(SchemaDef).where(SchemaDef.id == schema_id))
    else:
        store = PrivateEvalStore("hidden", engine, FsStore(private_root))
        yield Case(store, private_root, main_root, SchemaId(uuid7()))
        async with engine.begin() as conn:
            for table in reversed(PrivateBase.metadata.sorted_tables):
                await conn.execute(delete(table))
    await engine.dispose()


def _bundle(path: str = "/p/1") -> CaptureBundle:
    body = f"<html><body><h1>Item {path}</h1></body></html>".encode()
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=f"https://{HOST}{path}",
        final_url=f"https://{HOST}{path}",
        fetched_at=datetime(2026, 10, 1, 12, 30, tzinfo=UTC),
        method="http",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(("Accept", "text/html"),), response=(("Content-Type", "text/html"),)),
        timings_ms={"total": 240},
        html_sha256=sha256_hex(body),
        network_bodies=(),
        fetch_policy={"timeout_s": 12.0},
        engine_version="0+cal.0",
    )
    return CaptureBundle(manifest=manifest, body=body, network=())


def _page(case: Case, capture_id: CaptureId, **fields: object) -> EvalPageRow:
    values: dict[str, object] = {
        "capture_id": capture_id,
        "split": case.store.split,
        "schema_id": case.schema_id,
        "schema_name": SCHEMA_NAME,
        "page_kind": "detail",
        "category": "custom_store",
    }
    return EvalPageRow.model_validate(values | fields)


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) if root.exists() else []


def _llm_key(n: int) -> str:
    return hashlib.sha256(f"role|model|prompt {n}|schema".encode()).hexdigest()


async def test_a_capture_round_trips_and_its_bundle_lands_only_in_the_stores_own_root(case: Case) -> None:
    bundle = _bundle()

    capture_id = await case.store.put_capture(bundle, "custom_store")

    assert capture_id == bundle.manifest.capture_id
    assert await case.store.get_bundle(capture_id) == bundle
    expected_key = {"dev": f"eval/dev/{capture_id}.bundle.zst", "hidden": f"hidden/{capture_id}.bundle.zst"}
    assert _files(case.root) == [expected_key[case.store.split]]
    assert _files(case.other_root) == []


async def test_putting_a_capture_twice_converges(case: Case) -> None:
    bundle = _bundle()

    first = await case.store.put_capture(bundle, "custom_store")
    second = await case.store.put_capture(bundle, "custom_store")
    page_id = await case.store.put_page(_page(case, second))

    assert first == second == bundle.manifest.capture_id
    assert (await case.store.get_page(page_id)).capture_id == first
    assert await case.store.get_bundle(first) == bundle
    assert len(_files(case.root)) == 1


async def test_an_unknown_capture_is_not_found(case: Case) -> None:
    with pytest.raises(EvalNotFound):
        await case.store.get_bundle(CaptureId(uuid7()))


async def test_a_page_round_trips(case: Case) -> None:
    capture_id = await case.store.put_capture(_bundle(), "api_backed")
    page = _page(
        case,
        capture_id,
        category="api_backed",
        page_kind="listing",
        labels={"label_version": 1, "status": "draft", "fields": {}},
        config_snapshot={"version": 3},
    )

    page_id = await case.store.put_page(page)

    assert page_id == page.id
    assert await case.store.get_page(page_id) == page


async def test_an_unknown_page_is_not_found(case: Case) -> None:
    with pytest.raises(EvalNotFound):
        await case.store.get_page(EvalPageId(uuid7()))


async def test_a_page_of_another_split_is_refused(case: Case) -> None:
    capture_id = await case.store.put_capture(_bundle(), "mixed")
    other: Split = "fresh" if case.store.split == "dev" else "dev"

    with pytest.raises(ValueError, match=f"a {other} page cannot be stored in the {case.store.split} store"):
        await case.store.put_page(_page(case, capture_id, split=other))

    assert await case.store.list_pages() == []


async def test_a_page_must_reference_a_capture_of_this_store(case: Case) -> None:
    with pytest.raises(EvalNotFound):
        await case.store.put_page(_page(case, CaptureId(uuid7())))


async def test_pages_are_listed_by_schema_name_and_label_status(case: Case) -> None:
    capture_id = await case.store.put_capture(_bundle(), "job_board")
    draft, checked, labeled = (
        _page(case, capture_id, labels={"status": status}) for status in ("draft", "checked", "labeled")
    )
    for page in (draft, checked, labeled):
        await case.store.put_page(page)

    assert await case.store.list_pages() == [draft, checked, labeled]
    assert await case.store.list_pages(status="checked") == [checked]
    assert await case.store.list_pages(schema_name=SCHEMA_NAME, status="draft") == [draft]
    assert await case.store.list_pages(schema_name="other_detail") == []


async def test_labels_record_the_labeler_then_a_different_checker(case: Case) -> None:
    capture_id = await case.store.put_capture(_bundle(), "custom_store")
    page_id = await case.store.put_page(_page(case, capture_id))

    await case.store.put_labels(page_id, {"status": "labeled", "fields": {}}, "ana", "labeler")
    await case.store.put_labels(page_id, {"status": "checked", "fields": {}}, "ben", "checker")

    page = await case.store.get_page(page_id)
    assert (page.labels, page.labeler, page.checker) == ({"status": "checked", "fields": {}}, "ana", "ben")


async def test_a_labeler_pass_clears_the_check(case: Case) -> None:
    capture_id = await case.store.put_capture(_bundle(), "custom_store")
    page_id = await case.store.put_page(_page(case, capture_id))
    await case.store.put_labels(page_id, {"status": "labeled"}, "ana", "labeler")
    await case.store.put_labels(page_id, {"status": "checked"}, "ben", "checker")

    await case.store.put_labels(page_id, {"status": "labeled"}, "ben", "labeler")

    page = await case.store.get_page(page_id)
    assert (page.labels, page.labeler, page.checker) == ({"status": "labeled"}, "ben", None)


async def test_the_labeler_cannot_check_their_own_labels(case: Case) -> None:
    capture_id = await case.store.put_capture(_bundle(), "custom_store")
    page_id = await case.store.put_page(_page(case, capture_id))
    await case.store.put_labels(page_id, {"status": "labeled"}, "ana", "labeler")

    with pytest.raises(IntegrityError, match="two_people"):
        await case.store.put_labels(page_id, {"status": "checked"}, "ana", "checker")

    page = await case.store.get_page(page_id)
    assert (page.labels, page.checker) == ({"status": "labeled"}, None)


async def test_labels_of_an_unknown_page_are_refused(case: Case) -> None:
    with pytest.raises(EvalNotFound):
        await case.store.put_labels(EvalPageId(uuid7()), {}, "ana", "labeler")


async def test_the_latest_run_is_the_newest_optionally_of_one_commit(case: Case) -> None:
    assert await case.store.latest_run(None) is None
    runs = [
        EvalRunRow(split=case.store.split, engine_version=f"{sha}+cal.0", git_sha=sha, metrics={"n_pages": n})
        for sha, n in (("a" * 40, 1), ("b" * 40, 2), ("a" * 40, 3), ("c" * 40, 4))
    ]
    for run in runs:
        assert await case.store.put_run(run) == run.id

    assert await case.store.latest_run(None) == runs[3]
    assert await case.store.latest_run("a" * 40) == runs[2]
    assert await case.store.latest_run("d" * 40) is None


async def test_a_run_of_another_split_is_refused(case: Case) -> None:
    other: Split = "fresh" if case.store.split == "dev" else "dev"

    with pytest.raises(ValueError, match=f"a {other} run cannot be stored"):
        await case.store.put_run(EvalRunRow(split=other, engine_version="x", git_sha="a" * 40, metrics={}))

    assert await case.store.latest_run(None) is None


async def test_the_llm_cache_misses_then_returns_what_was_put(case: Case) -> None:
    assert await case.store.llm_cache_get(_llm_key(1)) is None

    await case.store.llm_cache_put(_llm_key(1), b'{"answer": 1}')
    await case.store.llm_cache_put(_llm_key(2), b'{"answer": 2}')
    await case.store.llm_cache_put(_llm_key(2), b'{"answer": 2}')

    assert await case.store.llm_cache_get(_llm_key(1)) == b'{"answer": 1}'
    assert await case.store.llm_cache_get(_llm_key(2)) == b'{"answer": 2}'
    assert await case.store.llm_cache_get(_llm_key(3)) is None
    assert _files(case.other_root) == []


async def test_an_llm_cache_key_must_be_a_sha256(case: Case) -> None:
    with pytest.raises(ValueError, match="invalid LLM cache key"):
        await case.store.llm_cache_put("../escape", b"{}")


async def test_a_dev_page_cannot_reference_a_production_capture(database_url: str, tmp_path: Path) -> None:
    """Production captures expire (SPEC-01 §4.4); a dev eval page needs one that never does."""
    engine = create_async_engine(database_url)
    store = DevEvalStore(engine, FsStore(tmp_path))
    capture_id = CaptureId(uuid7())
    try:
        async with engine.begin() as conn:
            default_project = text("(SELECT id FROM project WHERE name = 'default')")
            site_id = (
                await conn.execute(insert(Site).values(project_id=default_project, host=HOST).returning(Site.id))
            ).scalar_one()
            await conn.execute(
                insert(Capture).values(
                    id=capture_id,
                    site_id=site_id,
                    url=f"https://{HOST}/p/1",
                    fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
                    method="http",
                    status_code=200,
                    final_url=f"https://{HOST}/p/1",
                    block_class="ok",
                    object_key=f"captures/2026/10/{capture_id}.bundle.zst",
                    html_sha256="0" * 64,
                    expires_at=datetime(2026, 10, 31, tzinfo=UTC),
                    size_bytes=1,
                    duration_ms=1,
                )
            )
        page = EvalPageRow(
            capture_id=capture_id,
            split="dev",
            schema_id=SchemaId(uuid.UUID(int=0)),
            schema_name=SCHEMA_NAME,
            page_kind="detail",
            category="mixed",
        )

        with pytest.raises(EvalNotFound):
            await store.put_page(page)
        with pytest.raises(EvalNotFound):
            await store.get_bundle(capture_id)
    finally:
        async with engine.begin() as conn:
            await conn.execute(delete(Capture).where(Capture.id == capture_id))
            await conn.execute(delete(Site).where(Site.host == HOST))
        await engine.dispose()


async def test_the_main_database_refuses_hidden_and_fresh_pages_and_runs(database_url: str) -> None:
    """INV-01 in structure: whatever writes to the main database, it cannot hold a hidden or fresh case."""
    engine = create_async_engine(database_url)
    try:
        for split in ("hidden", "fresh"):
            async with engine.connect() as conn:
                with pytest.raises(IntegrityError, match="ck_eval_run_split"):
                    await conn.execute(
                        insert(EvalRun).values(split=split, engine_version="x", git_sha="a" * 40, metrics={})
                    )
            async with engine.connect() as conn:
                with pytest.raises(IntegrityError, match="ck_eval_page_split"):
                    await conn.execute(
                        insert(EvalPage).values(
                            capture_id=uuid7(),
                            split=split,
                            schema_id=uuid7(),
                            schema_name=SCHEMA_NAME,
                            page_kind="detail",
                            category="mixed",
                        )
                    )
    finally:
        await engine.dispose()


async def test_the_private_database_refuses_dev_runs(private_database_url: str) -> None:
    engine = create_async_engine(private_database_url)
    try:
        async with engine.connect() as conn:
            with pytest.raises(IntegrityError, match="ck_eval_run_split"):
                await conn.execute(
                    insert(PrivateBase.metadata.tables["eval_run"]).values(
                        id=uuid7(), split="dev", engine_version="x", git_sha="a" * 40, metrics={}
                    )
                )
    finally:
        await engine.dispose()
