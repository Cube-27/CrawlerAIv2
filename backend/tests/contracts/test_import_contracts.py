import configparser
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
    shutil.copytree(BACKEND / "src" / "crawlerai", tmp_path / "crawlerai", ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path


def plant(src: Path, files: dict[str, str]) -> None:
    for relative, code in files.items():
        (src / "crawlerai" / relative).write_text(code, encoding="utf-8")


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
    assert result.stdout.count(" BROKEN") == 1
    assert broken_contract in result.stdout.split("Broken contracts", 1)[1]


@pytest.mark.parametrize(
    "files",
    [
        {},
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
    assert " BROKEN" not in result.stdout


@pytest.mark.parametrize(
    ("contract", "exempt"),
    [
        ("normalize-libs", {"crawlerai.normalize"}),
        ("adapters-isolated", {"crawlerai.acquire", "crawlerai.collect", "crawlerai.adapters"}),
    ],
)
def test_forbidden_contract_sources_cover_every_top_level_module(contract: str, exempt: set[str]) -> None:
    config = configparser.ConfigParser()
    config.read(CONFIG, encoding="utf-8")
    sources = set(config[f"importlinter:contract:{contract}"]["source_modules"].split())
    top_level = {
        f"crawlerai.{path.stem}"
        for path in (BACKEND / "src" / "crawlerai").iterdir()
        if (path.is_dir() and (path / "__init__.py").exists()) or (path.suffix == ".py" and path.stem != "__init__")
    }

    assert sources == top_level - exempt
