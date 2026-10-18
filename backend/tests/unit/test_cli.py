import json
from pathlib import Path

import pytest

from crawlerai import cli
from crawlerai.cli import main
from crawlerai.core.data import DataReport


def test_openapi_prints_the_app_schema_as_sorted_json_with_trailing_newline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["openapi"])

    out = capsys.readouterr().out
    document = json.loads(out)
    assert document["openapi"].startswith("3.")
    assert document["info"]["title"] == "CrawlerAI"
    # The document includes the eval routes, which `frontend/openapi.json` is generated with.
    assert {"/healthz", "/v1/scrape", "/v1/eval/pages"} <= set(document["paths"])
    assert out == json.dumps(document, indent=2, sort_keys=True) + "\n"


def test_data_fetch_reports_each_fetched_entry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(cli, "_data_dir", lambda: tmp_path)

    def fetch_data(directory: Path) -> DataReport:
        calls.append(directory)
        return DataReport(written=["present schemaorg/vocabulary.jsonld", "fetched publicsuffix/list.dat"], refused=[])

    monkeypatch.setattr(cli, "fetch_data", fetch_data)

    main(["data", "fetch"])

    assert calls == [tmp_path]
    assert capsys.readouterr().out == "present schemaorg/vocabulary.jsonld\nfetched publicsuffix/list.dat\n"


def test_data_fetch_reports_every_entry_then_exits_2_on_a_refused_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "_data_dir", lambda: tmp_path)
    report = DataReport(
        written=["fetched schemaorg/vocabulary.jsonld"],
        refused=["publicsuffix/list.dat: sha256 0 does not match the manifest", "other.txt: download failed: x"],
    )
    monkeypatch.setattr(cli, "fetch_data", lambda _directory: report)

    with pytest.raises(SystemExit) as exit_info:
        main(["data", "fetch"])

    assert exit_info.value.code == 2
    assert capsys.readouterr() == (
        "fetched schemaorg/vocabulary.jsonld\n",
        "crawlerai data fetch: publicsuffix/list.dat: sha256 0 does not match the manifest\n"
        "crawlerai data fetch: other.txt: download failed: x\n",
    )
