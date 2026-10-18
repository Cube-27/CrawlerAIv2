"""Role S's request and names (llm spec): one name per prompt, a deterministic request, and an output schema that
accepts a schema document without its name."""

import json
import uuid
from typing import cast

import pytest
from pydantic import JsonValue

from crawlerai.collect import schema_org_map
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.db.models import JobId
from crawlerai.llm.roles import s_schema
from crawlerai.llm.roles.s_schema import (
    draft_request,
    output_schema,
)
from crawlerai.llm.roles.s_wire import from_wire, to_wire
from crawlerai.schemas.types import FieldType

JOB = JobId(uuid.UUID(int=1))

DRAFT: dict[str, JsonValue] = {
    "page_kind": "detail",
    "required_groups": [["sku", "gtin"]],
    "fields": {
        "title": {"type": "text", "required": True, "description": "Name of the product, without the store name"},
        "sku": {"type": "identifier", "scheme": "sku", "description": "Stock keeping unit"},
        "gtin": {"type": "identifier", "scheme": "gtin", "description": "Global trade item number"},
    },
}


def test_the_request_is_a_strong_s_draft_call_charged_to_the_job() -> None:
    req = draft_request("Event names and dates", ["Sample text"], JOB)

    assert (req.prompt_kind, req.model_class, req.job_id) == ("s_draft", "strong", JOB)


def test_the_user_part_holds_the_prompt_the_types_the_presets_and_each_sample() -> None:
    user = draft_request("Event  names", ["first page text", "second page text"], JOB).user

    assert "<request>\nEvent names\n</request>" in user
    assert all(f"- {kind.value}: " in user for kind in FieldType)
    assert '<sample_page n="1">\nfirst page text\n</sample_page>' in user
    assert '<sample_page n="2">\nsecond page text\n</sample_page>' in user


def test_the_wire_form_has_no_recursion_and_unrolls_nesting_to_the_depth_limit() -> None:
    nested: dict[str, JsonValue] = {
        "page_kind": "detail",
        "fields": {
            "tags": {"type": "list", "description": "Tags", "item": {"type": "text"}},
            "seller": {
                "type": "object",
                "description": "Seller",
                "fields": {"name": {"type": "text", "description": "N"}},
            },
        },
    }

    wire = to_wire(nested)

    assert [entry["name"] for entry in cast(list[dict[str, JsonValue]], wire["fields"])] == ["tags", "seller"]
    assert from_wire(wire) == {
        "page_kind": "detail",
        "required_groups": [],
        "fields": {
            "tags": {
                "type": "list",
                "required": False,
                "scope": "row",
                "description": "Tags",
                "item": {"type": "text", "required": False, "scope": "row"},
            },
            "seller": {
                "type": "object",
                "required": False,
                "scope": "row",
                "description": "Seller",
                "fields": {"name": {"type": "text", "required": False, "scope": "row", "description": "N"}},
            },
        },
    }
    assert "$ref" not in json.dumps(cast(dict[str, JsonValue], output_schema()["$defs"])["field_3"])


def _vocabulary() -> Vocabulary:
    terms: list[JsonValue] = [
        {"@id": "schema:Thing", "@type": "rdfs:Class"},
        {"@id": "schema:Product", "@type": "rdfs:Class", "rdfs:subClassOf": {"@id": "schema:Thing"}},
        {"@id": "schema:name", "@type": "rdf:Property"},
    ]
    return Vocabulary.parse({"@graph": terms})


@pytest.mark.parametrize(("path", "refused"), [("Product.name", False), ("Product.notAProperty", True)])
def test_the_reply_check_refuses_a_draft_naming_a_term_the_pinned_vocabulary_lacks(
    monkeypatch: pytest.MonkeyPatch, path: str, refused: bool
) -> None:
    monkeypatch.setattr(schema_org_map, "default_vocabulary", _vocabulary)
    draft = json.loads(json.dumps(DRAFT))
    draft["fields"]["title"]["schema_org"] = path

    reason = s_schema._invalid(to_wire(draft), "draft_000000000000")

    assert (reason is not None) is refused
    assert reason is None or "notAProperty is not a schema.org property" in reason
