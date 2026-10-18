"""Evidence buckets, calibration and the minimum confidence (resolution spec, INV-22): a chosen value's bucket, its
dev-measured confidence, the `calibrated` flag, and abstention below a request's minimum confidence."""

import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.core.ids import uuid7
from crawlerai.db.models import EvalRunId, SchemaId, SourceKind
from crawlerai.normalize.base import Ok
from crawlerai.resolve.derive import Derived
from crawlerai.resolve.evidence import (
    MIN_CALIBRATED_N,
    Bucket,
    Calibration,
    assess,
    assess_fields,
    evidence_of,
    load_calibration,
    required_fields,
)
from crawlerai.resolve.preference import Chosen, Unpublished
from crawlerai.resolve.types import Derivation, FieldOutcome
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

ENTITY = "jsonld:0:$"
RUN_ID = EvalRunId(uuid.UUID("01900000-0000-7000-8000-000000000001"))


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


def test_a_config_value_takes_the_configs_field_status() -> None:
    config = _candidate("config")
    assert evidence_of(config, (), corroborated=True) == "config_corroborated"
    assert evidence_of(config, (), corroborated=False) == "config_uncorroborated"


def test_an_adapter_value_stays_adapter_when_others_agree() -> None:
    assert evidence_of(_candidate("adapter"), (_candidate("jsonld"),), corroborated=False) == "adapter"


def test_a_lone_state_value_takes_the_state_bucket_and_publishes() -> None:
    state = _candidate("js_state", independent=False)
    outcome = _assess(_chosen(state))
    assert (outcome.status, outcome.value, outcome.evidence) == ("published", "A-1", "state")
    assert (outcome.source_kind, outcome.chosen) == ("js_state", state)


def test_a_lone_value_of_a_captured_call_takes_the_network_bucket() -> None:
    # Appendix A #58: the network data-source layer's values are measured in a bucket of their own.
    outcome = _assess(_chosen(_candidate("xhr")))
    assert (outcome.status, outcome.evidence) == ("published", "network")


# Calibration and the minimum confidence


def test_without_a_calibration_a_value_publishes_uncalibrated() -> None:
    chosen = _candidate()
    outcome = _assess(_chosen(chosen))
    assert (outcome.status, outcome.value, outcome.evidence) == ("published", "A-1", "structured")
    assert (outcome.confidence, outcome.calibrated) == (None, False)
    assert (outcome.source_kind, outcome.locator, outcome.chosen) == ("jsonld", chosen.locator, chosen)


def test_the_confidence_is_the_buckets_dev_precision() -> None:
    outcome = _assess(_chosen(_candidate()), _calibration(identifier__structured=(120, 0.99)))
    assert (outcome.status, outcome.confidence, outcome.calibrated) == ("published", 0.99, True)


def test_a_bucket_of_another_type_does_not_apply() -> None:
    outcome = _assess(_chosen(_candidate()), _calibration(money__structured=(120, 0.99)))
    assert (outcome.confidence, outcome.calibrated) == (None, False)


@pytest.mark.parametrize(("n", "calibrated"), [(MIN_CALIBRATED_N - 1, False), (MIN_CALIBRATED_N, True)])
def test_a_bucket_is_calibrated_from_the_floor_of_dev_labels(n: int, calibrated: bool) -> None:
    outcome = _assess(_chosen(_candidate()), _calibration(identifier__structured=(n, 0.5)), min_confidence=0.9)
    assert (outcome.calibrated, outcome.status) == (calibrated, "abstained" if calibrated else "published")
    assert outcome.confidence == 0.5


def test_a_calibrated_bucket_below_every_threshold_publishes_without_a_minimum_confidence() -> None:
    outcome = _assess(_chosen(_candidate()), _calibration(identifier__structured=(MIN_CALIBRATED_N, 0.57)))
    assert (outcome.status, outcome.value, outcome.reason) == ("published", "A-1", None)
    assert (outcome.confidence, outcome.calibrated) == (0.57, True)


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


def test_the_bucket_of_the_agreeing_kinds_is_measured() -> None:
    calibration = _calibration(identifier__structured=(50, 0.5), identifier__agreed=(50, 0.99))
    chosen, og = _candidate(), _candidate("og")
    outcome = _assess(_chosen(chosen, og), calibration)
    assert (outcome.status, outcome.evidence, outcome.confidence) == ("published", "agreed", 0.99)


def test_a_bucket_without_a_precision_is_uncalibrated() -> None:
    outcome = _assess(_chosen(_candidate()), _calibration(identifier__structured=(40, None)))
    assert (outcome.status, outcome.confidence, outcome.calibrated) == ("published", None, False)


# Unpublished and derived decisions


def test_an_unpublished_decision_keeps_its_status_and_reason() -> None:
    rejected = ((_candidate(), "disagree"), (_candidate("og"), "disagree"))
    outcome = _assess(Unpublished("conflict", "disagree", rejected))
    assert (outcome.status, outcome.reason, outcome.value, outcome.evidence) == ("conflict", "disagree", None, None)
    assert outcome.rejected == rejected


