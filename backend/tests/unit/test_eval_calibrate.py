"""`crawlerai eval fit-calibration` and `crawlerai eval fit-precedence` (extraction spec): both fit on a golden-set
report and stamp what they write with `source_split: dev`. Synthetic reports only (C9)."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml

from crawlerai.db.models import SourceKind
from crawlerai.eval.calibrate import (
    Orders,
    fit_calibration,
    fit_precedence,
    write_calibration,
    write_precedence,
)
from crawlerai.eval.metrics import EvalCase, PrecisionMetrics, Report, SchemaFields, SourceMetrics, build_report
from crawlerai.resolve.evidence import MIN_CALIBRATED_N, load_calibration
from crawlerai.resolve.preference import PRECEDENCE_TYPES, load_precedence
from crawlerai.schemas.types import FieldSpec, FieldType

SHA = "a" * 40


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


# From a dev report's pages to the files the engine reads (extraction spec).

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
