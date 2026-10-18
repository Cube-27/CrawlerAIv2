"""Calibration and precedence fitting (SPEC-05 §4.11, ARCHITECTURE §10): buckets fitted from 20 labelled values, and a
kind moved ahead of another only when their precision intervals separate. Synthetic measurements only (C9)."""

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.db.models import SourceKind
from crawlerai.resolve.calibrate import Measured, fit_order
from crawlerai.resolve.evidence import MIN_CALIBRATED_N

ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")


def test_a_kind_clearly_more_precise_moves_ahead_of_the_one_before_it() -> None:
    measured: dict[SourceKind, Measured] = {
        "jsonld": Measured(n=100, precision=0.70),
        "og": Measured(n=100, precision=0.99),
    }

    assert fit_order(("jsonld", "og"), measured) == ("og", "jsonld")


def test_a_move_passes_the_measured_kinds_it_beats_and_no_unmeasured_kind_changes_place() -> None:
    measured: dict[SourceKind, Measured] = {
        "jsonld": Measured(n=200, precision=0.40),
        "dom": Measured(n=200, precision=0.70),
        "xhr": Measured(n=200, precision=0.95),
    }

    # dom passes jsonld, then xhr passes dom; og and llm stay in their order.
    assert fit_order(("jsonld", "og", "dom", "llm", "xhr"), measured) == ("xhr", "dom", "jsonld", "og", "llm")


@given(
    st.permutations(ORDER),
    st.dictionaries(
        st.sampled_from(ORDER),
        st.builds(Measured, n=st.integers(0, 300), precision=st.none() | st.floats(0, 1)),
    ),
)
def test_a_fit_permutes_the_order_keeps_unmeasured_kinds_in_order_and_is_stable(
    current: list[SourceKind], measured: dict[SourceKind, Measured]
) -> None:
    fitted = fit_order(tuple(current), measured)

    def unmeasured(order: tuple[SourceKind, ...] | list[SourceKind]) -> list[SourceKind]:
        return [
            kind
            for kind in order
            if (cell := measured.get(kind)) is None or cell.precision is None or cell.n < MIN_CALIBRATED_N
        ]

    assert sorted(fitted) == sorted(current)
    assert unmeasured(fitted) == unmeasured(current)
    assert fit_order(fitted, measured) == fitted
