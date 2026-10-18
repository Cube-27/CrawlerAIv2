"""`crawlerai eval calibrate` and `crawlerai eval fit-precedence`: write `calibration.json` and
`source_precedence.yaml` from a stored run on the golden set.

Each stamps what it writes with `source_split: dev`, the run's id and its commit; the engine reads them back with
`resolve.evidence` and `resolve.preference`. Calibration is the run's bucket table; precedence is fitted from its
per-kind table (`by_source`) by `resolve.calibrate`.
"""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from crawlerai.core.engine_version import CALIBRATION_FILE
from crawlerai.db.models import EvalRunId, SourceKind
from crawlerai.eval.cli import EvalCliError
from crawlerai.eval.metrics import PrecisionMetrics, Report, SourceMetrics
from crawlerai.eval.store import EvalRunRow
from crawlerai.resolve.calibrate import Measured, fit_orders
from crawlerai.resolve.evidence import Bucket, Calibration
from crawlerai.resolve.preference import PRECEDENCE_FILE, parse_orders
from crawlerai.storage.fs import FsStore

Orders = dict[str, tuple[SourceKind, ...]]  # field type -> source kinds, first wins (SPEC-05 §4.7)


class PrecedenceMissing(EvalCliError):
    """There is no current source precedence to refit."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Precedence(_Model):
    source_split: Literal["dev"] = "dev"
    eval_run_id: EvalRunId
    git_sha: str
    orders: Orders


def calibrate(run: EvalRunRow) -> Calibration:
    report = Report.model_validate(run.metrics)
    return Calibration(eval_run_id=run.id, git_sha=run.git_sha, buckets=_buckets(report.by_bucket))


def fit_precedence(run: EvalRunRow, current: Mapping[str, Sequence[SourceKind]]) -> Precedence:
    report = Report.model_validate(run.metrics)
    return Precedence(eval_run_id=run.id, git_sha=run.git_sha, orders=fit_orders(current, _measured(report.by_source)))


def _buckets(cells: Mapping[str, PrecisionMetrics]) -> dict[str, Bucket]:
    return {key: Bucket(n=cell.n, precision=cell.precision) for key, cell in sorted(cells.items())}


def _measured(cells: Mapping[str, SourceMetrics]) -> dict[str, Measured]:
    return {key: Measured(n=cell.n, precision=cell.precision, coverage=cell.coverage) for key, cell in cells.items()}


def write_calibration(calibration: Calibration, data_dir: Path) -> Path:
    # Sorted keys and LF bytes: the engine version hashes this file (SPEC-01 §4.7), so the same fit gives one version.
    text = json.dumps(calibration.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return _write(data_dir / CALIBRATION_FILE, text)


def read_precedence(data_dir: Path) -> Orders:
    """The orders of the current `source_precedence.yaml` (`resolve.preference.parse_orders`)."""
    path = data_dir / PRECEDENCE_FILE
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PrecedenceMissing(f"no {PRECEDENCE_FILE} to refit; SPEC-05 commits the initial order") from None
    return {type_: tuple(order) for type_, order in parse_orders(document).items()}


def write_precedence(precedence: Precedence, data_dir: Path) -> Path:
    # SPEC-05 §4.7's shape: the stamp, then one list of source kinds per field type, in the fit's order.
    document = precedence.model_dump(mode="json", exclude={"orders"}) | {
        type_: list(order) for type_, order in precedence.orders.items()
    }
    return _write(data_dir / PRECEDENCE_FILE, yaml.safe_dump(document, sort_keys=False))


def _write(path: Path, text: str) -> Path:
    # Atomic (temp file, then rename): a crash never leaves a truncated file for the engine version to hash.
    FsStore(path.parent).put(path.name, text.encode())
    return path
