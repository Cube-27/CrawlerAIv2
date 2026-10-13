"""`eval promote` and `eval rotate-hidden` (SPEC-03 §4.4, ARCHITECTURE §16.1): pages move from a private store to the
dev store whole site by whole site, keeping their ids and labels, and leave nothing behind in the private store.
Throwaway main and private databases (`CRAWLERAI_TEST_DATABASE_URL`, `CRAWLERAI_TEST_PRIVATE_DATABASE_URL`), two
temporary object roots, synthetic `.test` pages only (C1, C9)."""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

import anyio
import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.acquire.types import FetchResult
from crawlerai.cli import main
from crawlerai.core.ids import uuid7
from crawlerai.db.models import Capture, EvalCategory, EvalPage, SchemaDef, SchemaId, Site
from crawlerai.db.private_models import EvalCapture, PrivateBase
from crawlerai.eval.promote import Move, Moved, promote, rotate_hidden
from crawlerai.eval.store import DevEvalStore, EvalPageRow, PrivateEvalStore
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

SCHEMA = "eval_promote_detail"

CHECKED = {"label_version": 1, "status": "checked", "fields": {"price": {"value": None, "absent": True}}}
DRAFT = {"label_version": 1, "status": "draft", "fields": {}}


@dataclass
class Stores:
    dev: DevEvalStore
    fresh: PrivateEvalStore
    hidden: PrivateEvalStore
    main_root: Path
    private_root: Path
    schema_id: SchemaId
    database_url: str
    private_database_url: str
    fetch_result: Callable[..., FetchResult]

    async def add(
        self, store: PrivateEvalStore, host: str, labels: dict[str, object], category: EvalCategory = "custom_store"
    ) -> EvalPageRow:
        """A captured page of `host` in a private split, labeled by two people when `labels` is checked."""
        body = f"<html><body><h1>{uuid7()}</h1></body></html>".encode()
        url = f"https://{host}/p/{uuid7()}"
        bundle = self.fetch_result(url, body=body).bundle
        capture_id = await store.put_capture(bundle, category)
        checked = labels.get("status") == "checked"
        page = EvalPageRow.model_validate(
            {
                "capture_id": capture_id,
                "split": store.split,
                "schema_id": self.schema_id,
                "schema_name": SCHEMA,
                "page_kind": "detail",
                "category": category,
                "labels": labels,
                "labeler": "labeler-a" if checked else None,
                "checker": "checker-b" if checked else None,
                "config_snapshot": {"version": 1},
            }
        )
        await store.put_page(page)
        return page


def _fs(path: Path) -> str:
    return "fs:///" + path.as_posix().lstrip("/")


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) if root.exists() else []


@pytest.fixture
async def stores(
    database_url: str, private_database_url: str, tmp_path: Path, fetch_result: Callable[..., FetchResult]
) -> AsyncIterator[Stores]:
    main_root, private_root = tmp_path / "main", tmp_path / "private"
    main_engine, private_engine = create_async_engine(database_url), create_async_engine(private_database_url)
    async with main_engine.begin() as conn:
        schema_id = (
            await conn.execute(
                insert(SchemaDef)
                .values(name=SCHEMA, version=1, page_kind="detail", fields={}, origin="user", status="active")
                .returning(SchemaDef.id)
            )
        ).scalar_one()
    yield Stores(
        DevEvalStore(main_engine, FsStore(main_root)),
        PrivateEvalStore("fresh", private_engine, FsStore(private_root)),
        PrivateEvalStore("hidden", private_engine, FsStore(private_root)),
        main_root,
        private_root,
        schema_id,
        database_url,
        private_database_url,
        fetch_result,
    )
    async with main_engine.begin() as conn:
        await conn.execute(delete(EvalPage))
        await conn.execute(delete(Capture).where(Capture.object_key.like("eval/dev/%")))
        await conn.execute(delete(Site).where(Site.host.like("%.example.test")))
        await conn.execute(delete(SchemaDef).where(SchemaDef.id == schema_id))
    async with private_engine.begin() as conn:
        for table in reversed(PrivateBase.metadata.sorted_tables):
            await conn.execute(delete(table))
    await main_engine.dispose()
    await private_engine.dispose()


