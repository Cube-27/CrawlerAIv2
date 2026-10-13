"""Role S's request and names (SPEC-06 §4.5): one name per prompt, a deterministic request, and an output schema that
accepts a schema document without its name and version."""

import json
import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

from crawlerai.db.models import JobId
from crawlerai.llm.client import request_hash
from crawlerai.llm.roles.s_schema import SAMPLE_MAX_CHARS, draft_name, draft_request, output_schema
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import FieldType

JOB = JobId(uuid.UUID(int=1))

DRAFT = {
    "page_kind": "detail",
    "required_groups": [["sku", "gtin"]],
    "fields": {
        "title": {"type": "text", "required": True, "description": "Name of the product, without the store name"},
        "sku": {"type": "identifier", "scheme": "sku", "description": "Stock keeping unit"},
        "gtin": {"type": "identifier", "scheme": "gtin", "description": "Global trade item number"},
    },
}


def test_the_name_is_the_hash_of_the_prompt() -> None:
    # sha256("Job titles and salaries")[:12]
    assert draft_name("Job titles and salaries") == "draft_1731376895d1"


# Space, tab, line feed, carriage return, no-break space, ideographic space: Unicode White_Space characters.
WHITESPACE = "".join(map(chr, (0x20, 0x09, 0x0A, 0x0D, 0xA0, 0x3000)))
words = st.lists(st.text(alphabet=st.characters(categories=["L", "N"]), min_size=1), min_size=1, max_size=5)
spaces = st.text(alphabet=WHITESPACE, min_size=1, max_size=3)


@given(words, st.data())
def test_prompts_that_differ_only_in_whitespace_share_a_name(parts: list[str], data: st.DataObject) -> None:
    spaced = data.draw(spaces) + "".join(part + data.draw(spaces) for part in parts)

    assert draft_name(spaced) == draft_name(" ".join(parts))


def test_different_prompts_have_different_names() -> None:
    assert draft_name("Job titles") != draft_name("Job title")


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

    assert list(validator.iter_errors(DRAFT)) == []
    assert not validator.is_valid({**DRAFT, "name": "chosen_by_the_model"})
    assert not validator.is_valid({**DRAFT, "version": 2})
