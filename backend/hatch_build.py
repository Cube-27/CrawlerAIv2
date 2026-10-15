"""Wheel build hook: writes `VERSION` and puts it, with the data files the manifest lists, inside the package.

An installed wheel has no backend source tree, so `crawlerai.core.engine_version.engine_dir` reads `VERSION` and
`data/` from `crawlerai/_engine/` instead (SPEC-01 §4.7). Only the files `data/manifest.json` lists, its dev-fitted
files and the manifest itself go in (C4, INV-05); a fetched file that `crawlerai data fetch` has not downloaded is left
out, and the engine then reports it missing. An editable install runs from the source tree and gets nothing.
"""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

PACKAGED = "crawlerai/_engine"
SHA_VARIABLE = "CRAWLERAI_GIT_SHA"
# A git object name, as `crawlerai.core.engine_version` reads it: 7 to 40 hex digits (SHA-1) or 64 (SHA-256).
_GIT_SHA = re.compile(r"[0-9a-f]{7,40}|[0-9a-f]{64}")
# The dev-fitted files under data/ that carry a `source_split: dev` stamp instead of a manifest entry (D-0444): the
# precedence and calibration (SPEC-05) and the drift margins (SPEC-08 §4.9).
_DEV_FITTED = ("source_precedence.yaml", "calibration.json", "drift_margins.json")


def git_sha(root: Path) -> str | None:
    """The commit being built: `CRAWLERAI_GIT_SHA` (a build without a checkout, such as the image), else `git
    rev-parse HEAD` in `root`; None when neither gives one."""
    sha = os.environ.get(SHA_VARIABLE, "").strip()
    if not sha:
        try:
            done = subprocess.run(  # noqa: S603 - fixed arguments, no shell
                ["git", "-C", str(root), "rev-parse", "HEAD"],  # noqa: S607 - git from PATH, as any build uses it
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        sha = done.stdout.strip() if done.returncode == 0 else ""
    if not sha:
        return None
    if not _GIT_SHA.fullmatch(sha):
        raise ValueError(f"{SHA_VARIABLE} or git gave {sha!r}, not a git SHA")
    return sha


def data_files(data: Path) -> list[str]:
    """The paths under `data` that go in the wheel: the manifest, each listed file present, and the dev-fitted
    files present."""
    entries = json.loads((data / "manifest.json").read_text(encoding="utf-8"))["entries"]
    listed = [entry["path"] for entry in entries] + list(_DEV_FITTED)
    return ["manifest.json"] + [path for path in listed if (data / path).is_file()]


class EngineFilesHook(BuildHookInterface):  # type: ignore[type-arg]
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel" or version == "editable":
            return
        root = Path(self.root)
        include = build_data["force_include"]
        sha = git_sha(root)
        # Without a commit to name, the wheel has no VERSION and its engine version says `unknown`.
        if sha is not None:
            (root / "VERSION").write_text(f"{sha}\n", encoding="ascii", newline="\n")
            include[str(root / "VERSION")] = f"{PACKAGED}/VERSION"
        for path in data_files(root / "data"):
            include[str(root / "data" / path)] = f"{PACKAGED}/data/{path}"
