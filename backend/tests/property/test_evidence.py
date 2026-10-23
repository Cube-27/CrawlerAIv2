"""Evidence buckets, calibration and the minimum confidence: a chosen value's bucket, its
dev-measured confidence, the `calibrated` flag, and abstention below a request's minimum confidence; on generated
candidates, `agreed` requires two independent candidates of different source kinds, and a calibrated bucket below
a request's minimum confidence never publishes."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.db.models import SourceKind
from crawlerai.normalize.base import Basis, Ok
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
KINDS: tuple[SourceKind, ...] = ("jsonld", "microdata", "og", "js_state", "xhr", "config", "llm")


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
        assert (outcome.reason, outcome.value, outcome.evidence, outcome.confidence, outcome.rejected) == (
            "below_min_confidence",
            None,
            "structured",
            precision,
            ((chosen, "below_min_confidence"),),
        )


@pytest.mark.parametrize(
    ("basis", "measured"),
    [(None, (0.97, True)), ("page", (0.97, True)), ("locale", (0.8, True)), ("unknown", (None, False))],
)
def test_a_price_on_weak_currency_evidence_is_noted_and_measured_apart(
    basis: Basis | None, measured: tuple[float | None, bool]
) -> None:
    # Owner decision 2026-10-18: a currency only the locale settles, or none, publishes with lower confidence.
    value: JsonValue = {"amount": "10", "currency": None if basis == "unknown" else "USD"}
    chosen = _candidate().model_copy(update={"field": "price", "raw": value, "normalized": Ok(value, basis=basis)})
    calibration = _calibration(
        money__structured=(MIN_CALIBRATED_N, 0.97), money__structured__locale=(MIN_CALIBRATED_N, 0.8)
    )

    outcome = _assess(_chosen(chosen), calibration, type_=FieldType.MONEY)

    assert (outcome.status, outcome.value, outcome.basis, outcome.confidence, outcome.calibrated) == (
        "published",
        value,
        basis,
        *measured,
    )


def test_a_url_publishes_as_written_and_in_full_when_an_agreeing_source_writes_it_so() -> None:
    url = "https://shop.example.test/p/1"
    relative = _candidate("adapter").model_copy(update={"raw": "/p/1", "normalized": Ok(url, stated="/p/1")})
    full = _candidate("og").model_copy(update={"raw": url, "normalized": Ok(url)})

    assert _assess(_chosen(relative), type_=FieldType.URL).published == "/p/1"  # never resolved
    assert _assess(_chosen(relative, full), type_=FieldType.URL).published == url


# Properties


candidates = st.lists(st.tuples(st.sampled_from(KINDS), st.booleans(), st.booleans()), min_size=1, max_size=6).map(
    lambda rows: [
        _candidate(kind, independent=independent, n=n).model_copy(update={"fallback": fallback})
        for n, (kind, independent, fallback) in enumerate(rows)
    ]
)


@given(candidates)
def test_agreed_means_two_independent_kinds(supporting: list[Candidate]) -> None:
    chosen, *agreeing = supporting
    # A fallback is no agreement.
    independent_kinds = {c.source_kind for c in supporting if c.independent and not c.fallback}

    agreed = evidence_of(chosen, tuple(agreeing), corroborated=False) == "agreed"

    assert agreed == (len(independent_kinds) >= 2)


@given(
    candidates,
    st.integers(min_value=0, max_value=200),
    st.floats(min_value=0.0, max_value=1.0),
    st.one_of(st.none(), st.sampled_from([0.95, 0.97])),
)
def test_a_calibrated_bucket_below_the_minimum_confidence_never_publishes(
    supporting: list[Candidate], n: int, precision: float, minimum: float | None
) -> None:
    chosen, *agreeing = supporting
    evidence = evidence_of(chosen, tuple(agreeing), corroborated=False)
    buckets = {} if evidence is None else {f"identifier|{evidence}": Bucket(n=n, precision=precision)}
    calibration = Calibration(git_sha="a", buckets=buckets)

    outcome = _assess(_chosen(chosen, *agreeing), calibration, min_confidence=minimum)

    if outcome.status == "published" and minimum is not None:
        assert not outcome.calibrated or (outcome.confidence is not None and outcome.confidence >= minimum)
    calibrated_below = minimum is not None and evidence is not None and n >= MIN_CALIBRATED_N and precision < minimum
    assert (outcome.status == "abstained" and outcome.reason == "below_min_confidence") == calibrated_below
