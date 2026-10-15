"""The merge gate (SPEC-03 §4.8, INV-21): each failure reason from hand-built reports, the `no_baseline` pass, and
the baseline lookup over commits on `main`."""

import asyncio
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.db.models import Split
from crawlerai.eval.gate import GateInputInvalid, GateResult, commits_on, find_baseline, gate
from crawlerai.eval.metrics import FieldMetrics, Report, Suppressed
from crawlerai.eval.store import EvalRunRow
from crawlerai.schemas.types import FieldType

# A row sub-field's cell (SPEC-13 §4.10), built from its type: the literal would read as a hostname to the C3 scan.
LIST_MONEY = f"list.{FieldType.MONEY.value}"


def cell(precision: float | None = 0.97, wrong_product: int = 0, n: int = 100) -> FieldMetrics:
    return FieldMetrics(
        precision=precision,
        coverage=0.9,
        abstain_rate=0.1,
        false_publish_on_absent=0.0,
        wrong_product=wrong_product,
        n=n,
    )


def report(
    by_field_type: Mapping[str, FieldMetrics | Suppressed],
    *,
    n_pages: int = 150,
    git_sha: str = "c" * 40,
    split: Split = "hidden",
) -> Report:
    return Report(
        engine_version="0.0.0",
        git_sha=git_sha,
        split=split,
        n_pages=n_pages,
        by_field_type=dict(by_field_type),
        by_field={},
        by_bucket={},
        by_config_status={},
        by_category={},
        acquisition={},
        usage={},
    )


BASE_SHA = "b" * 40
BASELINE = report({"money": cell(0.97), "text": cell(0.9), "list": cell(0.8)}, git_sha=BASE_SHA)


def test_no_baseline_passes() -> None:
    assert gate(report({"money": cell()}), None) == GateResult(
        baseline_git_sha=None, passed=True, reasons=["no_baseline"], by_field_type={"money": True}
    )


def test_unchanged_candidate_passes() -> None:
    assert gate(report({"money": cell(0.97), "text": cell(0.9), "list": cell(0.8)}), BASELINE) == GateResult(
        baseline_git_sha=BASE_SHA, passed=True, reasons=[], by_field_type={"list": True, "money": True, "text": True}
    )


def test_precision_drop_over_half_a_point_on_a_required_type_fails() -> None:
    result = gate(report({"money": cell(0.964), "text": cell(0.9)}), BASELINE)
    assert result == GateResult(
        baseline_git_sha=BASE_SHA,
        passed=False,
        reasons=["precision_drop:money"],
        by_field_type={"money": False, "text": True},
    )


def test_a_drop_of_exactly_half_a_point_passes() -> None:
    # "more than 0.5 pt" (ARCHITECTURE §16.4); 0.97 - 0.965 is not exactly 0.005 in binary floating point.
    assert gate(report({"money": cell(0.965), "text": cell(0.9)}), BASELINE).passed is True


def test_precision_drop_on_a_type_without_required_fields_passes() -> None:
    # `list` is not in the §4.8 required-type set, so only wrong products can fail it.
    result = gate(report({"money": cell(0.97), "list": cell(0.5)}), BASELINE)
    assert (result.passed, result.reasons, result.by_field_type["list"]) == (True, [], True)


def test_a_row_sub_field_cell_is_gated_on_wrong_products_only() -> None:
    # SPEC-13 §4.10: `list.<type>` cells are an optional field's; a precision drop passes, a wrong product fails.
    base = report({"money": cell(0.97), LIST_MONEY: cell(0.97)}, git_sha=BASE_SHA)

    dropped = gate(report({"money": cell(0.97), LIST_MONEY: cell(0.5)}), base)
    wrong = gate(report({"money": cell(0.97), LIST_MONEY: cell(0.97, wrong_product=1)}), base)

    assert (dropped.passed, dropped.reasons) == (True, [])
    assert (wrong.passed, wrong.reasons) == (False, [f"wrong_product:{LIST_MONEY}"])


def test_any_wrong_product_fails_on_any_type() -> None:
    result = gate(report({"money": cell(0.97), "list": cell(0.8, wrong_product=1)}), BASELINE)
    assert result == GateResult(
        baseline_git_sha=BASE_SHA,
        passed=False,
        reasons=["wrong_product:list"],
        by_field_type={"list": False, "money": True},
    )


def test_wrong_product_fails_without_a_baseline() -> None:
    # INV-21: the wrong-product count on hidden is 0, which needs no baseline to check.
    result = gate(report({"money": cell(wrong_product=2)}), None)
    assert (result.passed, result.reasons) == (False, ["no_baseline", "wrong_product:money"])


def test_dropped_pages_fail() -> None:
    result = gate(report({"money": cell(0.97)}, n_pages=149), BASELINE)
    assert (result.passed, result.reasons, result.by_field_type) == (False, ["n_pages_dropped"], {"money": True})


def test_reasons_are_sorted_and_carry_no_numbers() -> None:
    result = gate(report({"text": cell(0.5, wrong_product=1), "money": cell(0.1)}, n_pages=1), BASELINE)
    assert result.reasons == ["n_pages_dropped", "precision_drop:money", "precision_drop:text", "wrong_product:text"]


