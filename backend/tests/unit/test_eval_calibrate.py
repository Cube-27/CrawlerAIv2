"""`crawlerai eval calibrate` and `crawlerai eval fit-precedence` (SPEC-03 §4.4, SPEC-05 §4.11, INV-02): both fit on a
dev run only, refuse every other split before opening a store, and stamp what they write with `source_split: dev`.
Synthetic runs only (C9)."""

import json
import uuid
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml

from crawlerai import cli
from crawlerai.cli import main
from crawlerai.db.models import EvalRunId, SourceKind, Split
from crawlerai.eval.calibrate import (
    NotDev,
    Orders,
    Precedence,
    PrecedenceMissing,
    calibrate,
    fit_precedence,
    read_precedence,
    write_calibration,
    write_precedence,
)
from crawlerai.eval.metrics import (
    EvalCase,
    PrecisionMetrics,
    Report,
    SchemaFields,
    SourceMetrics,
    Suppressed,
    build_report,
)
from crawlerai.eval.store import EvalRunRow
from crawlerai.resolve.evidence import load_calibration
from crawlerai.resolve.preference import PRECEDENCE_TYPES, STAMP, load_precedence
from crawlerai.schemas.types import FieldSpec, FieldType

RUN_ID = EvalRunId(uuid.UUID("01900000-0000-7000-8000-000000000001"))
SHA = "a" * 40
CURRENT = "text: [adapter, api, jsonld, microdata, og, config, llm]\nurl: [adapter, jsonld, og]\n"


def _run(
    split: Split = "dev",
    by_bucket: Mapping[str, PrecisionMetrics | Suppressed] | None = None,
    by_source: Mapping[str, SourceMetrics | Suppressed] | None = None,
) -> EvalRunRow:
    report = Report(
        engine_version=f"{SHA}+cal.none",
        git_sha=SHA,
        split=split,
        n_pages=3,
        by_field_type={},
        by_field={},
        by_bucket=dict(by_bucket or {}),
        by_config_status={},
        by_category={},
        acquisition={},
        usage={},
        by_source=dict(by_source or {}),
    )
    return EvalRunRow(
        id=RUN_ID,
        split=split,
        engine_version=report.engine_version,
        git_sha=SHA,
        metrics=report.model_dump(mode="json"),
    )


def test_calibration_is_the_dev_runs_bucket_table_stamped_with_its_source(tmp_path: Path) -> None:
    run = _run(
        by_bucket={
            "money|structured": PrecisionMetrics(precision=0.982, n=112),
            "text|llm_grounded": PrecisionMetrics(precision=None, n=0),
        }
    )

    path = write_calibration(calibrate(run), tmp_path)

    assert path == tmp_path / "calibration.json"
    assert json.loads(path.read_bytes()) == {
        "calibration_version": 1,
        "source_split": "dev",
        "eval_run_id": str(RUN_ID),
        "git_sha": SHA,
        "buckets": {
            "money|structured": {"n": 112, "precision": 0.982},
            "text|llm_grounded": {"n": 0, "precision": None},
        },
    }


def test_a_suppressed_bucket_keeps_its_size_and_no_precision(tmp_path: Path) -> None:
    run = _run(by_bucket={"url|agreed": Suppressed(n=4)})

    buckets = json.loads(write_calibration(calibrate(run), tmp_path).read_bytes())["buckets"]

    assert buckets == {"url|agreed": {"n": 4, "precision": None}}


def test_calibrating_the_same_run_twice_writes_the_same_bytes(tmp_path: Path) -> None:
    # The engine version hashes this file (SPEC-01 §4.7), so a refit of the same run must not change it.
    run = _run(by_bucket={"b|agreed": PrecisionMetrics(precision=1.0, n=40), "a|adapter": Suppressed(n=2)})
    first = write_calibration(calibrate(run), tmp_path / "1").read_bytes()

    second = write_calibration(calibrate(run), tmp_path / "2").read_bytes()

    assert first == second
    assert first.endswith(b"}\n")
    assert b"\r" not in first


def test_calibration_refuses_a_run_that_is_not_dev() -> None:
    run = _run("hidden")

    with pytest.raises(NotDev, match="refusing the hidden split"):
        calibrate(run)


def test_a_run_without_per_kind_cells_keeps_the_current_order(tmp_path: Path) -> None:
    # SPEC-05 §4.11 keeps an unmeasured kind in its place; a run older than the per-kind table measured none.
    (tmp_path / "source_precedence.yaml").write_text(CURRENT, encoding="utf-8")

    path = write_precedence(fit_precedence(_run(), read_precedence(tmp_path)), tmp_path)

    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {
        "source_split": "dev",
        "eval_run_id": str(RUN_ID),
        "git_sha": SHA,
        "text": ["adapter", "api", "jsonld", "microdata", "og", "config", "llm"],
        "url": ["adapter", "jsonld", "og"],
    }
    # A refit reads its own output back: the stamp is not a field type.
    assert read_precedence(tmp_path) == {
        "text": ("adapter", "api", "jsonld", "microdata", "og", "config", "llm"),
        "url": ("adapter", "jsonld", "og"),
    }


