import os
import shutil
import subprocess
import sysconfig
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
CONFIG = BACKEND / ".importlinter"


def lint_imports(src: Path) -> subprocess.CompletedProcess[str]:
    script = shutil.which("lint-imports", path=sysconfig.get_path("scripts"))
    assert script is not None, "the `lint-imports` console script is not installed in this environment"
    return subprocess.run(  # noqa: S603
        [script, "--config", str(CONFIG), "--no-cache"],
        capture_output=True,
        text=True,
        check=False,
        cwd=src,
        env={**os.environ, "PYTHONPATH": str(src)},
    )


@pytest.fixture
def package_copy(tmp_path: Path) -> Path:
    shutil.copytree(BACKEND / "src" / "snowcrawl", tmp_path / "snowcrawl", ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path


def plant(src: Path, files: dict[str, str]) -> None:
    for relative, code in files.items():
        (src / "snowcrawl" / relative).write_text(code, encoding="utf-8")


@pytest.mark.parametrize(
    ("files", "broken_contract"),
    [
        ({"collect/probe.py": "import babel\n"}, "Only normalizers import normalization libraries"),
        ({"normalize/url.py": "from snowcrawl.normalize import text\n"}, "One module per field type"),
        (
            {"normalize/dispatch.py": "", "normalize/money.py": "from snowcrawl.normalize import dispatch\n"},
            "Normalizer internals",
        ),
        ({"resolve/probe.py": "from snowcrawl import adapters\n"}, "Nothing outside adapters imports adapters"),
        ({"core/probe.py": "from snowcrawl import db\n"}, "Layering"),
    ],
)
def test_planted_violation_breaks_its_contract(package_copy: Path, files: dict[str, str], broken_contract: str) -> None:
    plant(package_copy, files)

    result = lint_imports(package_copy)

    assert result.returncode == 1
    assert result.stdout.count(" BROKEN") == 1
    assert broken_contract in result.stdout.split("Broken contracts", 1)[1]


@pytest.mark.parametrize(
    "files",
    [
        {},
        {"normalize/probe.py": "import babel\nimport dateparser\n"},
        {"collect/probe.py": "from snowcrawl import adapters\n"},
        {"api/probe.py": "from snowcrawl import services\n", "services/probe.py": "from snowcrawl import schemas\n"},
    ],
)
def test_permitted_imports_keep_every_contract(package_copy: Path, files: dict[str, str]) -> None:
    plant(package_copy, files)

    result = lint_imports(package_copy)

    assert result.returncode == 0, result.stdout
    assert " BROKEN" not in result.stdout
