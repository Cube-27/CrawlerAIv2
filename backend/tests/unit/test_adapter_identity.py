"""Adapter entities carry identity: the item URL and identifier values the adapter's shape maps are
the entity's `item_urls` and `identity`, so resolution merges the platform's statement of an item with the page's own
JSON-LD statement of it, and keeps two different items apart. Boards and answers are synthetic."""

import json
from datetime import UTC, datetime
from typing import Any

from snowcrawl.adapters.base import AdapterMatch
from snowcrawl.adapters.rippling import Rippling
from snowcrawl.collect.adapter import AdapterCollector
from snowcrawl.collect.base import CollectResult
from snowcrawl.collect.jsonld import JsonLdCollector
from snowcrawl.content.page import ParsedPage
from snowcrawl.normalize.base import Context
from snowcrawl.resolve.ownership import EntityGraph
from tests.unit.adapter_support import FIXTURES, JOB_FIELDS, VOCABULARY
from tests.unit.test_adapter_collector import _schema

JOB = "00000000-0000-4000-8000-0000000000b1"
PAGE_URL = "https://careers.example.test/jobs/synthetic-engineer"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
SCHEMA = _schema("detail", **JOB_FIELDS)


def _adapter_result() -> CollectResult:
    body = (FIXTURES / "rippling" / "job.json").read_text(encoding="utf-8")
    collector = AdapterCollector(Rippling(), AdapterMatch("example-board", "detail", JOB), VOCABULARY)
    return collector.collect(ParsedPage(body), SCHEMA, CTX)


def _jsonld_result(**properties: Any) -> CollectResult:
    block = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Synthetic Engineer", **properties}
    page = ParsedPage(f'<html><head><script type="application/ld+json">{json.dumps(block)}</script></head></html>')
    return JsonLdCollector(VOCABULARY).collect(page, SCHEMA, CTX)


def _roots(*results: CollectResult) -> list[str]:
    graph = EntityGraph.of((e for r in results for e in r.entities), VOCABULARY, (PAGE_URL,))
    return [e.id for e in graph.entities.values() if e.parent is None and e.id != "page"]


def test_the_adapters_posting_and_the_pages_json_ld_posting_sharing_an_identifier_are_one_entity() -> None:
    roots = _roots(_adapter_result(), _jsonld_result(identifier=JOB))

    assert roots == ["adapter:rippling:$"]


def test_a_json_ld_posting_of_another_item_stays_apart() -> None:
    roots = _roots(_adapter_result(), _jsonld_result(identifier="another", url="https://ats.example.test/other"))

    assert len(roots) == 2
