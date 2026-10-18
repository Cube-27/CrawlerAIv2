"""`crawlerai eval capture` and `crawlerai eval import-sites` without a database: the site list, the report, and how
the commands hand their arguments on (SPEC-03 §4.4). Synthetic `.test` URLs only."""

import json
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

import pytest

from crawlerai import cli
from crawlerai.cli import main
from crawlerai.core.settings import Settings
from crawlerai.db.models import CaptureId, EvalPageId, PageKind
from crawlerai.eval.cli import (
    Captured,
    EvalCliError,
    Outcome,
    PageRequest,
    SiteList,
    Skipped,
    parse_site_list,
    report,
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


def test_every_error_in_a_site_list_is_reported_by_line_without_its_content() -> None:
    text = "\n".join(
        [
            f"custom_store commerce_detail {A}/p/1",
            f"shopping commerce_detail {A}/p/2",
            f"custom_store {A}/p/3",
            "custom_store commerce_detail ftp://a.example.test/p/4",
            "custom_store commerce_detail https:///p/5",
            f"custom_store commerce_detail {A}/p/1",
            f"custom_store commerce_detail {A}/p/6 extra",
        ]
    )

    with pytest.raises(EvalCliError) as error:
        parse_site_list(text, pages_per_site=3)

    assert str(error.value).splitlines() == [
        "the site list is invalid:",
        "line 2: the category is not one of api_backed, custom_store, job_board, mixed, platform_store",
        "line 3: expected `<category> <schema> <url>`",
        "line 4: not an http or https URL with a host",
        "line 5: not an http or https URL with a host",
        "line 6: the URL is listed twice",
        "line 7: expected `<category> <schema> <url>`",
    ]
    assert "example.test" not in str(error.value)


def _request(n: int, url: str) -> PageRequest:
    return PageRequest(n, url, "commerce_detail", "mixed")


def test_the_report_has_one_json_line_per_page_in_input_order() -> None:
    capture_id, page_id = "01a132f6-a42f-76c9-92f2-fb6ad3b2c878", "01a132f6-a433-7200-bf3f-3c79942f04a6"
    outcomes: list[Outcome] = [
        Skipped(3, "pages_per_site"),
        Captured(1, CaptureId(UUID(capture_id)), EvalPageId(UUID(page_id)), 403, "blocked", None),
        Skipped(2, "robots"),
    ]

    lines = [json.loads(line) for line in report(outcomes).splitlines()]

    assert lines == [
        {
            "n": 1,
            "capture_id": capture_id,
            "page_id": page_id,
            "status_code": 403,
            "block_class": "blocked",
            "error": None,
        },
        {"n": 2, "skipped": "robots"},
        {"n": 3, "skipped": "pages_per_site"},
    ]


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


def test_capture_refuses_a_url_it_cannot_fetch_before_running(
    runs: list[Call], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "eval", "capture", "--split", "dev", "--schema", "commerce_detail", "--page-kind", "detail",
                "--category", "mixed", f"{A}/p/1", "a.example.test/p/2",
            ]
        )  # fmt: skip

    assert exit_info.value.code == 2
    assert runs == []
    assert capsys.readouterr().err == "crawlerai eval: not an http or https URL with a host: URL 2\n"


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


@pytest.mark.parametrize("pages", ["0", "three"])
def test_import_sites_needs_a_positive_page_count(runs: list[Call], tmp_path: Path, pages: str) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["eval", "import-sites", "--split", "dev", "--file", str(tmp_path / "s.txt"), "--pages-per-site", pages])

    assert exit_info.value.code == 2
    assert runs == []


@pytest.mark.parametrize("relative", [True, False])
def test_import_sites_reads_a_site_list_only_from_under_the_working_directory(
    runs: list[Call],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    relative: bool,
) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    (tmp_path / "sites.txt").write_text(f"mixed commerce_detail {A}/p/1\n", encoding="utf-8")
    monkeypatch.chdir(workdir)
    outside = "../sites.txt" if relative else str(tmp_path / "sites.txt")

    with pytest.raises(SystemExit) as exit_info:
        main(["eval", "import-sites", "--split", "dev", "--pages-per-site", "1", "--file", outside])

    assert exit_info.value.code == 2
    assert runs == []
    assert "--file must be under the working directory" in capsys.readouterr().err


# What a database error can carry: the values of the row it refused.
_LEAKY = f"duplicate key value violates unique constraint\nDETAIL: Key (url)=({A}/p/1) already exists."


def _capture_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run(*args: object) -> list[Outcome]:
        raise RuntimeError(_LEAKY)

    monkeypatch.setattr(cli, "run_capture", run)
    main(
        [
            "eval", "capture", "--split", "dev", "--schema", "commerce_detail", "--page-kind", "detail",
            "--category", "mixed", f"{A}/p/1",
        ]
    )  # fmt: skip


def test_an_unexpected_failure_on_the_dev_split_keeps_its_details(
    monkeypatch: pytest.MonkeyPatch, settings_env: None
) -> None:
    with pytest.raises(RuntimeError, match="DETAIL: Key"):
        _capture_raising(monkeypatch)


@pytest.mark.parametrize("command", ["promote", "rotate-hidden"])
def test_there_is_no_command_moving_pages_between_splits(command: str) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["eval", command])

    assert exit_info.value.code == 2


def test_capture_takes_only_the_dev_split(runs: list[Call]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "eval", "capture", "--split", "hidden", "--schema", "commerce_detail", "--page-kind", "detail",
                "--category", "mixed", f"{A}/p/1",
            ]
        )  # fmt: skip

    assert exit_info.value.code == 2
    assert runs == []
