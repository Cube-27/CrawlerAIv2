"""Fail when a decision ID heads more than one entry of the decisions log (D-0823, `docs/DECISIONS.md` "Where an entry
goes": D-IDs are one sequence across all files).

The log is `docs/DECISIONS.md` and every `docs/decisions/*.md`. An entry starts with a level-3 Markdown heading
`### D-NNNN`; the same ID heading two entries, in one file or in two, is a duplicate. Prints each duplicate with every
`path:line` it heads, and exits 1; exits 0 with one summary line when there is none.

Checks the repository this file is in; it takes no arguments.
"""

import re
import sys
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENTRY = re.compile(r"### (D-\d+)\b")


def log_files(root: Path) -> list[Path]:
    main = root / "docs" / "DECISIONS.md"
    return [*([main] if main.is_file() else []), *sorted((root / "docs" / "decisions").rglob("*.md"))]


def entries(root: Path, file: Path) -> Iterator[tuple[str, str]]:
    """Each entry's ID and `path:line`, in file order."""
    path = file.relative_to(root).as_posix()
    for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
        if heading := ENTRY.match(line):
            yield heading[1], f"{path}:{number}"


def main() -> int:
    places: defaultdict[str, list[str]] = defaultdict(list)
    for file in log_files(REPO):
        for decision, place in entries(REPO, file):
            places[decision].append(place)
    duplicates = {decision: where for decision, where in sorted(places.items()) if len(where) > 1}
    for decision, where in duplicates.items():
        print(f"{decision} heads {len(where)} entries: {', '.join(where)}")
    if duplicates:
        print(f"decision-ids: {len(duplicates)} duplicate IDs; give each later entry the next free ID")
        return 1
    print(f"decision-ids: ok, {len(places)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
