"""The candidate, entity and outcome models (SPEC-05 §4.2) and INV-22: every candidate carries a locator; every
published field carries `evidence`, `confidence`, `calibrated`, `source_kind` and `locator`."""

from typing import Any

import pytest
from pydantic import ValidationError

from crawlerai.collect.base import Candidate, CollectResult, Entity
from crawlerai.normalize.base import Ok
from crawlerai.resolve.types import ExtractionResult, FieldOutcome

PRODUCT = Entity(id="jsonld:0:$['@graph'][0]", kind="Product", urls=("https://shop.example.test/p/1",), parent=None)
OFFER = Entity(id="jsonld:0:$['@graph'][0]['offers']", kind="Offer", urls=(), parent=PRODUCT.id)


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


def _published(**changes: Any) -> dict[str, Any]:
    chosen = _candidate()
    values: dict[str, Any] = {
        "status": "published",
        "reason": None,
        "value": "Widget 9",
        "evidence": "structured",
        "confidence": 0.98,
        "calibrated": True,
        "source_kind": "jsonld",
        "locator": chosen.locator,
        "derived_by": None,
        "chosen": chosen,
        "rejected": (),
    }
    return values | changes


def _missing(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "status": "missing",
        "reason": "no_candidates",
        "value": None,
        "evidence": None,
        "confidence": None,
        "calibrated": False,
        "source_kind": None,
        "locator": None,
        "derived_by": None,
        "chosen": None,
        "rejected": (),
    }
    return values | changes


# Candidates


@pytest.mark.parametrize("locator", ["", "jsonld:0", "css:span.price", "text:4-4"])
def test_a_candidate_without_a_valid_locator_is_refused(locator: str) -> None:
    with pytest.raises(ValidationError, match="locator"):
        _candidate(locator=locator)


def test_a_candidate_source_kind_comes_from_the_section_6_enum() -> None:
    with pytest.raises(ValidationError, match="source_kind"):
        _candidate(source_kind="dom")


# Collect results


def test_a_candidate_of_an_unknown_entity_is_refused() -> None:
    orphan_offer, product_name = OFFER.model_copy(update={"parent": None}), _candidate()
    with pytest.raises(ValidationError, match="unknown entity"):
        CollectResult(entities=(orphan_offer,), candidates=(product_name,))


def test_an_entity_whose_parent_is_unknown_is_refused() -> None:
    assert CollectResult(entities=(PRODUCT, OFFER), candidates=()).entities == (PRODUCT, OFFER)
    with pytest.raises(ValidationError, match="unknown parent"):
        CollectResult(entities=(OFFER,), candidates=())


def test_entity_ids_are_unique_within_a_result() -> None:
    with pytest.raises(ValidationError, match="duplicate entity"):
        CollectResult(entities=(PRODUCT, PRODUCT), candidates=())


# Field outcomes (INV-22)


@pytest.mark.parametrize("attribute", ["evidence", "source_kind", "locator", "value"])
def test_a_published_field_without_a_required_attribute_is_refused(attribute: str) -> None:
    values = _published(**{attribute: None})
    with pytest.raises(ValidationError, match=attribute):
        FieldOutcome(**values)


def test_an_uncalibrated_published_field_still_carries_a_confidence() -> None:
    outcome = FieldOutcome(**_published(calibrated=False, confidence=0.5))
    assert (outcome.calibrated, outcome.confidence) == (False, 0.5)


def test_a_published_field_without_a_dev_measurement_is_uncalibrated() -> None:
    outcome = FieldOutcome(**_published(calibrated=False, confidence=None))
    assert (outcome.calibrated, outcome.confidence) == (False, None)
    values = _published(calibrated=True, confidence=None)
    with pytest.raises(ValidationError, match="calibrated"):
        FieldOutcome(**values)


def test_a_published_field_locator_must_parse() -> None:
    values = _published(locator="jsonld:x:$")
    with pytest.raises(ValidationError, match="locator"):
        FieldOutcome(**values)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_is_a_probability(confidence: float) -> None:
    values = _published(confidence=confidence)
    with pytest.raises(ValidationError, match="confidence"):
        FieldOutcome(**values)


def test_an_unpublished_field_holds_no_value() -> None:
    values = _missing(status="conflict", value="Widget 9")
    with pytest.raises(ValidationError, match="value"):
        FieldOutcome(**values)


def test_an_unpublished_field_says_why() -> None:
    values = _missing(status="abstained", reason=None)
    with pytest.raises(ValidationError, match="reason"):
        FieldOutcome(**values)


def test_an_abstained_field_keeps_its_bucket_and_confidence() -> None:
    outcome = FieldOutcome(
        **_missing(status="abstained", reason="below_tau", evidence="structured", confidence=0.9, calibrated=True)
    )
    assert (outcome.evidence, outcome.confidence, outcome.value) == ("structured", 0.9, None)


def test_a_calibrated_field_has_a_confidence() -> None:
    values = _missing(calibrated=True)
    with pytest.raises(ValidationError, match="calibrated"):
        FieldOutcome(**values)


def test_derived_by_names_a_core_derivation() -> None:
    values = _published(derived_by="guessed")
    with pytest.raises(ValidationError, match="derived_by"):
        FieldOutcome(**values)


# Extraction results


def _result(**changes: Any) -> ExtractionResult:
    values: dict[str, Any] = {
        "outcome": "extracted",
        "entity": {"name": FieldOutcome(**_published())},
        "rows": (),
        "candidates": (_candidate(),),
        "llm_calls": (),
        "mode": "adhoc",
        "record_confidence": 0.98,
    }
    return ExtractionResult(**(values | changes))


@pytest.mark.parametrize("outcome", ["blocked", "not_found", "shell"])
def test_a_page_that_was_not_served_has_no_candidates_and_no_fields(outcome: str) -> None:
    candidates = (_candidate(),)
    with pytest.raises(ValidationError, match="candidates"):
        _result(outcome=outcome, entity=None, candidates=candidates)
    with pytest.raises(ValidationError, match="fields"):
        _result(outcome=outcome, candidates=())
    assert _result(outcome=outcome, entity=None, candidates=(), record_confidence=None).outcome == outcome


def test_an_error_publishes_nothing() -> None:
    with pytest.raises(ValidationError, match="fields"):
        _result(outcome="error", record_confidence=None)
    result = _result(outcome="error", entity=None, record_confidence=None)
    assert result.candidates == (_candidate(),)  # kept for diagnostics


def test_record_confidence_is_a_probability() -> None:
    with pytest.raises(ValidationError, match="record_confidence"):
        _result(record_confidence=1.5)