async def _main_hosts(stores: Stores) -> list[str]:
    engine = create_async_engine(stores.database_url)
    async with engine.connect() as conn:
        query = select(Site.host).where(Site.host.like("%.example.test")).order_by(Site.host)
        hosts = (await conn.execute(query)).all()
    await engine.dispose()
    return [host for (host,) in hosts]


def _as_dev(page: EvalPageRow) -> EvalPageRow:
    return page.model_copy(update={"split": "dev"})


async def test_promote_moves_the_fresh_sites_whose_pages_are_all_checked(stores: Stores) -> None:
    a1 = await stores.add(stores.fresh, "a.example.test", CHECKED)
    a2 = await stores.add(stores.fresh, "a.example.test", CHECKED)
    b1 = await stores.add(stores.fresh, "b.example.test", CHECKED)
    b2 = await stores.add(stores.fresh, "b.example.test", DRAFT)

    move = await promote(stores.fresh, stores.hidden, stores.dev, all_pages=False)

    assert move == Move((Moved(a1.id, a1.capture_id), Moved(a2.id, a2.capture_id)), sites=1, kept=2)
    # The pages keep their ids, labels, people and config snapshot.
    assert await stores.dev.list_pages(schema_name=SCHEMA) == [_as_dev(a1), _as_dev(a2)]
    assert [(await stores.dev.get_bundle(p.capture_id)).manifest.url.split("/")[2] for p in (a1, a2)] == [
        "a.example.test",
        "a.example.test",
    ]
    assert _files(stores.main_root) == sorted(f"eval/dev/{p.capture_id}.bundle.zst" for p in (a1, a2))
    # Site `b` stays whole in fresh, with its bundles; nothing of `a` is left there.
    assert await stores.fresh.list_pages() == [b1, b2]
    assert _files(stores.private_root) == sorted(f"fresh/{p.capture_id}.bundle.zst" for p in (b1, b2))
    assert await _main_hosts(stores) == ["a.example.test"]


async def test_promote_all_moves_every_fresh_site_and_empties_the_fresh_split(stores: Stores) -> None:
    pages = [
        await stores.add(stores.fresh, "a.example.test", DRAFT),
        await stores.add(stores.fresh, "b.example.test", CHECKED, category="job_board"),
    ]

    move = await promote(stores.fresh, stores.hidden, stores.dev, all_pages=True)

    assert (len(move.moved), move.sites, move.kept) == (2, 2, 0)
    assert await stores.dev.list_pages(schema_name=SCHEMA) == [_as_dev(p) for p in pages]
    assert await stores.fresh.list_pages() == []
    assert _files(stores.private_root) == []
    engine = create_async_engine(stores.private_database_url)
    async with engine.connect() as conn:
        assert (await conn.execute(select(EvalCapture.id))).all() == []
    await engine.dispose()


async def test_a_fresh_site_whose_host_has_hidden_pages_is_not_promoted(stores: Stores) -> None:
    hidden = await stores.add(stores.hidden, "h.example.test", CHECKED)
    fresh = await stores.add(stores.fresh, "h.example.test", CHECKED)

    move = await promote(stores.fresh, stores.hidden, stores.dev, all_pages=True)

    assert move == Move((), sites=0, kept=1)
    assert await stores.fresh.list_pages() == [fresh]
    assert await stores.hidden.list_pages() == [hidden]
    assert await _main_hosts(stores) == []
    assert _files(stores.main_root) == []


