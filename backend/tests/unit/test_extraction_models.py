"""The candidate, entity and outcome models and: every candidate carries a locator; every
published field carries `evidence`, `confidence`, `calibrated`, `source_kind` and `locator`."""

from typing import Any

import pytest
from pydantic import ValidationError

from crawlerai.collect.base import Candidate, Entity
from crawlerai.normalize.base import Ok

PRODUCT = Entity(id="jsonld:0:$['@graph'][0]", types=("Product",), urls=("https://shop.example.test/p/1",), parent=None)


def _candidate(**changes: Any) -> Candidate:
    values: dict[str, Any] = {
        "field": "name",
        "entity_id": PRODUCT.id,
        "source_kind": "jsonld",
        "raw": "Widget 9",
        "normalized": Ok("Widget 9"),
        "locator": "jsonld:0:$['@graph'][0]['name']",
        "independent": True,
    }
    return Candidate(**(values | changes))


# Candidates


@pytest.mark.parametrize("locator", ["", "jsonld:0", "css:span.price", "text:4-4"])
def test_a_candidate_without_a_valid_locator_is_refused(locator: str) -> None:
    with pytest.raises(ValidationError, match="locator"):
        _candidate(locator=locator)


# Collect results


# Field outcomes


# Extraction results
