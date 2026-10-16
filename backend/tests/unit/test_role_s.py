"""Role S's request and names (SPEC-06 §4.5): one name per prompt, a deterministic request, and an output schema that
accepts a schema document without its name and version."""

import json
import re
import uuid
from random import Random
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from pydantic import JsonValue

from crawlerai.db.models import JobId
from crawlerai.llm.client import request_hash
from crawlerai.llm.roles.s_schema import (
    SAMPLE_MAX_CHARS,
    draft_name,
    draft_request,
    fields_name,
    fields_request,
    output_schema,
)
from crawlerai.llm.roles.s_wire import from_wire, to_wire
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import NAME_PATTERN, FieldType

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


def test_the_name_is_the_hash_of_the_prompt() -> None:
    # sha256(prompt)[:12]
    assert draft_name("Job titles and salaries") == "draft_1731376895d1"
    assert draft_name("Job titles") == "draft_9afad3cc2cba"


# Space, tab, line feed, carriage return, no-break space, ideographic space: Unicode White_Space characters.
WHITESPACE = "".join(map(chr, (0x20, 0x09, 0x0A, 0x0D, 0xA0, 0x3000)))
words = st.lists(st.text(alphabet=st.characters(categories=["L", "N"]), min_size=1), min_size=1, max_size=5)
spaces = st.text(alphabet=WHITESPACE, min_size=1, max_size=3)


@given(words, st.data())
def test_prompts_that_differ_only_in_whitespace_share_a_name(parts: list[str], data: st.DataObject) -> None:
    spaced = data.draw(spaces) + "".join(part + data.draw(spaces) for part in parts)

    assert draft_name(spaced) == draft_name(" ".join(parts))


def test_the_request_is_a_strong_s_draft_call_charged_to_the_job() -> None:
    req = draft_request("Event names and dates", ["Sample text"], JOB)

    assert (req.prompt_kind, req.model_class, req.job_id) == ("s_draft", "strong", JOB)


def test_the_request_is_the_same_for_the_same_inputs() -> None:
    first = draft_request("Event names  and dates", ["one", "two"], JOB)
    second = draft_request("Event names and dates\n", ["one", "two"], JOB)

    assert request_hash(first) == request_hash(second)


def test_the_user_part_holds_the_prompt_the_types_the_presets_and_each_sample() -> None:
    user = draft_request("Event  names", ["first page text", "second page text"], JOB).user

    assert "<request>\nEvent names\n</request>" in user
    assert all(f"- {kind.value}: " in user for kind in FieldType)
    assert '<sample_page n="1">\nfirst page text\n</sample_page>' in user
    assert '<sample_page n="2">\nsecond page text\n</sample_page>' in user


def test_the_preset_examples_are_documents_the_output_schema_accepts() -> None:
    user = draft_request("Event names", ["text"], JOB).user
    examples = user.split("Example schemas (presets):\n")[1].split("\n\n")[0].splitlines()
    validator = Draft202012Validator(output_schema())

    assert len(examples) == len(load_presets())
    assert [list(validator.iter_errors(json.loads(example))) for example in examples] == [[]] * len(examples)


def test_a_long_sample_is_cut_at_the_limit() -> None:
    user = draft_request("Event names", ["a" * SAMPLE_MAX_CHARS + "TAIL"], JOB).user

    assert "a" * SAMPLE_MAX_CHARS + "\n</sample_page>" in user
    assert "TAIL" not in user


@pytest.mark.parametrize("samples", [[], ["1", "2", "3", "4"]])
def test_one_to_three_samples_are_needed(samples: list[str]) -> None:
    with pytest.raises(ValueError, match="1 to 3 sample pages"):
        draft_request("Event names", samples, JOB)


def test_an_empty_prompt_is_refused() -> None:
    with pytest.raises(ValueError, match="empty"):
        draft_request(" \n ", ["text"], JOB)


def test_the_output_schema_accepts_a_document_without_name_and_version() -> None:
    validator = Draft202012Validator(output_schema())

    assert list(validator.iter_errors(to_wire(DRAFT))) == []
    assert not validator.is_valid({**to_wire(DRAFT), "name": "chosen_by_the_model"})
    assert not validator.is_valid({**to_wire(DRAFT), "version": 2})


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


def test_a_field_name_given_twice_is_refused() -> None:
    wire = to_wire({"page_kind": "detail", "fields": {"a": {"type": "text"}}})
    wire["fields"] = cast(list[JsonValue], wire["fields"]) * 2

    with pytest.raises(ValueError, match="fields: field 'a' given twice"):
        from_wire(wire)


def test_a_list_with_two_items_is_refused() -> None:
    wire = to_wire({"page_kind": "detail", "fields": {"a": {"type": "list", "item": {"type": "text"}}}})
    entry = cast(list[dict[str, JsonValue]], wire["fields"])[0]
    entry["item"] = cast(list[JsonValue], entry["item"]) * 2

    with pytest.raises(ValueError, match=r"fields\.a: a list has one item, not 2"):
        from_wire(wire)


# Field names (SPEC-14 §4.10): one draft per set of names and page kind, from a request without samples or a job.
field_names = st.lists(st.from_regex(NAME_PATTERN, fullmatch=True), min_size=1, max_size=8, unique=True)


# The first request reads the presets (cached afterwards), which can outlast Hypothesis's default deadline.
@settings(deadline=None)
@given(field_names, st.randoms())
def test_the_names_in_any_order_share_a_draft_name(names: list[str], rng: Random) -> None:
    shuffled = rng.sample(names, len(names))

    assert fields_name(shuffled, "detail") == fields_name(names, "detail")
    assert fields_request(shuffled, "detail").user == fields_request(names, "detail").user


@given(field_names)
def test_a_draft_name_is_a_schema_name_and_differs_by_page_kind(names: list[str]) -> None:
    detail, listing = fields_name(names, "detail"), fields_name(names, "listing")

    assert detail != listing
    assert re.fullmatch(NAME_PATTERN, detail)


def test_the_fields_request_holds_the_sorted_names_and_page_kind_and_no_job() -> None:
    req = fields_request(["price", "colour"], "listing")

    assert (req.prompt_kind, req.model_class, req.job_id) == ("s_draft", "strong", None)
    assert '<fields page_kind="listing">\ncolour\nprice\n</fields>' in req.user
    assert "<sample_page" not in req.user
