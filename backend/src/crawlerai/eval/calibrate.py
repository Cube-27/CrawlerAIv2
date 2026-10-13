"""`crawlerai eval calibrate` and `crawlerai eval fit-precedence` (SPEC-03 §4.4): write `calibration.json` and
`source_precedence.yaml` from a dev eval run.

Both are fitted on dev only (C1, INV-02): each refuses a run of any other split, and stamps what it writes with
`source_split: dev`, the run's id and its commit; the engine reads them back with `resolve.evidence` and
`resolve.preference`. The fits are parameters. SPEC-05 §4.11 brings its own
(`resolve/calibrate`); until then calibration is the run's bucket table, and precedence keeps the current order.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from crawlerai.core.engine_version import CALIBRATION_FILE
from crawlerai.db.models import EvalRunId, Split
from crawlerai.eval.cli import EvalCliError
from crawlerai.eval.metrics import PrecisionMetrics, Report
from crawlerai.eval.store import EvalRunRow
from crawlerai.resolve.evidence import Bucket, Calibration
from crawlerai.resolve.preference import PRECEDENCE_FILE, parse_orders
from crawlerai.storage.fs import FsStore

Orders = dict[str, tuple[str, ...]]  # field type -> source kinds, first wins (SPEC-05 §4.7)


class NotDev(EvalCliError):
    """A fit was asked of a split other than dev."""


class PrecedenceMissing(EvalCliError):
    """There is no current source precedence to refit."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Precedence(_Model):
    source_split: Literal["dev"] = "dev"
    eval_run_id: EvalRunId
    git_sha: str
    orders: Orders


CalibrationFit = Callable[[EvalRunRow], dict[str, Bucket]]
PrecedenceFit = Callable[[EvalRunRow, Mapping[str, Sequence[str]]], Orders]


def require_dev(split: Split) -> None:
    if split != "dev":
        raise NotDev(f"calibration and precedence are fitted on dev only (INV-02); refusing the {split} split")


def run_buckets(run: EvalRunRow) -> dict[str, Bucket]:
    """The run's `by_bucket` table: `n` and precision of the published fields per field type and evidence bucket,
    which is SPEC-05 §4.11's definition. A suppressed cell keeps its size and has no precision."""
    report = Report.model_validate(run.metrics)
    return {
        key: Bucket(n=cell.n, precision=cell.precision if isinstance(cell, PrecisionMetrics) else None)
        for key, cell in report.by_bucket.items()
    }


def keep_order(run: EvalRunRow, current: Mapping[str, Sequence[str]]) -> Orders:
    """SPEC-05 §4.11 keeps a source kind with n < 30 in its place. The dev report has no per-kind counts yet, so every
    kind keeps its place."""
    return {type_: tuple(order) for type_, order in current.items()}


def calibrate(run: EvalRunRow, fit: CalibrationFit = run_buckets) -> Calibration:
    require_dev(run.split)
    return Calibration(eval_run_id=run.id, git_sha=run.git_sha, buckets=dict(sorted(fit(run).items())))


def fit_precedence(
    run: EvalRunRow, current: Mapping[str, Sequence[str]], fit: PrecedenceFit = keep_order
) -> Precedence:
    require_dev(run.split)
    return Precedence(eval_run_id=run.id, git_sha=run.git_sha, orders=fit(run, current))


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