def test_precedence_orders_the_measured_kinds_by_dev_precision(tmp_path: Path) -> None:
    run = _run(
        by_source={
            "url|jsonld": SourceMetrics(precision=0.90, coverage=0.9, n=40),
            "url|og": SourceMetrics(precision=0.99, coverage=0.5, n=40),
            "url|adapter": Suppressed(n=3),
        }
    )
    current: Orders = {"url": ("adapter", "jsonld", "og")}

    path = write_precedence(fit_precedence(run, current), tmp_path)

    assert yaml.safe_load(path.read_text(encoding="utf-8"))["url"] == ["adapter", "og", "jsonld"]


def test_precedence_needs_a_current_order_to_refit(tmp_path: Path) -> None:
    with pytest.raises(PrecedenceMissing, match=r"no source_precedence\.yaml"):
        read_precedence(tmp_path)


@pytest.mark.parametrize("text", ["- adapter\n", "text: adapter\n", "text: [adapter, 3]\n"])
def test_a_malformed_precedence_file_is_refused(tmp_path: Path, text: str) -> None:
    (tmp_path / "source_precedence.yaml").write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match=r"source_precedence\.yaml"):
        read_precedence(tmp_path)


def test_precedence_refuses_a_run_that_is_not_dev() -> None:
    run = _run("hidden")
    current: Orders = {"text": ("adapter",)}

    with pytest.raises(NotDev, match="refusing the hidden split"):
        fit_precedence(run, current)


@pytest.mark.parametrize("command", ["calibrate", "fit-precedence"])
def test_the_commands_exit_non_zero_on_a_private_split_without_opening_a_store(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    split = "fresh"

    def no_store(*args: object) -> None:
        raise AssertionError("a store was opened")

    monkeypatch.setattr(cli, "dev_store", no_store)
    monkeypatch.setattr(cli, "private_store", no_store)
    argv = ["eval", command, "--split", split, "--run", str(RUN_ID)]

    with pytest.raises(SystemExit) as exit_:
        main(argv)

    assert exit_.value.code == 2
    assert f"refusing the {split} split" in capsys.readouterr().err


def test_the_precedence_reader_skips_exactly_the_stamp_the_writer_adds() -> None:
    # `resolve.preference` reads the file and cannot import eval, so the two lists are checked here.
    assert set(Precedence.model_fields) - {"orders"} == STAMP


# From a dev run's pages to the files the engine reads (SPEC-05 §4.11, §8 PR 13: files written from a dev run).

TITLED = SchemaFields(name="titled", page_kind="detail", fields={"title": FieldSpec(type=FieldType.TEXT)})


def _case(i: int) -> EvalCase:
    # jsonld offers the right title and wins; og offers a wrong one and loses under the current order.
    return EvalCase.model_validate(
        {
            "page_id": f"p{i:03}",
            "category": "mixed",
            "schema_def": TITLED,
            "labels": {
                "label_version": 1,
                "status": "checked",
                "labeler": "labeler-a",
                "checker": "checker-b",
                "fields": {"title": {"value": f"Item {i}", "absent": False, "distractors": []}},
                "rows": [],
            },
            "output": {
                "block_class": "ok",
                "mode": "adhoc",
                "fields": {
                    "title": {
                        "status": "published",
                        "value": f"Item {i}",
                        "evidence": "structured",
                        "offered": {"jsonld": [f"Item {i}"], "og": [f"Other {i}"]},
                    }
                },
            },
        }
    )


@pytest.mark.parametrize(("pages", "fitted"), [(29, False), (30, True)])
def test_a_dev_run_fits_files_the_engine_reads(tmp_path: Path, pages: int, fitted: bool) -> None:
    report = build_report([_case(i) for i in range(pages)], "dev", engine_version=f"{SHA}+cal.none", git_sha=SHA)
    run = EvalRunRow(
        id=RUN_ID,
        split="dev",
        engine_version=report.engine_version,
        git_sha=SHA,
        metrics=report.model_dump(mode="json"),
    )
    order: tuple[SourceKind, ...] = ("og", "jsonld")
    current = {t.value: order for t in sorted(PRECEDENCE_TYPES)}

    calibration = load_calibration(write_calibration(calibrate(run), tmp_path))
    orders = load_precedence(write_precedence(fit_precedence(run, current), tmp_path))

    assert calibration is not None
    assert calibration.measure(FieldType.TEXT, "structured") == (1.0, fitted)
    assert orders[FieldType.TEXT] == (("jsonld", "og") if fitted else order)
    assert all(orders[t] == order for t in PRECEDENCE_TYPES - {FieldType.TEXT})
