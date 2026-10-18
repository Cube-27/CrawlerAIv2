"""When learning asks role A (learning-configs spec, "Induction, then role A synthesis"): only for a required field
induction left that some sample page published. Pages are synthetic; role A answers no step (`eval.learn_sim`)."""

import asyncio
from datetime import UTC, datetime
from typing import cast

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.held_out import StoredPage
from crawlerai.config_ir.induction import Published, SamplePage
from crawlerai.config_ir.learning import Target, learn_config
from crawlerai.config_ir.validation import Facts, HeldOutPage
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import CaptureId, SchemaId
from crawlerai.eval.learn_sim import RoleACounter
from crawlerai.llm.providers.fake import ScriptedClient
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle

CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC))
SCHEMA = SchemaDef.model_validate(
    {
        "id": SchemaId(uuid7()),
        "origin": "user",
        "status": "active",
        "name": "synthetic",
        "page_kind": "detail",
        "fields": {
            "title": {"type": "text", "required": True, "description": "d"},
            "code": {"type": "text", "required": True, "description": "d"},
        },
    }
)


def _page(n: int, *, code: bool) -> StoredPage:
    page = ParsedPage(f"<html><body><h1 id='t'>Item {n}</h1><p>C-{n}</p></body></html>")
    published = {"title": Published(f"Item {n}", "dom:/html/body/h1")}
    if code:  # stated in an element with no stable anchor: induction verifies no selector for it
        published["code"] = Published(f"C-{n}", "dom:/html/body/p")
    facts = Facts({name: p.value for name, p in published.items()})
    held_out = HeldOutPage(CaptureId(uuid7()), page, CTX, facts)
    return StoredPage(held_out, SamplePage(page, CTX, published), cast(CaptureBundle, None))


def _learned(*, code: bool) -> tuple[int, set[str]]:
    pages = [_page(n, code=code) for n in range(1, 4)]
    counter = RoleACounter(ScriptedClient(), None)
    target = Target(SCHEMA, "shop.example.test", "http", None)
    held_out = [p.held_out for p in pages]
    validated = asyncio.run(learn_config(counter, target, pages, held_out, Vocabulary({}), 10_000, absent_from=[]))
    assert validated.ir is not None
    return counter.calls, set(validated.ir.fields)


def test_a_required_field_no_sample_page_published_does_not_make_role_a_run() -> None:
    assert _learned(code=False) == (0, {"title"})


def test_a_required_field_a_page_published_and_induction_left_makes_role_a_run() -> None:
    assert _learned(code=True) == (1, {"title"})
