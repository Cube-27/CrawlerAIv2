"""Behaviour of `tools/decision_ids.py`: a decision ID heads one entry across every Markdown file under
`openspec/`."""

import shutil
import subprocess
import sys
from pathlib import Path

from scan_repo import make_repo

CHECK = Path(__file__).resolve().parents[1] / "decision_ids.py"


def run_check(root: Path, files: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run a copy of the check placed in `root`'s tools/, so it checks the log written under `root`."""
    make_repo(root, dict(files))
    check = root / "tools" / CHECK.name
    check.parent.mkdir(exist_ok=True)
    shutil.copyfile(CHECK, check)
    return subprocess.run([sys.executable, str(check)], capture_output=True, text=True, check=False)  # noqa: S603


def entry(decision: str) -> str:
    return f"### {decision} — a title\n\n- **Status:** decided\n\n"


def test_distinct_ids_across_the_log_pass(tmp_path: Path) -> None:
    result = run_check(
        tmp_path,
        {
            "openspec/decisions/log.md": "# Decisions\n\n### D-NNNN — <title>\n\n" + entry("D-0001") + entry("D-0002"),
            "openspec/changes/add-x/design.md": entry("D-0003"),
            "docs/decisions/SPEC-02.md": "No entries yet.\n",
        },
    )

    assert (result.returncode, result.stdout) == (0, "decision-ids: ok, 3 entries\n")


def test_an_id_in_two_files_fails_with_every_place(tmp_path: Path) -> None:
    result = run_check(
        tmp_path,
        {
            "openspec/decisions/log.md": entry("D-0001") + entry("D-0007"),
            "openspec/changes/add-x/design.md": entry("D-0007"),
            "openspec/changes/archive/2026-01-01-spec-03-y/decisions.md": entry("D-0002") + entry("D-0007"),
        },
    )

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "D-0007 heads 3 entries: openspec/changes/add-x/design.md:1,"
        " openspec/changes/archive/2026-01-01-spec-03-y/decisions.md:5, openspec/decisions/log.md:5",
        "decision-ids: 1 duplicate IDs; give each later entry the next free ID",
    ]


def test_an_id_twice_in_one_file_fails(tmp_path: Path) -> None:
    result = run_check(tmp_path, {"openspec/decisions/log.md": entry("D-0010") + entry("D-0010")})

    assert result.returncode == 1
    assert result.stdout.splitlines()[0] == (
        "D-0010 heads 2 entries: openspec/decisions/log.md:1, openspec/decisions/log.md:5"
    )


def test_mentions_and_other_heading_levels_are_not_entries(tmp_path: Path) -> None:
    text = entry("D-0001") + "See D-0001 and `### D-0001`.\n#### D-0001 — a sub-heading\n## D-0001\n"

    result = run_check(tmp_path, {"openspec/decisions/log.md": text, "docs/SPEC-01.md": entry("D-0001")})

    assert (result.returncode, result.stdout) == (0, "decision-ids: ok, 1 entries\n")
