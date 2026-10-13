"""Evidence properties (SPEC-05 §4.9, ARCHITECTURE §8.1, §10): `agreed` requires two independent candidates of
different source kinds, and a calibrated bucket below τ never publishes."""

import uuid

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.db.models import EvalRunId, SourceKind
from crawlerai.normalize.base import Ok
from crawlerai.resolve.evidence import Bucket, Calibration, assess, evidence_of
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
    st.sampled_from([0.95, 0.97]),
)
def test_a_calibrated_bucket_below_tau_never_publishes(
    supporting: list[Candidate], n: int, precision: float, tau: float
) -> None:
    chosen, *agreeing = supporting
    evidence = evidence_of(chosen, tuple(agreeing), corroborated=False)
    buckets = {} if evidence is None else {f"identifier|{evidence}": Bucket(n=n, precision=precision)}
    calibration = Calibration(eval_run_id=EvalRunId(uuid.uuid4()), git_sha="a", buckets=buckets)

    outcome = assess(
        FieldType.IDENTIFIER, Chosen(chosen, tuple(agreeing), ()), calibration, tau=tau, corroborated=False
    )

    if outcome.status == "published":
        assert not outcome.calibrated or (outcome.confidence is not None and outcome.confidence >= tau)
    calibrated_below = evidence is not None and n >= 30 and precision < tau
    assert (outcome.status == "abstained" and outcome.reason == "below_tau") == calibrated_below
