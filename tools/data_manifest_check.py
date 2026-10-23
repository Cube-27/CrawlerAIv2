"""Fail when `backend/data/` holds a file that the manifest does not pin (C4).

Vocabularies come from versioned external data. Each file under `backend/data/` must be listed in
`backend/data/manifest.json` with its source URL, version, sha256, license and justification, and its bytes must
match the pinned hash. An entry marked `"fetched": true` is downloaded by `crawlerai data fetch` and not committed:
its file may be absent, and when present it must match its hash. Prints one line per problem and
exits 1, or prints one summary line and exits 0.

Three files are fitted on dev rather than fetched: `source_precedence.yaml`, `calibration.json` and
`drift_margins.json`. They are frozen as fitted on 2026-10-18 and not listed in the manifest; each must instead
carry the stamp `source_split: dev` (the split they were fitted on).
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath

DATA_DIR = PurePosixPath("backend/data")
MANIFEST = DATA_DIR / "manifest.json"
REQUIRED_FIELDS = ("path", "url", "version", "sha256", "license", "justification")
# YAML 1.2.2 §8.2.2 (block mapping) and §7.3 (plain, single- and double-quoted scalars): the key `source_split` at
# indentation 0, so a key of the document itself, with the value `dev`, and an optional trailing comment.
_YAML_DEV_STAMP = re.compile(r"""^source_split:[ \t]+(dev|'dev'|"dev")[ \t]*(#.*)?$""", re.MULTILINE)


def json_dev_stamp(text: str) -> bool:
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(document, dict) and document.get("source_split") == "dev"


def yaml_dev_stamp(text: str) -> bool:
    return _YAML_DEV_STAMP.search(text) is not None


# The dev-fitted files (top level of the data directory), each with how its stamp is read.
DEV_FITTED = {
    "source_precedence.yaml": yaml_dev_stamp,
    "calibration.json": json_dev_stamp,
    "drift_margins.json": json_dev_stamp,
}


def valid_entry_path(path: str) -> bool:
    pure = PurePosixPath(path)
    inside = not pure.is_absolute() and ".." not in pure.parts and "\\" not in path
    return inside and pure != PurePosixPath("manifest.json")


def read_entries(manifest_path: Path) -> list[object] | str:
    """The manifest's entries, or the one problem that stops them being read."""
    if not manifest_path.is_file():
        return f"{MANIFEST}: missing"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return f"{MANIFEST}: not valid JSON ({error})"
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        return f"{MANIFEST}: needs an 'entries' list"
    return entries


def field_problems(index: int, item: dict[str, object], missing: list[str]) -> list[str]:
    """The problems with one entry's fields: each required field it lacks, and a `fetched` that is not a boolean."""
    problems = [f"{MANIFEST}: entry {index} has no '{field}'" for field in missing]
    if not isinstance(item.get("fetched", False), bool):
        problems.append(f"{MANIFEST}: entry {index} has a 'fetched' that is not true or false")
    return problems


def path_problem(index: int, path: str, claimed: set[str]) -> str | None:
    """Why an entry's path cannot be claimed: it is invalid, or an earlier entry already claims it."""
    if not valid_entry_path(path):
        return f"{MANIFEST}: entry {index} has an invalid path {path!r}"
    if path in claimed:
        return f"{MANIFEST}: entry {index} repeats path {path!r}"
    if path in DEV_FITTED:
        return f"{MANIFEST}: entry {index} pins {path!r}, a dev-fitted file checked by its stamp instead"
    return None


def check_entries(entries: list[object]) -> tuple[list[str], set[str], dict[str, str], set[str]]:
    """Return the problems, the claimed paths, the sha256 of each complete entry by path, and the fetched paths.

    Paths of entries that are incomplete are still claimed, so their file is not also reported as unlisted.
    """
    problems: list[str] = []
    claimed: set[str] = set()
    pinned: dict[str, str] = {}
    fetched: set[str] = set()
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            problems.append(f"{MANIFEST}: entry {index} is not an object")
            continue
        missing = [field for field in REQUIRED_FIELDS if not str(item.get(field) or "").strip()]
        problems.extend(field_problems(index, item, missing))
        if "path" in missing:
            continue
        path = str(item["path"])
        if problem := path_problem(index, path, claimed):
            problems.append(problem)
            continue
        claimed.add(path)
        if not missing:
            pinned[path] = str(item["sha256"]).lower()
        if item.get("fetched") is True:
            fetched.add(path)
    return problems, claimed, pinned, fetched


def stamp_problems(data_dir: Path, present: set[str]) -> list[str]:
    """One problem for each dev-fitted file present without the stamp `source_split: dev`."""
    return [
        f"{DATA_DIR / path}: a dev-fitted file needs the stamp 'source_split: dev'"
        for path in sorted(present & DEV_FITTED.keys())
        if not DEV_FITTED[path]((data_dir / path).read_text(encoding="utf-8"))
    ]


def check(root: Path) -> tuple[list[str], int]:
    """Return the problems found and the number of pinned files."""
    manifest_path = root / MANIFEST
    entries = read_entries(manifest_path)
    if isinstance(entries, str):
        return [entries], 0
    problems, claimed, pinned, fetched = check_entries(entries)

    data_dir = root / DATA_DIR
    files = (file for file in data_dir.rglob("*") if file.is_file() and file != manifest_path)
    present = {file.relative_to(data_dir).as_posix() for file in files}
    problems.extend(stamp_problems(data_dir, present))
    for path in sorted(present - claimed - DEV_FITTED.keys()):
        problems.append(f"{DATA_DIR / path}: not listed in {MANIFEST}")
    for path, sha256 in sorted(pinned.items()):
        if path in present:
            with (data_dir / path).open("rb") as file:
                if hashlib.file_digest(file, "sha256").hexdigest() != sha256:
                    problems.append(f"{DATA_DIR / path}: sha256 does not match the manifest")
        elif path not in fetched:
            problems.append(f"{DATA_DIR / path}: listed in the manifest but missing")
    return problems, len(pinned)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="repository root")
    args = parser.parse_args(argv)

    problems, pinned = check(args.root)
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(f"data-manifest: ok, {pinned} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