def test_an_absolutized_value_publishes_with_its_source_candidates_provenance() -> None:
    source = _candidate("jsonld", "/img/1.png")
    outcome = _assess(Derived("https://shop.example.test/img/1.png", "absolutize", source), type_=FieldType.IMAGE_URL)
    assert (outcome.status, outcome.value, outcome.derived_by) == (
        "published",
        "https://shop.example.test/img/1.png",
        "absolutize",
    )
    assert (outcome.evidence, outcome.source_kind, outcome.locator) == ("structured", "jsonld", source.locator)


@pytest.mark.parametrize("derived_by", ["canonical_link", "final_url"])
def test_a_page_url_derivation_publishes_in_the_derived_bucket(derived_by: Derivation) -> None:
    outcome = _assess(Derived("https://shop.example.test/p/1", derived_by, None), type_=FieldType.URL)
    assert (outcome.status, outcome.value, outcome.derived_by, outcome.chosen) == (
        "published",
        "https://shop.example.test/p/1",
        derived_by,
        None,
    )
    assert (outcome.evidence, outcome.source_kind, outcome.locator) == ("derived", "derived", f"derived:{derived_by}")
    assert (outcome.confidence, outcome.calibrated) == (None, False)


def test_a_page_url_derivation_is_measured_in_its_own_bucket() -> None:
    derived = Derived("https://shop.example.test/p/1", "canonical_link", None)
    outcome = _assess(derived, _calibration(url__derived=(40, 0.99)), type_=FieldType.URL)
    assert (outcome.status, outcome.evidence, outcome.confidence, outcome.calibrated) == (
        "published",
        "derived",
        0.99,
        True,
    )


def test_a_page_url_derivation_in_a_bucket_below_the_minimum_confidence_abstains() -> None:
    calibration = _calibration(url__derived=(40, 0.9))
    derived = Derived("https://shop.example.test/p/1", "final_url", None)
    outcome = _assess(derived, calibration, type_=FieldType.URL, min_confidence=0.95)
    assert (outcome.status, outcome.reason, outcome.value) == ("abstained", "below_min_confidence", None)
    assert (outcome.evidence, outcome.confidence, outcome.calibrated) == ("derived", 0.9, True)


# A page's fields


def _schema() -> SchemaDef:
    def spec(*, required: bool = False) -> FieldSpec:
        return FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="d", required=required)

    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="s",
        page_kind="detail",
        required_groups=[["gtin", "mpn"]],
        fields={"sku": spec(required=True), "gtin": spec(), "mpn": spec(), "note": spec()},
    )


def test_required_fields_are_the_required_ones_and_the_group_members() -> None:
    assert required_fields(_schema()) == {"sku", "gtin", "mpn"}


def test_every_field_is_held_to_the_one_minimum_confidence() -> None:
    calibration = _calibration(identifier__structured=(MIN_CALIBRATED_N, 0.96))
    decisions = {name: _chosen(_candidate()) for name in ("sku", "gtin", "mpn", "note")}
    held = assess_fields(_schema(), decisions, calibration, frozenset(), min_confidence=0.97)
    assert {o.status for o in held.values()} == {"abstained"}
    free = assess_fields(_schema(), decisions, calibration, frozenset())
    assert {o.status for o in free.values()} == {"published"}


def test_the_configs_corroborated_fields_are_named() -> None:
    decisions = {name: _chosen(_candidate("config")) for name in ("sku", "gtin", "mpn", "note")}
    outcomes = assess_fields(_schema(), decisions, None, frozenset({"gtin"}))
    assert outcomes["gtin"].evidence == "config_corroborated"
    assert outcomes["sku"].evidence == "config_uncorroborated"


# The calibration file


def test_a_missing_calibration_file_means_no_calibration(tmp_path: Path) -> None:
    assert load_calibration(tmp_path / "calibration.json") is None


def test_a_calibration_not_fitted_on_dev_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "calibration.json"
    path.write_text(
        '{"calibration_version": 1, "source_split": "hidden", "git_sha": "a", "buckets": {}}',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="source_split"):
        load_calibration(path)


@pytest.mark.parametrize(("precision", "status"), [(0.5, "abstained"), (0.99, "published")])
def test_the_outcome_keeps_the_candidates_that_passed_screening(precision: float, status: str) -> None:
    # Precedence fitting scores every kind that offered a value (SPEC-05 §4.11), not only the chosen one.
    chosen, og = _candidate(), _candidate("og")
    calibration = _calibration(identifier__agreed=(50, precision))

    outcome = _assess(_chosen(chosen, og), calibration, min_confidence=0.9)

    assert (outcome.status, outcome.kept) == (status, (chosen, og))


def test_a_state_value_publishes_with_its_kept_candidates() -> None:
    chosen, xhr = _candidate("js_state"), _candidate("xhr", independent=False, n=1)

    outcome = _assess(_chosen(chosen, xhr))

    assert (outcome.status, outcome.evidence, outcome.kept) == ("published", "state", (chosen, xhr))


def test_a_declined_field_keeps_its_competing_candidates() -> None:
    a, b = _candidate(), _candidate("og", "A-2")

    outcome = _assess(Unpublished("conflict", "disagree", ((a, "disagree"), (b, "disagree")), (a, b)))

    assert (outcome.status, outcome.kept) == ("conflict", (a, b))