async def test_rotate_moves_the_fraction_of_hidden_sites_of_each_category_whole(stores: Stores) -> None:
    pages: dict[str, list[EvalPageRow]] = {}
    sites: list[tuple[str, EvalCategory, int]] = [
        ("s1.example.test", "custom_store", 2),
        ("s2.example.test", "custom_store", 1),
        ("s3.example.test", "custom_store", 1),
        ("j1.example.test", "job_board", 1),
        ("j2.example.test", "job_board", 2),
    ]
    for host, category, count in sites:
        pages[host] = [await stores.add(stores.hidden, host, CHECKED, category=category) for _ in range(count)]

    move = await rotate_hidden(stores.hidden, stores.dev, 0.5)

    # Half of 3 custom_store sites rounds to 2, half of 2 job_board sites to 1.
    moved_hosts = await _main_hosts(stores)
    assert move.sites == 3
    assert sum(host.startswith("s") for host in moved_hosts) == 2
    assert sum(host.startswith("j") for host in moved_hosts) == 1
    # Every page of a moved site is in dev with its labels; every page of the others is still hidden.
    moved_pages = [page for host in moved_hosts for page in pages[host]]
    kept_pages = [page for host in pages if host not in moved_hosts for page in pages[host]]
    assert sorted(m.page_id for m in move.moved) == sorted(page.id for page in moved_pages)
    assert sorted(await stores.dev.list_pages(schema_name=SCHEMA), key=lambda p: p.id) == sorted(
        (_as_dev(page) for page in moved_pages), key=lambda p: p.id
    )
    assert await stores.hidden.list_pages() == sorted(kept_pages, key=lambda p: p.id)
    assert move.kept == len(kept_pages)
    assert _files(stores.private_root) == sorted(f"hidden/{p.capture_id}.bundle.zst" for p in kept_pages)


async def test_a_move_interrupted_after_the_copy_finishes_on_the_next_run(stores: Stores) -> None:
    page = await stores.add(stores.fresh, "a.example.test", CHECKED)
    # The first run copied the page to dev and stopped before deleting the source.
    await stores.dev.put_capture(await stores.fresh.get_bundle(page.capture_id), page.category)
    await stores.dev.put_page(_as_dev(page))

    move = await promote(stores.fresh, stores.hidden, stores.dev, all_pages=False)

    assert move == Move((Moved(page.id, page.capture_id),), sites=1, kept=0)
    assert await stores.dev.list_pages(schema_name=SCHEMA) == [_as_dev(page)]
    assert await stores.fresh.list_pages() == []
    assert _files(stores.private_root) == []


async def test_a_capture_and_its_bundle_stay_while_another_page_names_them(stores: Stores) -> None:
    first = await stores.add(stores.fresh, "a.example.test", DRAFT)
    second = first.model_copy(update={"id": uuid7()})
    await stores.fresh.put_page(second)

    await stores.fresh.remove_page(first.id)

    assert await stores.fresh.list_pages() == [second]
    assert (await stores.fresh.get_bundle(first.capture_id)).manifest.capture_id == first.capture_id

    await stores.fresh.remove_page(second.id)
    await stores.fresh.remove_page(second.id)  # a missing page is a no-op

    assert _files(stores.private_root) == []


async def test_the_promote_command_reports_ids_and_counts_and_no_host(
    stores: Stores, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    page = await stores.add(stores.fresh, "a.example.test", CHECKED)
    await stores.add(stores.fresh, "b.example.test", DRAFT)
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", stores.database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", _fs(stores.main_root))
    monkeypatch.setenv("CRAWLERAI_EVAL_PRIVATE_DATABASE_URL", stores.private_database_url)
    monkeypatch.setenv("CRAWLERAI_EVAL_PRIVATE_OBJECT_STORE", _fs(stores.private_root))

    # In a thread: the command runs its own event loop.
    await anyio.to_thread.run_sync(main, ["eval", "promote", "--from", "fresh", "--to", "dev"])

    out = capsys.readouterr().out
    assert [json.loads(line) for line in out.splitlines()] == [
        {"page_id": str(page.id), "capture_id": str(page.capture_id)},
        {"moved_pages": 1, "moved_sites": 1, "kept_pages": 1},
    ]
    assert "example.test" not in out
    assert await stores.dev.list_pages(schema_name=SCHEMA) == [_as_dev(page)]
