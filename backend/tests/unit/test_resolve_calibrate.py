"""Precedence fitting (SPEC-05 §4.11, ARCHITECTURE §10, INV-02): each precedence type's order by per-kind dev
precision, ties by coverage, kinds measured on fewer than 30 fields kept in place. Synthetic measurements only (C9)."""

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.db.models import SourceKind
from crawlerai.resolve.calibrate import Measured, fit_order, fit_orders

ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")


def test_kinds_order_by_dev_precision() -> None:
    measured: dict[SourceKind, Measured] = {
        "jsonld": Measured(n=100, precision=0.90, coverage=0.8),
        "og": Measured(n=60, precision=0.99, coverage=0.4),
        "microdata": Measured(n=30, precision=0.95, coverage=0.1),
    }

    assert fit_order(("jsonld", "microdata", "og"), measured) == ("og", "microdata", "jsonld")


def test_equal_precision_orders_by_coverage() -> None:
    measured: dict[SourceKind, Measured] = {
        "jsonld": Measured(n=50, precision=0.98, coverage=0.2),
        "og": Measured(n=50, precision=0.98, coverage=0.7),
    }

    assert fit_order(("jsonld", "og"), measured) == ("og", "jsonld")


def test_a_full_tie_keeps_the_current_order() -> None:
    measured: dict[SourceKind, Measured] = {
        "og": Measured(n=50, precision=0.98, coverage=0.5),
        "jsonld": Measured(n=50, precision=0.98, coverage=0.5),
    }

    assert fit_order(("og", "jsonld"), measured) == ("og", "jsonld")


def test_a_kind_measured_on_fewer_than_30_fields_keeps_its_place() -> None:
    measured: dict[SourceKind, Measured] = {
        "adapter": Measured(n=29, precision=0.50, coverage=0.1),
        "jsonld": Measured(n=30, precision=0.90, coverage=0.5),
        "og": Measured(n=30, precision=0.99, coverage=0.5),
    }

    # adapter stays first; the two measured kinds swap in the slots they held.
    assert fit_order(("adapter", "jsonld", "og"), measured) == ("adapter", "og", "jsonld")


def test_an_unmeasured_kind_keeps_its_place() -> None:
    measured: dict[SourceKind, Measured] = {
        "jsonld": Measured(n=40, precision=0.80),
        "og": Measured(n=40, precision=0.90),
    }

    assert fit_order(("jsonld", "llm", "og"), measured) == ("og", "llm", "jsonld")


def test_a_measured_kind_outside_the_order_is_not_added() -> None:
    measured: dict[SourceKind, Measured] = {
        "js_state": Measured(n=500, precision=1.0, coverage=1.0),
        "og": Measured(n=40, precision=0.5),
    }

    assert fit_order(("jsonld", "og"), measured) == ("jsonld", "og")


def test_a_kind_without_a_precision_keeps_its_place() -> None:
    # Every field it offered sits in a suppressed cell, or none had a label to compare with.
    measured: dict[SourceKind, Measured] = {
        "jsonld": Measured(n=40, precision=None),
        "og": Measured(n=40, precision=0.9),
    }

    assert fit_order(("og", "jsonld"), measured) == ("og", "jsonld")


@given(
    st.permutations(ORDER),
    st.dictionaries(
        st.sampled_from(ORDER),
        st.builds(
            Measured,
            n=st.integers(0, 100),
            precision=st.none() | st.floats(0, 1),
            coverage=st.none() | st.floats(0, 1),
        ),
    ),
)
def test_a_fit_permutes_the_order_and_never_moves_a_kind_under_30(
    current: list[SourceKind], measured: dict[SourceKind, Measured]
) -> None:
    fitted = fit_order(tuple(current), measured)

    assert sorted(fitted) == sorted(current)
    precisions: list[float] = []
    for i, kind in enumerate(current):
        cell = measured.get(kind)
        if cell is None or cell.n < 30 or cell.precision is None:
            assert fitted[i] == kind
        elif (placed := measured[fitted[i]].precision) is not None:
            precisions.append(placed)
    assert precisions == sorted(precisions, reverse=True)


def test_orders_read_each_types_cells() -> None:
    by_source = {
        "url|jsonld": Measured(n=40, precision=0.9),
        "url|og": Measured(n=40, precision=0.99),
        "text|og": Measured(n=40, precision=0.5),
        "text|jsonld": Measured(n=40, precision=0.95),
        "money|og": Measured(n=40, precision=1.0),  # an agreement type: not ranked
    }

    fitted = fit_orders({"text": ("og", "jsonld"), "url": ("jsonld", "og")}, by_source)

    assert fitted == {"text": ("jsonld", "og"), "url": ("og", "jsonld")}
