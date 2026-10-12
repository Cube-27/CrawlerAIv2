"""Behaviour of `tools/license_policy.py` (SPEC-00 §4.6 job 3, ARCHITECTURE §18), run as CI runs it."""

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
        ("AGPL-3.0-only", "AGPL-3.0-only"),
        ("agpl-3.0-or-later", "AGPL-3.0-or-later"),
        ("GPL-2.0-only", "GPL-2.0-only"),
        ("GPL-3.0", "GPL-3.0"),
        ("SSPL-1.0", "SSPL-1.0"),
        ("CC-BY-NC-SA-4.0", "CC-BY-NC-SA-4.0"),
        ("PolyForm-Noncommercial-1.0.0", "PolyForm-Noncommercial-1.0.0"),
        # `+` is SPDX "or later"; the base identifier is what the deny-list names.
        ("GPL-2.0+", "GPL-2.0"),
        # An exception narrows a license but leaves it copyleft.
        ("GPL-2.0-only WITH Classpath-exception-2.0", "GPL-2.0-only"),
        # Commons Clause is usually attached to a permissive license as a WITH term.
        ("Apache-2.0 WITH Commons-Clause", "Commons-Clause"),
        # AND means every license applies.
        ("MIT AND GPL-3.0-only", "GPL-3.0-only"),
        ("(MIT OR Apache-2.0) AND AGPL-3.0-or-later", "AGPL-3.0-or-later"),
        ("(AGPL-3.0-only OR GPL-3.0-only) AND MIT", "AGPL-3.0-only, GPL-3.0-only"),
    ],
)
def test_denied_expression_fails_and_names_the_license(tmp_path: Path, expression: str, denied: str) -> None:
    result = run_policy(tmp_path, python=[python_package("pkg-a", expression=expression)])

    assert result.returncode == 1
    assert result.stderr == f"denied license: python pkg-a 1.0.0: {denied} (declared {expression!r})\n"


@pytest.mark.parametrize(
    "expression",
    [
        # LGPL contains "GPL" as a substring but is a different identifier (D-0001: allowed).
        "LGPL-2.1-only",
        "LGPL-3.0-or-later",
        "LGPL-2.0+",
        # Another identifier that merely contains a denied one as a substring.
        "CC-BY-NC-4.0-ish",
        "MIT",
        "Apache-2.0 OR BSD-2-Clause",
        # OR means the project may choose the permissive branch.
        "MIT OR GPL-3.0-only",
        "(GPL-2.0-only OR AGPL-3.0-only) OR (MIT AND BSD-3-Clause)",
    ],
)
def test_allowed_expression_passes(tmp_path: Path, expression: str) -> None:
    result = run_policy(tmp_path, python=[python_package("pkg-a", expression=expression)])

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_trove_classifier_for_a_denied_license_fails(tmp_path: Path) -> None:
    classifier = "MIT License; GNU Affero General Public License v3"

    result = run_policy(tmp_path, python=[python_package("pkg-a", classifier=classifier)])

    assert result.returncode == 1
    assert result.stderr == (
        "denied license: python pkg-a 1.0.0: GNU Affero General Public License v3"
        " (declared 'GNU Affero General Public License v3')\n"
    )


@pytest.mark.parametrize(
    "classifier",
    [
        "GNU Lesser General Public License v3 (LGPLv3)",
        "GNU Library or Lesser General Public License (LGPL)",
        "Apache Software License; BSD License",
    ],
)
def test_trove_classifier_for_an_allowed_license_passes(tmp_path: Path, classifier: str) -> None:
    result = run_policy(tmp_path, python=[python_package("pkg-a", classifier=classifier)])

    assert result.returncode == 0, result.stderr


def test_license_expression_takes_precedence_over_classifiers(tmp_path: Path) -> None:
    # PEP 639: License-Expression is authoritative; classifiers are the legacy declaration.
    package = python_package("pkg-a", expression="MIT", classifier="GNU General Public License v3 (GPLv3)")

    result = run_policy(tmp_path, python=[package])

    assert result.returncode == 0, result.stderr


def test_license_metadata_is_used_when_nothing_else_is_declared(tmp_path: Path) -> None:
    result = run_policy(tmp_path, python=[python_package("pkg-a", metadata="GPL-3.0-or-later")])

    assert result.returncode == 1
    assert result.stderr == "denied license: python pkg-a 1.0.0: GPL-3.0-or-later (declared 'GPL-3.0-or-later')\n"


def test_node_package_with_denied_license_fails(tmp_path: Path) -> None:
    node = node_report({"pkg-ok": "MIT", "pkg-lgpl": "LGPL-3.0-only", "pkg-bad": "(MIT AND AGPL-3.0-only)"})

    result = run_policy(tmp_path, node=node)

    assert result.returncode == 1
    assert result.stderr == "denied license: node pkg-bad 1.0.0: AGPL-3.0-only (declared '(MIT AND AGPL-3.0-only)')\n"


def test_every_denied_package_is_reported(tmp_path: Path) -> None:
    python = [python_package("pkg-a", expression="SSPL-1.0"), python_package("pkg-b", expression="MIT")]
    node = node_report({"pkg-c": "GPL-3.0-only"})

    result = run_policy(tmp_path, python=python, node=node)

    assert result.returncode == 1
    assert result.stderr.splitlines() == [
        "denied license: python pkg-a 1.0.0: SSPL-1.0 (declared 'SSPL-1.0')",
        "denied license: node pkg-c 1.0.0: GPL-3.0-only (declared 'GPL-3.0-only')",
    ]


def test_clean_reports_pass_and_print_the_count(tmp_path: Path) -> None:
    python = [python_package("pkg-a", expression="MIT"), python_package("pkg-b", classifier="BSD License")]
    node = node_report({"pkg-c": "ISC", "pkg-d": "Unknown"})

    result = run_policy(tmp_path, python=python, node=node)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "licenses ok: 2 python and 2 node packages checked\n"
