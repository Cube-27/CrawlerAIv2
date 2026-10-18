"""`crawlerai eval fit-calibration` and `crawlerai eval fit-precedence` (SPEC-05 §4.11): both fit on a golden-set
report and stamp what they write with `source_split: dev`. Synthetic reports only (C9)."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml

from crawlerai import cli
from crawlerai.cli import main
from crawlerai.db.models import SourceKind
from crawlerai.eval.calibrate import (
    Orders,
    Precedence,
    PrecedenceMissing,
    ReportRefused,
    fit_calibration,
    fit_precedence,
    read_precedence,
    read_report,
    write_calibration,
    write_precedence,
)
from crawlerai.eval.metrics import EvalCase, PrecisionMetrics, Report, SchemaFields, SourceMetrics, build_report
from crawlerai.resolve.calibrate import fit_buckets
from crawlerai.resolve.evidence import MIN_CALIBRATED_N, load_calibration
from crawlerai.resolve.preference import PRECEDENCE_TYPES, STAMP, load_precedence
from crawlerai.schemas.types import FieldSpec, FieldType

SHA = "a" * 40
CURRENT = "text: [adapter, api, jsonld, microdata, og, config, llm]\nurl: [adapter, jsonld, og]\n"


def _report(
    by_bucket: Mapping[str, PrecisionMetrics] | None = None,
    by_source: Mapping[str, SourceMetrics] | None = None,
    **overrides: object,
) -> Report:
    fields: dict[str, object] = {
        "engine_version": f"{SHA}+cal.none",
        "git_sha": SHA,
        "split": "dev",
        "n_pages": 3,
        "by_field_type": {},
        "by_field": {},
        "by_bucket": dict(by_bucket or {}),
        "by_config_status": {},
        "by_category": {},
        "acquisition": {},
        "usage": {},
        "by_source": dict(by_source or {}),
        "rows_scored": "labeled",
    }
    return Report.model_validate(fields | overrides)


def test_calibration_holds_only_the_buckets_with_enough_labels(tmp_path: Path) -> None:
    report = _report(
        by_bucket={
            "money|structured": PrecisionMetrics(precision=0.982, n=112),
            "money|dom": PrecisionMetrics(precision=1.0, n=MIN_CALIBRATED_N - 1),
            "text|llm_grounded": PrecisionMetrics(precision=None, n=0),
        }
    )

    path = write_calibration(fit_calibration(report), tmp_path)

    assert path == tmp_path / "calibration.json"
    assert json.loads(path.read_bytes()) == {
        "calibration_version": 1,
        "source_split": "dev",
        "git_sha": SHA,
        "buckets": {"money|structured": {"n": 112, "precision": 0.9737}},
    }


def test_a_fitted_confidence_is_the_beta_posterior_mean_so_a_small_bucket_is_never_certain() -> None:
    cells = {"a|dom": (20, 1.0), "b|dom": (100, 0.9), "c|dom": (40, 0.0)}

    fitted = fit_buckets(cells)

    assert {key: bucket.precision for key, bucket in fitted.items()} == {
        "a|dom": round(21 / 22, 4),
        "b|dom": round(91 / 102, 4),
        "c|dom": round(1 / 42, 4),
    }


def test_fitting_the_same_report_twice_writes_the_same_bytes(tmp_path: Path) -> None:
    # The engine version hashes this file (SPEC-01 §4.7), so a refit of the same report must not change it.
    report = _report(
        by_bucket={
            "b|agreed": PrecisionMetrics(precision=1.0, n=40),
            "a|adapter": PrecisionMetrics(precision=0.9, n=40),
        }
    )
    first = write_calibration(fit_calibration(report), tmp_path / "1").read_bytes()

    second = write_calibration(fit_calibration(report), tmp_path / "2").read_bytes()

    assert first == second
    assert first.endswith(b"}\n")
    assert b"\r" not in first
    assert list(json.loads(first)["buckets"]) == ["a|adapter", "b|agreed"]


def test_a_report_scoring_every_engine_row_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text(_report(rows_scored="all").model_dump_json(), encoding="utf-8")

    with pytest.raises(ReportRefused, match="scores every engine row"):
        read_report(path)


def test_a_report_run_with_a_calibration_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text(_report(engine_version=f"{SHA}+cal.0123456789ab").model_dump_json(), encoding="utf-8")

    with pytest.raises(ReportRefused, match="run with a calibration"):
        read_report(path)


@pytest.mark.parametrize("text", ["not json", '{"report_version": 1}'])
def test_an_unreadable_report_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "r.json"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ReportRefused, match=r"cannot read r\.json"):
        read_report(path)


def test_a_report_that_is_not_utf8_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_bytes(b"\xff\xfe\x00")

    with pytest.raises(ReportRefused, match=r"cannot read r\.json"):
        read_report(path)


def test_a_missing_report_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ReportRefused, match=r"cannot read r\.json"):
        read_report(tmp_path / "r.json")


def test_a_report_without_per_kind_cells_keeps_the_current_order(tmp_path: Path) -> None:
    # SPEC-05 §4.11 keeps an unmeasured kind in its place.
    (tmp_path / "source_precedence.yaml").write_text(CURRENT, encoding="utf-8")

    path = write_precedence(fit_precedence(_report(), read_precedence(tmp_path)), tmp_path)

    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {
        "source_split": "dev",
        "git_sha": SHA,
        "text": ["adapter", "api", "jsonld", "microdata", "og", "config", "llm"],
        "url": ["adapter", "jsonld", "og"],
    }
    # A refit reads its own output back: the stamp is not a field type.
    assert read_precedence(tmp_path) == {
        "text": ("adapter", "api", "jsonld", "microdata", "og", "config", "llm"),
        "url": ("adapter", "jsonld", "og"),
    }


def test_precedence_moves_a_kind_ahead_only_when_the_data_separates_them(tmp_path: Path) -> None:
    report = _report(
        by_source={
            "url|jsonld": SourceMetrics(precision=0.80, coverage=0.9, n=100),
            "url|og": SourceMetrics(precision=0.99, coverage=0.5, n=100),
            "url|adapter": SourceMetrics(precision=None, coverage=None, n=3),
        }
    )
    current: Orders = {"url": ("adapter", "jsonld", "og")}

    path = write_precedence(fit_precedence(report, current), tmp_path)

    assert yaml.safe_load(path.read_text(encoding="utf-8"))["url"] == ["adapter", "og", "jsonld"]


def test_precedence_needs_a_current_order_to_refit(tmp_path: Path) -> None:
    with pytest.raises(PrecedenceMissing, match=r"no source_precedence\.yaml"):
        read_precedence(tmp_path)


@pytest.mark.parametrize("text", ["- adapter\n", "text: adapter\n", "text: [adapter, 3]\n"])
def test_a_malformed_precedence_file_is_refused(tmp_path: Path, text: str) -> None:
    (tmp_path / "source_precedence.yaml").write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match=r"source_precedence\.yaml"):
        read_precedence(tmp_path)


def test_the_precedence_reader_skips_exactly_the_stamp_the_writer_adds() -> None:
    # `resolve.preference` reads the file and cannot import eval, so the two lists are checked here.
    assert set(Precedence.model_fields) - {"orders"} == STAMP


# From a dev report's pages to the files the engine reads (SPEC-05 §4.11).

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


@pytest.mark.parametrize(("pages", "fitted"), [(MIN_CALIBRATED_N - 1, False), (MIN_CALIBRATED_N, True)])
def test_a_dev_report_fits_files_the_engine_reads(tmp_path: Path, pages: int, fitted: bool) -> None:
    report = build_report(
        [_case(i) for i in range(pages)], "dev", engine_version=f"{SHA}+cal.none", git_sha=SHA, rows="labeled"
    )
    order: tuple[SourceKind, ...] = ("og", "jsonld")
    current = {t.value: order for t in sorted(PRECEDENCE_TYPES)}

    calibration = load_calibration(write_calibration(fit_calibration(report), tmp_path))
    orders = load_precedence(write_precedence(fit_precedence(report, current), tmp_path))

    assert calibration is not None
    confidence, calibrated = calibration.measure(FieldType.TEXT, "structured")
    assert calibrated is fitted
    assert (confidence is not None) is fitted
    assert orders[FieldType.TEXT] == (("jsonld", "og") if fitted else order)
    assert all(orders[t] == order for t in PRECEDENCE_TYPES - {FieldType.TEXT})


def test_the_command_writes_the_fit_under_the_data_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_data_dir", lambda: tmp_path / "data")
    (tmp_path / "report.json").write_text(
        _report(by_bucket={"money|structured": PrecisionMetrics(precision=1.0, n=50)}).model_dump_json(),
        encoding="utf-8",
    )

    main(["eval", "fit-calibration", "--split", "dev", "--report", "report.json"])

    written = tmp_path / "data" / "calibration.json"
    assert json.loads(written.read_bytes())["buckets"] == {"money|structured": {"n": 50, "precision": 0.9808}}
    assert json.loads(capsys.readouterr().out) == {"written": str(written), "git_sha": SHA, "source_split": "dev"}


def test_the_command_exits_non_zero_on_a_refused_report_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_data_dir", lambda: tmp_path / "data")
    argv = ["eval", "fit-calibration", "--split", "dev", "--report", "missing.json"]

    with pytest.raises(SystemExit) as exit_:
        main(argv)

    assert exit_.value.code == 2
    assert "cannot read missing.json" in capsys.readouterr().err
    assert not (tmp_path / "data").exists()
