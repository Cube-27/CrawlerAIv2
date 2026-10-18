"""Behaviour of `tools/site_literal_scan.py --hidden-hosts-from-env` (INV-04), run as the
protected job runs it.

The host lists here are synthetic names under the reserved `.test` TLD. The log of the protected job is public, so
the property every test checks is that no hidden host reaches the output.
"""

import os
import subprocess
import sys
from pathlib import Path

from scan_repo import SCAN, make_repo

VAR = "SCAN_TEST_HIDDEN_HOSTS"


def run_hidden(root: Path, hosts: str | None) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != VAR}
    if hosts is not None:
        env[VAR] = hosts
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCAN), "--hidden-hosts-from-env", VAR, "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def assert_no_host_in(result: subprocess.CompletedProcess[str], *hosts: str) -> None:
    output = (result.stdout + result.stderr).lower()
    for host in hosts:
        assert host not in output


def test_match_prints_path_and_line_only_in_every_kind_of_file(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {
            "scratch.txt": "one\nfetched from shop.hidden.test today\n",
            "docs/notes.md": "https://shop.hidden.test/p\n",
            "backend/uv.lock": "shop.hidden.test\n",
            "a.py": "x = 1\nshop.hidden.test(1)\n",
            "blob.bin": b"\x00\x01\nshop.hidden.test\x00",
        },
    )
    (repo / "untracked.txt").write_text("shop.hidden.test\n", encoding="utf-8")

    result = run_hidden(repo, "shop.hidden.test")

    assert result.returncode == 1
    assert sorted(result.stdout.splitlines()) == [
        "a.py:2",
        "backend/uv.lock:1",
        "blob.bin:2",
        "docs/notes.md:1",
        "scratch.txt:2",
    ]
    assert result.stderr == "hidden-hosts: fail, 5 match(es)\n"
    assert_no_host_in(result, "shop.hidden.test", "hidden.test")


def test_paths_naming_a_hidden_host_are_reported_with_the_host_withheld(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {
            "captures/shop.hidden.test/page.html": "<p>nothing</p>\n",
            "caps/shop.hidden.test_2024.html": "see shop.hidden.test\n",
            "a/MyShop.Hidden.Test-x/page.txt": "shop.hidden.test\n",
        },
    )

    result = run_hidden(repo, "shop.hidden.test")

    assert result.returncode == 1
    assert sorted(result.stdout.splitlines()) == [
        "a/My[hidden]-x/page.txt:1",
        "caps/[hidden]_2024.html:0",
        "caps/[hidden]_2024.html:1",
        "captures/[hidden]/page.html:0",
    ]
    assert_no_host_in(result, "shop.hidden.test", "hidden.test")


def test_clean_repo_passes_and_unset_or_empty_host_list_passes_and_says_so(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"a.txt": "https://shop.example.com/\n", "b.txt": "none\n"})

    clean = run_hidden(repo, "shop.hidden.test")

    assert (clean.returncode, clean.stdout, clean.stderr) == (0, "hidden-hosts: pass, 2 files scanned\n", "")
    for hosts in (None, "", " ,\n "):
        result = run_hidden(repo, hosts)

        assert result.returncode == 0
        assert result.stdout == "hidden-hosts: pass, no host list configured\n"


def test_schema_column_references_and_schema_org_values_do_not_exempt_hidden_hosts(tmp_path: Path) -> None:
    migration = 'op.create_table("shop", sa.Column("test", sa.Text()))\n'
    path = ".".join(["Shop", "test"])
    repo = make_repo(
        tmp_path / "repo",
        {"migrations/0001.py": migration, "a.py": 'FK = "shop.test"\n', "p.json": f'{{"schema_org": "{path}"}}\n'},
    )

    result = run_hidden(repo, "shop.test")

    assert result.returncode == 1
    assert sorted(result.stdout.splitlines()) == ["a.py:1", "p.json:1"]
    assert_no_host_in(result, "shop.test")
