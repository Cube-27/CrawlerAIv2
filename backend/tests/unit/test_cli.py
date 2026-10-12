import json
import shutil
import subprocess
import sysconfig

import pytest

from crawlerai.cli import main


def test_version_flag_prints_package_version_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == "crawlerai 0.1.0\n"


def test_installed_console_script_reports_version() -> None:
    script = shutil.which("crawlerai", path=sysconfig.get_path("scripts"))
    assert script is not None, "the `crawlerai` console script is not installed in this environment"

    result = subprocess.run([script, "--version"], capture_output=True, text=True, check=False)  # noqa: S603

    assert result.returncode == 0
    assert result.stdout == "crawlerai 0.1.0\n"


def test_openapi_prints_the_app_schema_as_sorted_json_with_trailing_newline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["openapi"])

    out = capsys.readouterr().out
    document = json.loads(out)
    assert document["openapi"].startswith("3.")
    assert document["info"]["title"] == "CrawlerAI"
    assert list(document["paths"]) == ["/healthz"]
    assert out == json.dumps(document, indent=2, sort_keys=True) + "\n"


def test_installed_console_script_writes_identical_lf_only_openapi_on_every_run() -> None:
    script = shutil.which("crawlerai", path=sysconfig.get_path("scripts"))
    assert script is not None, "the `crawlerai` console script is not installed in this environment"

    runs = [subprocess.run([script, "openapi"], capture_output=True, check=True).stdout for _ in range(2)]  # noqa: S603

    assert runs[0] == runs[1]
    assert b"\r" not in runs[0]
    assert runs[0].endswith(b"}\n")
