"""Evidence buckets, calibration and τ (SPEC-05 §4.9, ARCHITECTURE §10, INV-02, INV-22): a chosen value's bucket, its
dev-measured confidence, the `calibrated` flag, and abstention below τ."""

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
    Bucket,
    Calibration,
    assess,
    assess_fields,
    evidence_of,
    load_calibration,
    required_fields,
)
from crawlerai.resolve.preference import Chosen, Unpublished
from crawlerai.resolve.types import FieldOutcome
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

ENTITY = "jsonld:0:$"
RUN_ID = EvalRunId(uuid.UUID("01900000-0000-7000-8000-000000000001"))


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
        eval_run_id=RUN_ID,
        git_sha="a" * 40,
        buckets={key.replace("__", "|"): Bucket(n=n, precision=p) for key, (n, p) in buckets.items()},
    )


def _assess(
    decision: Chosen | Unpublished | Derived,
    calibration: Calibration | None = None,
    *,
    tau: float = 0.97,
    corroborated: bool = False,
    type_: FieldType = FieldType.IDENTIFIER,
) -> FieldOutcome:
    return assess(type_, decision, calibration, tau=tau, corroborated=corroborated)


# Buckets


@pytest.mark.parametrize(
    ("kind", "bucket"),
    [
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


def test_a_lone_state_value_has_no_bucket_and_abstains() -> None:
    state = _candidate("js_state")
    outcome = _assess(Chosen(state, (), (), (state,)))
    assert (outcome.status, outcome.reason, outcome.value) == ("abstained", "no_bucket", None)
    assert outcome.rejected == ((state, "no_bucket"),)


# Calibration and τ


def test_without_a_calibration_a_value_publishes_uncalibrated() -> None:
    chosen = _candidate()
    outcome = _assess(Chosen(chosen, (), (), (chosen,)))
    assert (outcome.status, outcome.value, outcome.evidence) == ("published", "A-1", "structured")
    assert (outcome.confidence, outcome.calibrated) == (None, False)
    assert (outcome.source_kind, outcome.locator, outcome.chosen) == ("jsonld", chosen.locator, chosen)


def test_the_confidence_is_the_buckets_dev_precision() -> None:
    outcome = _assess(Chosen(_candidate(), (), (), (_candidate(),)), _calibration(identifier__structured=(120, 0.99)))
    assert (outcome.status, outcome.confidence, outcome.calibrated) == ("published", 0.99, True)


def test_a_bucket_of_another_type_does_not_apply() -> None:
    outcome = _assess(Chosen(_candidate(), (), (), (_candidate(),)), _calibration(money__structured=(120, 0.99)))
    assert (outcome.confidence, outcome.calibrated) == (None, False)


@pytest.mark.parametrize(("n", "calibrated"), [(29, False), (30, True)])
def test_a_bucket_is_calibrated_from_30_dev_labels(n: int, calibrated: bool) -> None:
    outcome = _assess(Chosen(_candidate(), (), (), (_candidate(),)), _calibration(identifier__structured=(n, 0.5)))
    assert (outcome.calibrated, outcome.status) == (calibrated, "abstained" if calibrated else "published")
    assert outcome.confidence == 0.5


@pytest.mark.parametrize(("precision", "status"), [(0.969, "abstained"), (0.97, "published")])
def test_a_required_field_abstains_below_tau(precision: float, status: str) -> None:
    chosen = _candidate()
    outcome = _assess(Chosen(chosen, (), (), (chosen,)), _calibration(identifier__structured=(30, precision)))
    assert outcome.status == status
    if status == "abstained":
        assert (outcome.reason, outcome.value, outcome.evidence, outcome.confidence) == (
            "below_tau",
            None,
            "structured",
            precision,
        )
        assert outcome.rejected == ((chosen, "below_tau"),)


def test_the_bucket_of_the_agreeing_kinds_is_measured() -> None:
    calibration = _calibration(identifier__structured=(50, 0.5), identifier__agreed=(50, 0.99))
    chosen, og = _candidate(), _candidate("og")
    outcome = _assess(Chosen(chosen, (og,), (), (chosen, og)), calibration)
    assert (outcome.status, outcome.evidence, outcome.confidence) == ("published", "agreed", 0.99)


def test_a_bucket_without_a_precision_is_uncalibrated() -> None:
    outcome = _assess(Chosen(_candidate(), (), (), (_candidate(),)), _calibration(identifier__structured=(40, None)))
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


def test_a_page_url_derivation_without_a_candidate_does_not_publish() -> None:
    outcome = _assess(Derived("https://shop.example.test/p/1", "final_url", None), type_=FieldType.URL)
    assert (outcome.status, outcome.reason, outcome.value) == ("missing", "no_provenance", None)


# A page's fields


def _schema() -> SchemaDef:
    def spec(*, required: bool = False) -> FieldSpec:
        return FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="d", required=required)

    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="s",
        version=1,
        page_kind="detail",
        required_groups=[["gtin", "mpn"]],
        fields={"sku": spec(required=True), "gtin": spec(), "mpn": spec(), "note": spec()},
    )


