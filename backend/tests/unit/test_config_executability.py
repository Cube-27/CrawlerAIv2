"""Executability classes (learning-configs, "Executability classes"): what each field of a config needs to run, from the
IR alone."""

from typing import Any

import pytest

from snowcrawl.config_ir.executability import class_counts, config_classes, step_class
from snowcrawl.config_ir.model import ExtractionConfigIR, FieldSteps

HTML = {"xpath": "normalize-space(//h1)"}
JSONLD = {"jsonld": "$['name']"}
STATE = {"jsonpath": "$['a']", "source": "js_state"}
XHR = {"jsonpath": "$['a']", "source": "xhr"}
API = {"jsonpath": "$['a']", "source": "api"}


def _field(*steps: dict[str, Any], status: str = "corroborated") -> dict[str, Any]:
    return {"steps": list(steps), "status": status}


def _config(fields: dict[str, Any], listing: dict[str, Any] | None = None) -> ExtractionConfigIR:
    return ExtractionConfigIR.model_validate(
        {
            "ir_version": "1",
            "site": "shop.example.test",
            "schema": {"name": "synthetic", "digest": "0" * 64},
            "page_kind": "listing" if listing else "detail",
            "fetch": {"method": "http"},
            "fields": fields,
            "listing": listing,
            "provenance": {
                "origin": "induced",
                "validated_on": [],
                "learned_at": "2026-10-01T00:00:00Z",
                "engine_version": "test",
            },
        }
    )


@pytest.mark.parametrize(
    ("step", "has_recipe", "expected"),
    [
        (HTML, False, "static-html"),
        (JSONLD, False, "static-html"),
        (STATE, False, "static-html"),
        ({"regex": "a(b)"}, False, "static-html"),
        (XHR, False, "needs-browser"),
        (XHR, True, "needs-browser"),
        (API, True, "api-call"),
        (API, False, "unexecutable"),
    ],
)
def test_a_step_needs_the_input_its_selector_reads(step: dict[str, Any], has_recipe: bool, expected: str) -> None:
    parsed = FieldSteps.model_validate(_field(step)).steps[0]
    assert step_class(parsed, has_recipe=has_recipe) == expected


def test_a_configs_fields_are_classed_with_listing_fields_and_next() -> None:
    config = _config(
        {"name": _field(HTML), "price": _field(XHR), "gone": _field(HTML, status="suspended")},
        {
            "row": {"xpath": "//ol/li"},
            "fields": {"title": _field(JSONLD), "rating": _field(API)},
            "next": {"jsonpath": "$['n']", "source": "xhr"},
        },
    )
    assert config_classes(config) == {
        "name": "static-html",
        "price": "needs-browser",
        "gone": "unexecutable",
        "listing:title": "static-html",
        "listing:rating": "unexecutable",
        "listing:next": "needs-browser",
    }
    assert class_counts(config) == {"static-html": 2, "needs-browser": 2, "api-call": 0, "unexecutable": 2}
