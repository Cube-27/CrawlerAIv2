"""Behaviour of `tools/theme_only_check.py` (DESIGN.md, Theming and Stack): visual values live only in theme.css, and
UI comes only from @heroui/react."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from scan_repo import make_repo

CHECK = Path(__file__).resolve().parents[1] / "theme_only_check.py"
THEME = "frontend/src/app/theme.css"
ENTRY_CSS = '@import "tailwindcss";\n@import "@heroui/styles";\n:root { --color-x: #123456; }\n'


def run_check(root: Path) -> subprocess.CompletedProcess[str]:
    """Run a copy of the check placed in `root`'s tools/, untracked, so it checks that repository."""
    check = root / "tools" / CHECK.name
    check.parent.mkdir(exist_ok=True)
    shutil.copyfile(CHECK, check)
    return subprocess.run(  # noqa: S603
        [sys.executable, str(check)], capture_output=True, text=True, check=False
    )


def findings_for(tmp_path: Path, files: dict[str, str]) -> list[str]:
    result = run_check(make_repo(tmp_path, {THEME: ENTRY_CSS, **files}))
    return result.stdout.splitlines() if result.returncode == 1 else []


@pytest.mark.parametrize(
    ("line", "rule"),
    [
        ('<path fill="#ff0000" />', "color literal"),
        ('const c = "oklch(0.5 0.1 200)";', "color literal"),
        ('<div className="mx-auto max-w-[1280px]" />', "arbitrary value"),
        ('<div className="hover:text-slate-950" />', "palette color"),
        ("<div style={{ width: 4 }} />", "style prop"),
        ('import { Button } from "react-aria-components";', "ui import"),
        ('const kit = await import("some-ui-kit");', "ui import"),
    ],
)
def test_a_visual_value_or_ui_import_outside_the_theme_layer_fails(tmp_path: Path, line: str, rule: str) -> None:
    found = findings_for(tmp_path, {"frontend/src/screens/X.tsx": f"// header\n{line}\n"})

    assert found == [f"frontend/src/screens/X.tsx:2: {rule}: {line}"]


def test_semantic_tokens_default_scale_and_allowed_imports_pass(tmp_path: Path) -> None:
    source = "\n".join(
        (
            'import { Button, Table } from "@heroui/react";',
            'import { CircleCheck } from "@gravity-ui/icons";',
            'import { useState } from "react";',
            'import { PageHeader } from "../components/PageHeader";',
            'import "./app/theme.css";',
            '<div className="max-w-content h-page-view bg-background text-foreground border-border text-danger" />',
            '<div className="flex gap-6 px-4 sm:w-48 lg:w-1/2 rounded" />',
            'if (typeof state === "object" && "from" in state) {',
        )
    )
    result = run_check(make_repo(tmp_path, {THEME: ENTRY_CSS, "frontend/src/screens/X.tsx": source}))

    assert result.returncode == 0, result.stdout
    assert result.stdout == "theme-only: ok, 1 files\n"


def test_theme_tests_generated_files_and_files_outside_src_are_not_scanned(tmp_path: Path) -> None:
    files = {
        "frontend/src/screens/X.test.tsx": '<div style={{}} className="bg-red-500" />\n',
        "frontend/src/test/setup.ts": 'import "@testing-library/jest-dom/vitest";\n',
        "frontend/src/api/schema.d.ts": 'color: "#ffffff";\n',
        "frontend/vite.config.ts": 'import { defineConfig } from "vite-plus";\n',
        "docs/x.css": "a { color: #000; }\n",
    }

    result = run_check(make_repo(tmp_path, {THEME: ENTRY_CSS, **files}))

    assert result.returncode == 0, result.stdout
    assert result.stdout == "theme-only: ok, 0 files\n"
