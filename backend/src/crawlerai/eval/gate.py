"""The merge gate (SPEC-03 §4.8, ARCHITECTURE §16.4, C10, INV-21): the hidden half of C10, non-regression.

`gate` compares a candidate report with its baseline: the report of the latest run of the same split whose commit
is on `main`, found by `find_baseline` over `commits_on("origin/main")`. Both reports are the unsuppressed in-job
form (D-0182). The result is pass/fail per field type plus reasons that carry no numbers, so it can be posted on a
PR (§16.4: numeric hidden aggregates go only to the custodian).
"""

import math
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from crawlerai.eval.metrics import FieldMetrics, Report
from crawlerai.eval.store import EvalRunRow
from crawlerai.schemas.types import FieldType

# SPEC-03 §4.8: the field types with at least one required field in a preset. The precision rule covers only these.
REQUIRED_FIELD_TYPES: frozenset[FieldType] = frozenset(
    {
        FieldType.MONEY,
        FieldType.TEXT,
        FieldType.LONG_TEXT,
        FieldType.ENUM,
        FieldType.URL,
        FieldType.IMAGE_URL,
        FieldType.IDENTIFIER,
        FieldType.DATE,
        FieldType.LOCATION,
    }
)

# ARCHITECTURE §16.4: a hidden precision drop of more than 0.5 pt fails the merge.
MAX_PRECISION_DROP = 0.005


class GateInputInvalid(Exception):
    """The gate was given reports it cannot compare, or a ref git cannot resolve."""


class GateResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    baseline_git_sha: str | None
    passed: bool
    reasons: list[str]  # sorted; no numbers
    by_field_type: dict[str, bool]  # pass/fail per field type of the candidate


def gate(candidate: Report, baseline: Report | None) -> GateResult:
    """Fail on a precision drop of more than `MAX_PRECISION_DROP` on a required field type, on any wrong product, or on
    fewer pages than the baseline (§16.4: pages are never silently dropped). Without a baseline it passes with
    `no_baseline`, unless a wrong product is published: that count must be 0 on its own (INV-21).

    A type without a precision on either side (nothing published) is not compared: an abstention is never wrong."""
    cells = _unsuppressed(candidate)
    base_cells = _unsuppressed(baseline) if baseline is not None else None
    if baseline is not None and baseline.split != candidate.split:
        raise GateInputInvalid(f"cannot gate a {candidate.split} run against a {baseline.split} baseline")

    reasons: list[str] = []
    by_field_type: dict[str, bool] = {}
    for type_, cell in sorted(cells.items()):
        type_reasons = []
        if cell.wrong_product > 0:
            type_reasons.append(f"wrong_product:{type_}")
        if base_cells is not None and type_ in REQUIRED_FIELD_TYPES and _precision_dropped(cell, base_cells.get(type_)):
            type_reasons.append(f"precision_drop:{type_}")
        by_field_type[type_] = not type_reasons
        reasons += type_reasons
    if baseline is not None and candidate.n_pages < baseline.n_pages:
        reasons.append("n_pages_dropped")
    passed = not reasons
    if baseline is None:
        reasons.append("no_baseline")  # informational: it never fails the gate

    return GateResult(
        baseline_git_sha=baseline.git_sha if baseline is not None else None,
        passed=passed,
        reasons=sorted(reasons),
        by_field_type=by_field_type,
    )


def _precision_dropped(cell: FieldMetrics, base: FieldMetrics | None) -> bool:
    if base is None or base.precision is None or cell.precision is None:
        return False
    drop = base.precision - cell.precision
    # A drop of exactly 0.5 pt passes ("more than"); the precisions are floats, so equality is approximate.
    return drop > MAX_PRECISION_DROP and not math.isclose(drop, MAX_PRECISION_DROP)


def _unsuppressed(report: Report) -> dict[str, FieldMetrics]:
    # An exported aggregate (`export_aggregate`) hides small cells, and with them their wrong-product counts.
    cells = {k: c for k, c in report.by_field_type.items() if isinstance(c, FieldMetrics)}
    if len(cells) != len(report.by_field_type):
        raise GateInputInvalid(
            f"the {report.split} report at {report.git_sha} has suppressed cells; gate the in-job report"
        )
    return cells


class RunHistory(Protocol):
    """The part of `EvalStore` the baseline lookup reads."""

    async def latest_run(self, git_sha_on_main: str | None) -> EvalRunRow | None: ...


async def find_baseline(store: RunHistory, main_commits: Iterable[str]) -> Report | None:
    """The report of the newest run whose commit is in `main_commits` (newest first), or None (§4.8)."""
    newest = await store.latest_run(None)
    if newest is None:
        return None  # no runs at all: skip the walk over main
    for sha in main_commits:
        run = newest if sha == newest.git_sha else await store.latest_run(sha)
        if run is not None:
            return Report.model_validate(run.metrics)
    return None


def commits_on(ref: str, repo: Path) -> list[str]:
    """Every commit reachable from `ref` in the repository at `repo`, newest first. CI needs the full history."""
    git = shutil.which("git")
    if git is None:
        raise GateInputInvalid("git is not on PATH")
    # A fixed argv with no shell. `--end-of-options` makes git read `ref` as a revision even when it starts with `-`,
    # so a ref can't become an option.
    result = subprocess.run(  # noqa: S603
        [git, "-C", str(repo), "rev-list", "--end-of-options", ref, "--"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise GateInputInvalid(f"git rev-list {ref} failed: {result.stderr.strip()}")
    return result.stdout.split()
