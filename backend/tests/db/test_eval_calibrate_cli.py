"""`crawlerai eval calibrate` and `crawlerai eval fit-precedence` end to end (SPEC-03 §4.4, INV-02): each reads a dev
run from the dev store by id and writes its file stamped `source_split: dev`. A throwaway main database
(`CRAWLERAI_TEST_DATABASE_URL`), a temporary data directory, a synthetic run (C9)."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import anyio
import pytest
import yaml
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai import cli
from crawlerai.cli import main
from crawlerai.core.ids import uuid7
from crawlerai.db.models import EvalRun
from crawlerai.eval.metrics import PrecisionMetrics, Report
from crawlerai.eval.store import DevEvalStore, EvalRunRow
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

SHA = "b" * 40


@pytest.fixture
async def dev_run(database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[EvalRunRow]:
    report = Report(
        engine_version=f"{SHA}+cal.none",
        git_sha=SHA,
        split="dev",
        n_pages=40,
        by_field_type={},
        by_field={},
        by_bucket={"money|structured": PrecisionMetrics(precision=0.975, n=40)},
        by_config_status={},
        by_category={},
        acquisition={},
        usage={},
    )
    run = EvalRunRow(split="dev", engine_version=report.engine_version, git_sha=SHA, metrics=report.model_dump())
    engine = create_async_engine(database_url)
    await DevEvalStore(engine, FsStore(tmp_path / "objects")).put_run(run)
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + (tmp_path / "objects").as_posix().lstrip("/"))
    monkeypatch.setattr(cli, "_data_dir", lambda: tmp_path / "data")
    yield run
    async with engine.begin() as conn:
        await conn.execute(delete(EvalRun).where(EvalRun.id == run.id))
    await engine.dispose()


async def test_calibrate_writes_the_dev_runs_buckets(
    dev_run: EvalRunRow, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # In a thread: the command runs its own event loop.
    await anyio.to_thread.run_sync(main, ["eval", "calibrate", "--split", "dev", "--run", str(dev_run.id)])

    written = tmp_path / "data" / "calibration.json"
    assert json.loads(written.read_bytes()) == {
        "calibration_version": 1,
        "source_split": "dev",
        "eval_run_id": str(dev_run.id),
        "git_sha": SHA,
        "buckets": {"money|structured": {"n": 40, "precision": 0.975}},
    }
    assert json.loads(capsys.readouterr().out) == {
        "written": str(written),
        "eval_run_id": str(dev_run.id),
        "source_split": "dev",
    }


async def test_fit_precedence_rewrites_the_order_stamped_with_the_dev_run(dev_run: EvalRunRow, tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "source_precedence.yaml").write_text("text: [adapter, jsonld, llm]\n", encoding="utf-8")

    await anyio.to_thread.run_sync(main, ["eval", "fit-precedence", "--split", "dev", "--run", str(dev_run.id)])

    assert yaml.safe_load((tmp_path / "data" / "source_precedence.yaml").read_text(encoding="utf-8")) == {
        "source_split": "dev",
        "eval_run_id": str(dev_run.id),
        "git_sha": SHA,
        "text": ["adapter", "jsonld", "llm"],
    }


async def test_an_unknown_run_exits_non_zero_and_writes_nothing(
    dev_run: EvalRunRow, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unknown = str(uuid7())
    argv = ["eval", "calibrate", "--split", "dev", "--run", unknown]

    with pytest.raises(SystemExit) as exit_:
        await anyio.to_thread.run_sync(main, argv)

    assert exit_.value.code == 2
    assert f"no dev eval run {unknown}" in capsys.readouterr().err
    assert not (tmp_path / "data").exists()
