"""`crawlerai eval capture` and `crawlerai eval import-sites` without a database: the site list, the report, and how
the commands hand their arguments on (SPEC-03 §4.4). Synthetic `.test` URLs only."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from crawlerai import cli
from crawlerai.cli import main
from crawlerai.core.settings import Settings
from crawlerai.db.models import PageKind
from crawlerai.eval.cli import (
    Outcome,
    PageRequest,
    SiteList,
    Skipped,
    parse_site_list,
)

A = "https://a.example.test"
B = "https://b.example.test"


def test_a_site_list_keeps_the_first_pages_of_each_host_and_skips_the_rest() -> None:
    text = "\n".join(
        [
            "# fresh batch",
            f"custom_store commerce_detail {A}/p/1",
            "",
            f"job_board jobs_listing {B}/jobs",
            f"custom_store commerce_detail {A}/p/2",
            f"custom_store commerce_listing {A.upper()}/c/1",  # the same host, whatever its case
            "   # an indented comment",
            f"job_board jobs_detail {B}/jobs/1",
        ]
    )

    assert parse_site_list(text, pages_per_site=2) == SiteList(
        requests=(
            PageRequest(2, f"{A}/p/1", "commerce_detail", "custom_store"),
            PageRequest(4, f"{B}/jobs", "jobs_listing", "job_board"),
            PageRequest(5, f"{A}/p/2", "commerce_detail", "custom_store"),
            PageRequest(8, f"{B}/jobs/1", "jobs_detail", "job_board"),
        ),
        over_limit=(Skipped(6, "pages_per_site"),),
    )


Call = tuple[list[PageRequest], PageKind | None]


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", "postgresql+asyncpg://app:app@127.0.0.1:5432/crawlerai")
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///srv/objects")


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch, settings_env: None) -> list[Call]:
    """Records what the commands ask `run_capture` for, and answers that every page was skipped."""
    calls: list[Call] = []

    async def run(
        settings: Settings, requests: Sequence[PageRequest], page_kind: PageKind | None = None
    ) -> list[Outcome]:
        calls.append((list(requests), page_kind))
        return [Skipped(request.n, "robots") for request in requests]

    monkeypatch.setattr(cli, "run_capture", run)
    return calls


def test_capture_asks_for_each_url_with_the_schema_kind_and_category(
    runs: list[Call], capsys: pytest.CaptureFixture[str]
) -> None:
    main(
        [
            "eval", "capture", "--split", "dev", "--schema", "commerce_detail", "--page-kind", "detail",
            "--category", "platform_store", f"{A}/p/1", f"{B}/p/2",
        ]
    )  # fmt: skip

    assert runs == [
        (
            [
                PageRequest(1, f"{A}/p/1", "commerce_detail", "platform_store"),
                PageRequest(2, f"{B}/p/2", "commerce_detail", "platform_store"),
            ],
            "detail",
        )
    ]
    assert capsys.readouterr().out == '{"n": 1, "skipped": "robots"}\n{"n": 2, "skipped": "robots"}\n'


def test_import_sites_captures_the_kept_pages_and_reports_the_rest(
    runs: list[Call], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sites.txt").write_text(
        f"mixed commerce_detail {A}/p/1\nmixed commerce_detail {A}/p/2\n", encoding="utf-8"
    )

    main(["eval", "import-sites", "--split", "dev", "--file", "sites.txt", "--pages-per-site", "1"])

    assert runs == [([PageRequest(1, f"{A}/p/1", "commerce_detail", "mixed")], None)]
    assert capsys.readouterr().out == '{"n": 1, "skipped": "robots"}\n{"n": 2, "skipped": "pages_per_site"}\n'


# What a database error can carry: the values of the row it refused.
