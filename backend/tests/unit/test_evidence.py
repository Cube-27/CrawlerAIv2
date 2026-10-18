"""Evidence buckets, calibration and the minimum confidence (resolution spec, INV-22): a chosen value's bucket, its
dev-measured confidence, the `calibrated` flag, and abstention below a request's minimum confidence."""

import pytest

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.db.models import SourceKind
from crawlerai.normalize.base import Ok
from crawlerai.resolve.derive import Derived
from crawlerai.resolve.evidence import (
    MIN_CALIBRATED_N,
    Bucket,
    Calibration,
    assess,
    evidence_of,
)
from crawlerai.resolve.preference import Chosen, Unpublished
from crawlerai.resolve.types import FieldOutcome
from crawlerai.schemas.types import FieldType

ENTITY = "jsonld:0:$"


def _chosen(chosen: Candidate, *agreeing: Candidate) -> Chosen:
    """The preference that publishes `chosen`: every kept candidate is it or agrees with it."""
    return Chosen(chosen, agreeing, (), (chosen, *agreeing))


def _candidate(kind: SourceKind = "jsonld", value: str = "A-1", *, independent: bool = True, n: int = 0) -> Candidate:
    locators = {
        "og": f"meta:og:x{n}",
        "js_state": f"js_state:/html[1]/body[1]/script[1]:$['x{n}']",
        "xhr": f"xhr:0:$['x{n}']",
        "adapter": f"adapter:example:$['x{n}']",
        "api": f"api:r1:$['x{n}']",
        "config": f"config:sku:0:span.x{n}",
        "llm": f"text:{n}-{n + 3}",
    }
    return Candidate(
        field="sku",
        entity_id=PAGE if kind in ("og", "llm", "js_state", "xhr") else ENTITY,
        source_kind=kind,
        raw=value,
        normalized=Ok(value),
        locator=locators.get(kind, f"{ENTITY}['x{n}']"),
        independent=independent,
    )


def _calibration(**buckets: tuple[int, float | None]) -> Calibration:
    return Calibration(
        git_sha="a" * 40,
        buckets={key.replace("__", "|"): Bucket(n=n, precision=p) for key, (n, p) in buckets.items()},
    )


def _assess(
    decision: Chosen | Unpublished | Derived,
    calibration: Calibration | None = None,
    *,
    min_confidence: float | None = None,
    corroborated: bool = False,
    type_: FieldType = FieldType.IDENTIFIER,
) -> FieldOutcome:
    return assess(type_, decision, calibration, min_confidence=min_confidence, corroborated=corroborated)


# Buckets


@pytest.mark.parametrize(
    ("kind", "bucket"),
    [
        ("dom", "dom"),
        ("js_state", "state"),
        ("api", "adapter"),
        ("og", "structured"),
        ("llm", "llm_grounded"),
    ],
)
def test_a_lone_value_takes_its_source_kinds_bucket(kind: SourceKind, bucket: str) -> None:
    assert evidence_of(_candidate(kind), (), corroborated=False) == bucket


# Calibration and the minimum confidence


@pytest.mark.parametrize(("precision", "status"), [(0.969, "abstained"), (0.97, "published")])
def test_a_field_abstains_below_the_requests_minimum_confidence(precision: float, status: str) -> None:
    chosen = _candidate()
    calibration = _calibration(identifier__structured=(MIN_CALIBRATED_N, precision))
    outcome = _assess(_chosen(chosen), calibration, min_confidence=0.97)
    assert outcome.status == status
    if status == "abstained":
        assert (outcome.reason, outcome.value, outcome.evidence, outcome.confidence) == (
            "below_min_confidence",
            None,
            "structured",
            precision,
        )
        assert outcome.rejected == ((chosen, "below_min_confidence"),)


# Unpublished and derived decisions


# A page's fields


# The calibration file
