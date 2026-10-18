"""Evidence properties (resolution spec, INV-22): `agreed` requires two independent candidates of
different source kinds, and a calibrated bucket below a request's minimum confidence never publishes."""

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.db.models import SourceKind
from crawlerai.normalize.base import Ok
from crawlerai.resolve.evidence import MIN_CALIBRATED_N, Bucket, Calibration, assess, evidence_of
from crawlerai.resolve.preference import Chosen
from crawlerai.schemas.types import FieldType

KINDS: tuple[SourceKind, ...] = ("jsonld", "microdata", "og", "js_state", "xhr", "config", "llm")


def _candidate(kind: SourceKind, independent: bool, n: int) -> Candidate:
    return Candidate(
        field="sku",
        entity_id=PAGE,
        source_kind=kind,
        raw="A-1",
        normalized=Ok("A-1"),
        locator=f"meta:og:x{n}",
        independent=independent,
    )


candidates = st.lists(st.tuples(st.sampled_from(KINDS), st.booleans()), min_size=1, max_size=6).map(
    lambda pairs: [_candidate(kind, independent, n) for n, (kind, independent) in enumerate(pairs)]
)


@given(candidates)
def test_agreed_means_two_independent_kinds(supporting: list[Candidate]) -> None:
    chosen, *agreeing = supporting
    independent_kinds = {c.source_kind for c in supporting if c.independent}

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

    outcome = assess(
        FieldType.IDENTIFIER,
        Chosen(chosen, tuple(agreeing), (), (chosen, *agreeing)),
        calibration,
        min_confidence=minimum,
        corroborated=False,
    )

    if outcome.status == "published" and minimum is not None:
        assert not outcome.calibrated or (outcome.confidence is not None and outcome.confidence >= minimum)
    calibrated_below = minimum is not None and evidence is not None and n >= MIN_CALIBRATED_N and precision < minimum
    assert (outcome.status == "abstained" and outcome.reason == "below_min_confidence") == calibrated_below
