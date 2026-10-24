"""Build hook: writes `VERSION` and puts it, with the data files the manifest lists, inside the wheel's package.

An installed wheel has no backend source tree, so `snowcrawl.core.engine_version.engine_dir` reads `VERSION` and
`data/` from `snowcrawl/_engine/` instead. Only the files `data/manifest.json` lists, its
dev-fitted files and the manifest itself go in (C4); a fetched file that `snowcrawl data fetch` has not
downloaded is left out, and the engine then reports it missing. An editable install runs from the source tree and gets
nothing.

An sdist carries `VERSION` and the same data files at their own paths, so a wheel built from it (`uv build`'s default)
gets them although the unpacked sdist is no checkout and holds none of the ignored files. A build with no commit to
name fails rather than report `unknown`.
"""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

PACKAGED = "snowcrawl/_engine"
SHA_VARIABLE = "SNOWCRAWL_GIT_SHA"
# A git object name, as `snowcrawl.core.engine_version` reads it: 7 to 40 hex digits (SHA-1) or 64 (SHA-256).
_GIT_SHA = re.compile(r"[0-9a-f]{7,40}|[0-9a-f]{64}")
# The dev-fitted files under data/ that carry a `source_split: dev` stamp instead of a manifest entry: the
# precedence and calibration and the drift margins.
_DEV_FITTED = ("source_precedence.yaml", "calibration.json", "drift_margins.json")


def git_sha(root: Path) -> str | None:
    """The commit being built: `SNOWCRAWL_GIT_SHA` (a build without a checkout, such as the image), else the `VERSION`
    of an unpacked sdist (it has `PKG-INFO`), else `git rev-parse HEAD` in `root`; None when none gives one. In a
    checkout, `VERSION` is an earlier build's output, so git names the commit."""
    sha = os.environ.get(SHA_VARIABLE, "").strip()
    if not sha and (root / "PKG-INFO").is_file() and (root / "VERSION").is_file():
        sha = (root / "VERSION").read_text(encoding="ascii").strip()
    if not sha:
        try:
            # Fixed arguments and no shell; git is found on PATH, as any build finds it.
            done = subprocess.run(  # noqa: S603
                ["git", "-C", str(root), "rev-parse", "HEAD"],  # noqa: S607
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
        if self.target_name not in ("wheel", "sdist") or version == "editable":
            return
        root = Path(self.root)
        sha = git_sha(root)
        if sha is None:
            raise RuntimeError(f"no commit to name in VERSION: set {SHA_VARIABLE}, or build from a git checkout")
        (root / "VERSION").write_text(f"{sha}\n", encoding="ascii", newline="\n")
        # The wheel holds them in the package; the sdist at their own paths, for the wheel built from it.
        target = f"{PACKAGED}/" if self.target_name == "wheel" else ""
        include = build_data["force_include"]
        include[str(root / "VERSION")] = f"{target}VERSION"
        for path in data_files(root / "data"):
            include[str(root / "data" / path)] = f"{target}data/{path}"