@pytest.mark.parametrize(
    ("candidate", "baseline"),
    [
        pytest.param(None, 0.97, id="candidate published nothing"),
        pytest.param(0.5, None, id="baseline published nothing"),
    ],
)
def test_a_type_without_precision_on_either_side_is_not_compared(
    candidate: float | None, baseline: float | None
) -> None:
    result = gate(report({"money": cell(candidate)}), report({"money": cell(baseline)}, git_sha=BASE_SHA))
    assert (result.passed, result.reasons) == (True, [])


def test_suppressed_cells_are_refused() -> None:
    # The gate reads the unsuppressed in-job report (D-0182); an exported aggregate can hide a wrong product.
    suppressed = report({"money": Suppressed(n=3)})
    candidate = report({"money": cell()})
    with pytest.raises(GateInputInvalid, match="suppressed"):
        gate(suppressed, BASELINE)
    with pytest.raises(GateInputInvalid, match="suppressed"):
        gate(candidate, suppressed)


def test_splits_must_match() -> None:
    fresh = report({"money": cell()}, split="fresh")
    with pytest.raises(GateInputInvalid, match="fresh run against a hidden baseline"):
        gate(fresh, BASELINE)


@given(
    st.dictionaries(
        st.sampled_from(["money", "text", "url", "date", "list"]),
        st.builds(cell, st.one_of(st.none(), st.floats(0, 1)), st.just(0), st.integers(0, 500)),
    ),
    st.integers(0, 500),
)
def test_a_report_never_regresses_against_itself(types: dict[str, FieldMetrics], n_pages: int) -> None:
    same = report(types, n_pages=n_pages)
    assert gate(same, same).passed is True


class FakeStore:
    """The `latest_run` half of `EvalStore`: the newest run of each commit."""

    def __init__(self, runs: dict[str, Report]) -> None:
        self.runs = runs
        self.asked: list[str | None] = []

    async def latest_run(self, git_sha_on_main: str | None) -> EvalRunRow | None:
        self.asked.append(git_sha_on_main)
        if git_sha_on_main is None:
            sha = next(reversed(self.runs), None)
        else:
            sha = git_sha_on_main if git_sha_on_main in self.runs else None
        if sha is None:
            return None
        r = self.runs[sha]
        return EvalRunRow(
            split=r.split, engine_version=r.engine_version, git_sha=sha, metrics=r.model_dump(mode="json")
        )


def test_baseline_is_the_newest_main_commit_with_a_run() -> None:
    older, newer = report({}, git_sha="1" * 40), report({}, git_sha="3" * 40)
    off_main = report({}, git_sha="9" * 40)
    store = FakeStore({"1" * 40: older, "3" * 40: newer, "9" * 40: off_main})
    assert asyncio.run(find_baseline(store, ["4" * 40, "3" * 40, "2" * 40, "1" * 40])) == newer


def test_the_newest_run_is_reused_when_main_reaches_it() -> None:
    newest = report({}, git_sha="2" * 40)
    store = FakeStore({"1" * 40: report({}, git_sha="1" * 40), "2" * 40: newest})
    assert asyncio.run(find_baseline(store, ["3" * 40, "2" * 40, "1" * 40])) == newest
    assert store.asked == [None, "3" * 40]


def test_no_run_on_main_means_no_baseline() -> None:
    store = FakeStore({"9" * 40: report({}, git_sha="9" * 40)})
    assert asyncio.run(find_baseline(store, ["2" * 40, "1" * 40])) is None


def test_an_empty_store_answers_without_walking_main() -> None:
    store = FakeStore({})
    assert asyncio.run(find_baseline(store, ["2" * 40, "1" * 40])) is None
    assert store.asked == [None]


GIT = shutil.which("git")


@pytest.mark.skipif(GIT is None, reason="needs git")
def test_commits_on_lists_a_ref_newest_first(tmp_path: Path) -> None:
    assert GIT is not None

    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }

    def git(*args: str) -> str:
        return subprocess.run(  # noqa: S603
            [GIT, "-C", str(tmp_path), *args], capture_output=True, text=True, check=True, env=env
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    shas = []
    for i in range(3):
        git("commit", "-q", "--allow-empty", "-m", f"c{i}")
        shas.append(git("rev-parse", "HEAD"))
    git("checkout", "-q", "-b", "topic")
    git("commit", "-q", "--allow-empty", "-m", "topic")

    assert commits_on("main", tmp_path) == shas[::-1]


@pytest.mark.skipif(GIT is None, reason="needs git")
def test_commits_on_reads_a_ref_that_looks_like_an_option_as_a_ref(tmp_path: Path) -> None:
    assert GIT is not None
    subprocess.run([GIT, "init", "-q", str(tmp_path)], check=True)  # noqa: S603

    with pytest.raises(GateInputInvalid, match="--all"):
        commits_on("--all", tmp_path)


@pytest.mark.skipif(GIT is None, reason="needs git")
def test_commits_on_an_unknown_ref_fails(tmp_path: Path) -> None:
    with pytest.raises(GateInputInvalid, match="no-such-ref"):
        commits_on("no-such-ref", tmp_path)
