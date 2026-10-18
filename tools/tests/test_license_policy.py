"""Behaviour of `tools/license_policy.py` (CI job 3), run as CI runs it."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

POLICY = Path(__file__).resolve().parents[1] / "license_policy.py"
UNKNOWN = "UNKNOWN"


def python_package(
    name: str, expression: str = UNKNOWN, classifier: str = UNKNOWN, metadata: str = UNKNOWN
) -> dict[str, str]:
    """One row of `pip-licenses --from=all --format=json`."""
    return {
        "Name": name,
        "Version": "1.0.0",
        "License-Expression": expression,
        "License-Classifier": classifier,
        "License-Metadata": metadata,
    }


def node_report(packages: dict[str, str]) -> dict[str, list[dict[str, object]]]:
    """The shape of `pnpm licenses list --json`: packages grouped by their declared license."""
    report: dict[str, list[dict[str, object]]] = {}
    for name, license_ in packages.items():
        report.setdefault(license_, []).append({"name": name, "versions": ["1.0.0"], "license": license_})
    return report


def run_policy(
    tmp_path: Path,
    python: list[dict[str, str]] | None = None,
    node: dict[str, list[dict[str, object]]] | None = None,
) -> subprocess.CompletedProcess[str]:
    python_path = tmp_path / "python-licenses.json"
    node_path = tmp_path / "node-licenses.json"
    python_path.write_text(json.dumps(python or []), encoding="utf-8")
    node_path.write_text(json.dumps(node or {}), encoding="utf-8")
    return subprocess.run(  # noqa: S603
        [sys.executable, str(POLICY), "--python", str(python_path), "--node", str(node_path)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("expression", "denied"),
    [
        ("agpl-3.0-or-later", "AGPL-3.0-or-later"),
        ("CC-BY-NC-SA-4.0", "CC-BY-NC-SA-4.0"),
        ("GPL-2.0+", "GPL-2.0"),
        ("GPL-2.0-only WITH Classpath-exception-2.0", "GPL-2.0-only"),
        ("Apache-2.0 WITH Commons-Clause", "Commons-Clause"),
        ("(MIT OR Apache-2.0) AND AGPL-3.0-or-later", "AGPL-3.0-or-later"),
    ],
)
def test_denied_expression_fails_and_names_the_license(tmp_path: Path, expression: str, denied: str) -> None:
    result = run_policy(tmp_path, python=[python_package("pkg-a", expression=expression)])

    assert result.returncode == 1
    assert result.stderr == f"denied license: python pkg-a 1.0.0: {denied} (declared {expression!r})\n"


def test_clean_reports_pass_and_print_the_count(tmp_path: Path) -> None:
    python = [python_package("pkg-a", expression="MIT"), python_package("pkg-b", classifier="BSD License")]
    node = node_report({"pkg-c": "ISC", "pkg-d": "Unknown"})

    result = run_policy(tmp_path, python=python, node=node)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "licenses ok: 2 python and 2 node packages checked\n"
