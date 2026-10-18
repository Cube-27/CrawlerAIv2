"""`crawlerai eval fit-calibration` and `crawlerai eval fit-precedence`: write `calibration.json` and
`source_precedence.yaml` from a dev report (`crawlerai eval run --out`).

Each stamps what it writes with `source_split: dev` and the report's commit; the engine reads them back with
`resolve.evidence` and `resolve.preference`. Both files hold bucket and source-kind names and numbers only, no site.
The report must be scored on the labeled rows (the `evaluation` spec) by an engine without a calibration: a
calibrated run measures only what τ let through, so a fit on it would be of its own selection.
"""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from crawlerai.core.engine_version import CALIBRATION_FILE
from crawlerai.db.models import SourceKind
from crawlerai.eval.cli import EvalCliError
from crawlerai.eval.metrics import Report, SourceMetrics
from crawlerai.resolve.calibrate import Measured, fit_buckets, fit_orders
from crawlerai.resolve.evidence import Calibration
from crawlerai.resolve.preference import PRECEDENCE_FILE, parse_orders
from crawlerai.storage.fs import FsStore

Orders = dict[str, tuple[SourceKind, ...]]  # field type -> source kinds, first wins (SPEC-05 §4.7)


class PrecedenceMissing(EvalCliError):
    """There is no current source precedence to refit."""


class ReportRefused(EvalCliError):
    """The report is not one a fit may read."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Precedence(_Model):
    source_split: Literal["dev"] = "dev"
    git_sha: str
    orders: Orders


def read_report(path: Path) -> Report:
    """The dev report at `path`, refused unless it is a fit's input: scored on the labeled rows, by an engine whose
    calibration was absent."""
    try:
        report = Report.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as e:
        raise ReportRefused(f"cannot read {path.name} as a report: {type(e).__name__}") from e
    if report.split != "dev":
        raise ReportRefused(f"{path.name} is a {report.split} report: a fit reads the dev split only")
    if report.rows_scored != "labeled":
        raise ReportRefused(f"{path.name} scores every engine row: fit on the report `eval run --out` writes")
    if not report.engine_version.endswith("+cal.none"):
        raise ReportRefused(f"{path.name} was run with a calibration: move calibration.json away and run again")
    return report


def fit_calibration(report: Report) -> Calibration:
    cells = {key: (cell.n, cell.precision) for key, cell in report.by_bucket.items()}
    return Calibration(git_sha=report.git_sha, buckets=fit_buckets(cells))


def fit_precedence(report: Report, current: Mapping[str, Sequence[SourceKind]]) -> Precedence:
    return Precedence(git_sha=report.git_sha, orders=fit_orders(current, _measured(report.by_source)))


def _measured(cells: Mapping[str, SourceMetrics]) -> dict[str, Measured]:
    return {key: Measured(n=cell.n, precision=cell.precision) for key, cell in cells.items()}


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
