"""Calibration and precedence fitting (SPEC-05 §4.11, ARCHITECTURE §10): buckets fitted from 20 labelled values, and a
kind moved ahead of another only when their precision intervals separate. Synthetic measurements only (C9)."""

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.db.models import SourceKind
from crawlerai.resolve.calibrate import Measured, fit_buckets, fit_order, fit_orders
from crawlerai.resolve.evidence import MIN_CALIBRATED_N

ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")


def test_a_kind_clearly_more_precise_moves_ahead_of_the_one_before_it() -> None:
    measured: dict[SourceKind, Measured] = {
        "jsonld": Measured(n=100, precision=0.70),
        "og": Measured(n=100, precision=0.99),
    }

    assert fit_order(("jsonld", "og"), measured) == ("og", "jsonld")


def test_a_gap_that_sampling_noise_explains_leaves_the_order() -> None:
    measured: dict[SourceKind, Measured] = {
        "jsonld": Measured(n=100, precision=0.85),
        "og": Measured(n=100, precision=0.90),
    }

    assert fit_order(("jsonld", "og"), measured) == ("jsonld", "og")


def test_a_kind_measured_on_too_few_fields_keeps_its_place_however_precise() -> None:
    measured: dict[SourceKind, Measured] = {
        "adapter": Measured(n=MIN_CALIBRATED_N - 1, precision=1.0),
        "jsonld": Measured(n=500, precision=0.2),
    }

    assert fit_order(("jsonld", "adapter"), measured) == ("jsonld", "adapter")


def test_a_move_passes_the_measured_kinds_it_beats_and_no_unmeasured_kind_changes_place() -> None:
    measured: dict[SourceKind, Measured] = {
        "jsonld": Measured(n=200, precision=0.40),
        "dom": Measured(n=200, precision=0.70),
        "xhr": Measured(n=200, precision=0.95),
    }

    # dom passes jsonld, then xhr passes dom; og and llm stay in their order.
    assert fit_order(("jsonld", "og", "dom", "llm", "xhr"), measured) == ("xhr", "dom", "jsonld", "og", "llm")


def test_a_measured_kind_outside_the_order_is_not_added() -> None:
    measured: dict[SourceKind, Measured] = {
        "js_state": Measured(n=500, precision=1.0),
        "og": Measured(n=40, precision=0.5),
    }

    assert fit_order(("jsonld", "og"), measured) == ("jsonld", "og")


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


def test_orders_read_each_types_cells() -> None:
    by_source = {
        "url|jsonld": Measured(n=100, precision=0.7),
        "url|og": Measured(n=100, precision=0.99),
        "text|og": Measured(n=100, precision=0.5),
        "text|jsonld": Measured(n=100, precision=0.95),
        "money|og": Measured(n=100, precision=1.0),  # an agreement type: not ranked
    }

    fitted = fit_orders({"text": ("og", "jsonld"), "url": ("jsonld", "og")}, by_source)

    assert fitted == {"text": ("jsonld", "og"), "url": ("og", "jsonld")}


def test_buckets_below_the_floor_or_unmeasured_are_left_out_and_the_rest_are_shrunk() -> None:
    cells = {
        "a|dom": (MIN_CALIBRATED_N, 1.0),
        "b|dom": (MIN_CALIBRATED_N - 1, 1.0),
        "c|dom": (500, None),
        "d|dom": (100, 0.9),
    }

    fitted = fit_buckets(cells)

    assert {key: (bucket.n, bucket.precision) for key, bucket in fitted.items()} == {
        "a|dom": (MIN_CALIBRATED_N, round(21 / 22, 4)),
        "d|dom": (100, round(91 / 102, 4)),
    }
