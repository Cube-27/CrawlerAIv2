import asyncio
import json
from typing import Any

from crawlerai.db.models import CaptureId, EvalCategory, EvalPageId, Split
from crawlerai.eval.cli import PageRequest, Skipped, report
from crawlerai.eval.page_import import import_pages
from crawlerai.eval.store import EvalPageRow
from crawlerai.schemas.types import SchemaDef
from tests.unit.test_eval_label_file import DETAIL, SCHEMAS, A, bundle_result


class PageStore:
    """The parts of an `EvalStore` an import writes, in memory."""

    split: Split = "dev"

    def __init__(self) -> None:
        self.pages: dict[EvalPageId, EvalPageRow] = {}

    async def put_capture(self, bundle: Any, category: EvalCategory) -> CaptureId:
        return CaptureId(bundle.manifest.capture_id)

    async def put_page(self, page: EvalPageRow) -> EvalPageId:
        self.pages[page.id] = page
        return page.id


def test_pages_are_stored_unlabeled_and_a_page_not_fetched_or_already_there_is_skipped() -> None:
    requests = [PageRequest(n, f"{A}/p/{n}", DETAIL.name, "custom_store") for n in (1, 2, 3)]
    fetched: list[str] = []
    attempts: list[str] = []

    async def fetch(url: str, schema: SchemaDef) -> Any:
        fetched.append(url)
        attempts.append(schema.name)
        return "robots" if url.endswith("/2") else bundle_result(url)

    store = PageStore()
    outcomes = asyncio.run(import_pages(store, SCHEMAS, requests, fetch, existing={f"{A}/p/3"}))  # type: ignore[arg-type]

    assert fetched == [f"{A}/p/1", f"{A}/p/2"]
    assert set(attempts) == {DETAIL.name}
    [stored, robots, done] = outcomes
    assert (robots, done) == (Skipped(2, "robots"), Skipped(3, "already_in_split"))
    [(page_id, row)] = store.pages.items()
    assert page_id == stored.page_id  # type: ignore[union-attr]
    assert (row.schema_name, row.page_kind, row.category, row.split) == (DETAIL.name, "detail", "custom_store", "dev")
    assert row.labels == {}
    lines = [json.loads(line) for line in report(outcomes).splitlines()]
    assert [line["n"] for line in lines] == [1, 2, 3]
