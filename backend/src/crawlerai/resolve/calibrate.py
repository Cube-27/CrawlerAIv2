"""Precedence fitting (SPEC-05 §4.11, ARCHITECTURE §10): the fit behind `crawlerai eval fit-precedence`
(`eval.calibrate`), from a dev run's measurements. Calibration needs no fit: a bucket's calibration is its dev
measurement, which `eval.calibrate` copies from the run's report.

An order ranks the source kinds of one field type by how often each kind's own value is right on dev, wherever it
offered one, whether or not it won: the order is what decides between them, so it is fitted on every kind's values,
not only on the winners'.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from crawlerai.db.models import SourceKind
from crawlerai.resolve.evidence import MIN_CALIBRATED_N


@dataclass(frozen=True, slots=True)
class Measured:
    """One dev cell of a source kind: `n` judged fields, the precision of their values, and the coverage of the
    labeled values. `precision` is `None` when no field of the cell could be scored."""

    n: int
    precision: float | None
    coverage: float | None = None


def fit_orders(
    current: Mapping[str, Sequence[SourceKind]], by_source: Mapping[str, Measured]
) -> dict[str, tuple[SourceKind, ...]]:
    """Each order of `current` refitted from its type's `"field_type|source_kind"` cells."""
    return {
        type_: fit_order(order, {kind: cell for kind in order if (cell := by_source.get(f"{type_}|{kind}"))})
        for type_, order in current.items()
    }


def fit_order(current: Sequence[SourceKind], measured: Mapping[SourceKind, Measured]) -> tuple[SourceKind, ...]:
    """§4.11: the kinds measured on at least `MIN_CALIBRATED_N` fields, by precision then coverage, in the places
    those kinds hold now; every other kind keeps its place. A full tie keeps the current order (a stable sort). The
    set of kinds is the current one: a kind the order leaves out stays out (it never wins, D-0020)."""
    ranked = [kind for kind in current if _ranks(measured.get(kind))]
    by_precision = iter(sorted(ranked, key=lambda kind: _rank_key(measured[kind])))
    return tuple(next(by_precision) if kind in ranked else kind for kind in current)


def _ranks(cell: Measured | None) -> bool:
    # ARCHITECTURE §10's 30-label floor, as for a calibrated bucket.
    return cell is not None and cell.precision is not None and cell.n >= MIN_CALIBRATED_N


def _rank_key(cell: Measured) -> tuple[float, float]:
    # `_ranks` holds, so the precision is measured; a missing coverage ranks last among equal precisions.
    return -(cell.precision or 0.0), -(cell.coverage or 0.0)