def test_required_fields_are_the_required_ones_and_the_group_members() -> None:
    assert required_fields(_schema()) == {"sku", "gtin", "mpn"}


def test_optional_fields_abstain_below_the_optional_tau_only() -> None:
    calibration = _calibration(identifier__structured=(30, 0.96))
    decisions = {name: Chosen(_candidate(), (), (), (_candidate(),)) for name in ("sku", "gtin", "mpn", "note")}
    outcomes = assess_fields(_schema(), decisions, calibration, frozenset())
    assert {name: o.status for name, o in outcomes.items()} == {
        "sku": "abstained",
        "gtin": "abstained",
        "mpn": "abstained",
        "note": "published",
    }


def test_the_configs_corroborated_fields_are_named() -> None:
    decisions = {
        name: Chosen(_candidate("config"), (), (), (_candidate("config"),)) for name in ("sku", "gtin", "mpn", "note")
    }
    outcomes = assess_fields(_schema(), decisions, None, frozenset({"gtin"}))
    assert outcomes["gtin"].evidence == "config_corroborated"
    assert outcomes["sku"].evidence == "config_uncorroborated"


# The calibration file (INV-02)


def test_a_missing_calibration_file_means_no_calibration(tmp_path: Path) -> None:
    assert load_calibration(tmp_path / "calibration.json") is None


def test_a_calibration_not_fitted_on_dev_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "calibration.json"
    path.write_text(
        f'{{"calibration_version": 1, "source_split": "hidden", "eval_run_id": "{RUN_ID}", "git_sha": "a",'
        ' "buckets": {}}',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="source_split"):
        load_calibration(path)


@pytest.mark.parametrize(("precision", "status"), [(0.5, "abstained"), (0.99, "published")])
def test_the_outcome_keeps_the_candidates_that_passed_screening(precision: float, status: str) -> None:
    # Precedence fitting scores every kind that offered a value (SPEC-05 §4.11), not only the chosen one.
    chosen, og = _candidate(), _candidate("og")
    calibration = _calibration(identifier__agreed=(50, precision))

    outcome = _assess(Chosen(chosen, (og,), (), (chosen, og)), calibration)

    assert (outcome.status, outcome.kept) == (status, (chosen, og))


def test_a_lone_state_value_abstains_with_its_kept_candidates() -> None:
    chosen, xhr = _candidate("js_state"), _candidate("xhr", independent=False, n=1)

    outcome = _assess(Chosen(chosen, (xhr,), (), (chosen, xhr)))

    assert (outcome.status, outcome.reason, outcome.kept) == ("abstained", "no_bucket", (chosen, xhr))


def test_a_declined_field_keeps_its_competing_candidates() -> None:
    a, b = _candidate(), _candidate("og", "A-2")

    outcome = _assess(Unpublished("conflict", "disagree", ((a, "disagree"), (b, "disagree")), (a, b)))

    assert (outcome.status, outcome.kept) == ("conflict", (a, b))
