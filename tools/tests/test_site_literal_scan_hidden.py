"""Behaviour of `tools/site_literal_scan.py --hidden-hosts-from-env` (SPEC-00 §4.6, §4.7, INV-04), run as the
protected job runs it.

The host lists here are synthetic names under the reserved `.test` TLD. The log of the protected job is public, so
the property every test checks is that no hidden host reaches the output.
"""

import os
import subprocess
import sys
from pathlib import Path

SCAN = Path(__file__).resolve().parents[1] / "site_literal_scan.py"
VAR = "SCAN_TEST_HIDDEN_HOSTS"


def make_repo(root: Path, files: dict[str, str | bytes]) -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)  # noqa: S603, S607
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)  # noqa: S603, S607
    return root


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


def test_match_prints_path_and_line_only(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"scratch.txt": "one\nfetched from shop.hidden.test today\n"})

    result = run_hidden(repo, "shop.hidden.test")

    assert result.returncode == 1
    assert result.stdout.splitlines() == ["scratch.txt:2"]
    assert result.stderr == "hidden-hosts: fail, 1 match(es)\n"
    assert_no_host_in(result, "shop.hidden.test", "hidden.test")


def test_exempt_paths_docs_and_allowlisted_names_are_scanned(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {
            "docs/notes.md": "https://shop.hidden.test/p\n",
            ".github/workflows/x.yml": "url: https://shop.hidden.test/\n",
            "backend/src/crawlerai/adapters/a.py": 'H = "shop.hidden.test"\n',
            "backend/uv.lock": "shop.hidden.test\n",
            "LICENSE": "x\nshop.hidden.test\n",
        },
    )

    result = run_hidden(repo, "shop.hidden.test")

    assert result.returncode == 1
    assert sorted(result.stdout.splitlines()) == [
        ".github/workflows/x.yml:1",
        "LICENSE:2",
        "backend/src/crawlerai/adapters/a.py:1",
        "backend/uv.lock:1",
        "docs/notes.md:1",
    ]


def test_code_outside_strings_is_scanned(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"a.py": "x = 1\nshop.hidden.test(1)\n"})

    result = run_hidden(repo, "shop.hidden.test")

    assert result.stdout.splitlines() == ["a.py:2"]


def test_subdomains_and_case_variants_match_but_longer_labels_do_not(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {
            "a.txt": (
                "https://WWW.Retailer.Test/x\n"
                "cdn.retailer.test\n"
                "myretailer.test\n"
                "retailer.testing\n"
                "other-retailer.test\n"
                "line\\nretailer.test\n"
            )
        },
    )

    result = run_hidden(repo, "retailer.test")

    assert result.stdout.splitlines() == ["a.txt:1", "a.txt:2", "a.txt:6"]


def test_host_list_is_split_on_whitespace_and_commas_and_normalised(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"a.txt": "one.hidden.test\ntwo.hidden.test\nthree.hidden.test\nnone\n"})

    result = run_hidden(repo, " One.Hidden.Test.,\n .two.hidden.test\tthree.hidden.test\n")

    assert result.stdout.splitlines() == ["a.txt:1", "a.txt:2", "a.txt:3"]


def test_one_line_is_reported_once(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"a.txt": "a.hidden.test and b.hidden.test and a.hidden.test\n"})

    result = run_hidden(repo, "a.hidden.test b.hidden.test")

    assert result.stdout.splitlines() == ["a.txt:1"]


def test_path_naming_a_hidden_host_is_reported_with_the_host_withheld(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"captures/shop.hidden.test/page.html": "<p>nothing</p>\n"})

    result = run_hidden(repo, "shop.hidden.test")

    assert result.returncode == 1
    assert result.stdout.splitlines() == ["captures/[hidden]/page.html:0"]
    assert_no_host_in(result, "shop.hidden.test", "hidden.test")


def test_binary_files_are_scanned(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"blob.bin": b"\x00\x01\nshop.hidden.test\x00"})

    result = run_hidden(repo, "shop.hidden.test")

    assert result.stdout.splitlines() == ["blob.bin:2"]


def test_untracked_files_are_not_scanned(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"a.txt": "clean\n"})
    (repo / "untracked.txt").write_text("shop.hidden.test\n", encoding="utf-8")

    result = run_hidden(repo, "shop.hidden.test")

    assert result.returncode == 0


def test_clean_repo_passes_with_one_line(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"a.txt": "https://shop.example.com/\n", "b.txt": "none\n"})

    result = run_hidden(repo, "shop.hidden.test")

    assert result.returncode == 0
    assert result.stdout == "hidden-hosts: pass, 2 files scanned\n"
    assert result.stderr == ""


def test_unset_or_empty_host_list_passes_and_says_so(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"a.txt": "shop.hidden.test\n"})

    for hosts in (None, "", " ,\n "):
        result = run_hidden(repo, hosts)

        assert result.returncode == 0
        assert result.stdout == "hidden-hosts: pass, no host list configured\n"


def test_modes_are_mutually_exclusive_and_one_is_required(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"a.txt": "none\n"})

    both = subprocess.run(  # noqa: S603
        [sys.executable, str(SCAN), "--public", "--hidden-hosts-from-env", VAR, "--root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )
    neither = subprocess.run(  # noqa: S603
        [sys.executable, str(SCAN), "--root", str(repo)], capture_output=True, text=True, check=False
    )

    assert both.returncode == 2
    assert neither.returncode == 2
