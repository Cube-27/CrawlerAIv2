"""Calibration and precedence fitting (SPEC-05 §4.11, ARCHITECTURE §10): the fits behind `crawlerai eval
fit-calibration` and `fit-precedence` (`eval.calibrate`), from a dev run's measurements.

A bucket's confidence is its dev precision under a Beta(1, 1) prior, `(tp + 1) / (n + 2)`: a small bucket is pulled
toward one half, so a handful of right values never reads as certainty. Only a bucket measured on at least
`MIN_CALIBRATED_N` fields is fitted; every other bucket is left out and so stays uncalibrated.

An order ranks the source kinds of one field type by how often each kind's own value is right on dev, wherever it
offered one, whether or not it won: the order is what decides between them, so it is fitted on every kind's values,
not only on the winners'. A kind moves ahead of another only when the data separates them: the intervals of their
precisions do not overlap, so a gap that sampling noise explains leaves the order as it is.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from crawlerai.db.models import SourceKind
from crawlerai.resolve.evidence import MIN_CALIBRATED_N, Bucket

# The two-sided 95% normal quantile, for the Wilson interval of a precision.
_Z: Final = 1.96


@dataclass(frozen=True, slots=True)
class Measured:
    """One dev cell of a source kind: `n` judged fields and the precision of their values. `precision` is `None` when
    no field of the cell could be scored."""

    n: int
    precision: float | None


def fit_orders(
    current: Mapping[str, Sequence[SourceKind]], by_source: Mapping[str, Measured]
) -> dict[str, tuple[SourceKind, ...]]:
    """Each order of `current` refitted from its type's `"field_type|source_kind"` cells."""
    return {
        type_: fit_order(order, {kind: cell for kind in order if (cell := by_source.get(f"{type_}|{kind}"))})
        for type_, order in current.items()
    }


def fit_order(current: Sequence[SourceKind], measured: Mapping[SourceKind, Measured]) -> tuple[SourceKind, ...]:
    """§4.11: of the kinds measured on at least `MIN_CALIBRATED_N` fields, one whose interval of precision lies wholly
    above the next measured kind's moves to just before it (D-1741); nothing else moves, so a kind the data does not
    separate keeps its place against every other, measured or not. The set of kinds is the current one: a kind the
    order leaves out stays out (it never wins, D-0020)."""
    order = list(current)
    moved = True
    while moved:  # each move removes one inversion among the measured kinds, so this ends
        moved = False
        ranked = [kind for kind in order if _ranks(measured.get(kind))]
        for ahead, behind in pairwise(ranked):
            if _lower(measured[behind]) > _upper(measured[ahead]):
                order.remove(behind)
                order.insert(order.index(ahead), behind)
                moved = True
                break
    return tuple(order)


def fit_buckets(cells: Mapping[str, tuple[int, float | None]]) -> dict[str, Bucket]:
    """The fitted table of `"field_type|evidence"` cells given as `(n, precision)`: the buckets measured on at least
    `MIN_CALIBRATED_N` fields, each with its Beta(1, 1) posterior mean as its confidence."""
    return {
        key: Bucket(n=n, precision=round((round(precision * n) + 1) / (n + 2), 4))
        for key, (n, precision) in sorted(cells.items())
        if precision is not None and n >= MIN_CALIBRATED_N
    }


def _ranks(cell: Measured | None) -> bool:
    return cell is not None and cell.precision is not None and cell.n >= MIN_CALIBRATED_N


def _interval(cell: Measured) -> tuple[float, float]:
    # The Wilson score interval; `_ranks` holds, so the precision is measured and `n` is positive.
    n, p = cell.n, cell.precision or 0.0
    centre = (p + _Z**2 / (2 * n)) / (1 + _Z**2 / n)
    half = _Z * math.sqrt(p * (1 - p) / n + _Z**2 / (4 * n**2)) / (1 + _Z**2 / n)
    return centre - half, centre + half


def _lower(cell: Measured) -> float:
    return _interval(cell)[0]


def _upper(cell: Measured) -> float:
    return _interval(cell)[1]
