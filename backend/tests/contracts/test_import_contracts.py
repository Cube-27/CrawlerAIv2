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
    env = {**os.environ, "PYTHONPATH": str(src)}
    return subprocess.run(  # noqa: S603
        [script, "--config", str(CONFIG), "--no-cache"],
        capture_output=True,
        text=True,
        check=False,
        cwd=src,
        env=env,
    )


@pytest.fixture
def package_copy(tmp_path: Path) -> Path:
    shutil.copytree(BACKEND / "src" / "crawlerai", tmp_path / "crawlerai", ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path


def plant(src: Path, files: dict[str, str]) -> None:
    for relative, code in files.items():
        (src / "crawlerai" / relative).write_text(code, encoding="utf-8")


def test_contracts_hold_on_the_package(package_copy: Path) -> None:
    result = lint_imports(package_copy)

    assert result.returncode == 0, result.stdout
    assert "Contracts: 4 kept, 0 broken." in result.stdout


@pytest.mark.parametrize(
    ("files", "broken_contract"),
    [
        ({"collect/probe.py": "import babel\n"}, "Only normalizers import normalization libraries"),
        ({"schemas/probe.py": "from price_parser import Price\n"}, "Only normalizers import normalization libraries"),
        (
            {"normalize/alpha.py": "", "normalize/beta.py": "from crawlerai.normalize import alpha\n"},
            "One module per field type",
        ),
        ({"resolve/probe.py": "from crawlerai import adapters\n"}, "Nothing outside adapters imports adapters"),
        ({"core/probe.py": "from crawlerai import db\n"}, "Layering"),
        ({"normalize/probe.py": "from crawlerai import schemas\n"}, "Layering"),
    ],
)
def test_planted_violation_breaks_its_contract(package_copy: Path, files: dict[str, str], broken_contract: str) -> None:
    plant(package_copy, files)

    result = lint_imports(package_copy)

    assert result.returncode == 1
    assert "Contracts: 3 kept, 1 broken." in result.stdout
    assert broken_contract in result.stdout.split("Broken contracts", 1)[1]


@pytest.mark.parametrize(
    "files",
    [
        {"normalize/probe.py": "import babel\nimport dateparser\n"},
        {"acquire/probe.py": "from crawlerai import adapters\n"},
        {"collect/probe.py": "from crawlerai import adapters\n"},
        {"collect/probe.py": "from crawlerai import normalize\n"},
    ],
)
def test_permitted_imports_keep_every_contract(package_copy: Path, files: dict[str, str]) -> None:
    plant(package_copy, files)

    result = lint_imports(package_copy)

    assert result.returncode == 0, result.stdout
    assert "Contracts: 4 kept, 0 broken." in result.stdout
