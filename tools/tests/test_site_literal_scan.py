"""Behaviour of `tools/site_literal_scan.py --public` (SPEC-00 §4.7), run as CI runs it.

Every host here is reserved by RFC 2606 or RFC 6761. Detection tests pass an explicit allowlist so that those
reserved names are not exempted.
"""

import subprocess
import sys
from pathlib import Path

import pytest

SCAN = Path(__file__).resolve().parents[1] / "site_literal_scan.py"


def make_repo(root: Path, files: dict[str, str | bytes]) -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)  # noqa: S603, S607
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)  # noqa: S603, S607
    return root


def write_allowlist(path: Path, lines: list[str]) -> Path:
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


def run_scan(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCAN), "--public", "--root", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def empty_allowlist(tmp_path: Path) -> Path:
    return write_allowlist(tmp_path / "allowlist.txt", [])


def test_hostname_in_generic_code_fails_with_path_line_and_host(tmp_path: Path, empty_allowlist: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {"backend/src/crawlerai/collect/hosts.py": 'X = 1\nHOST = "shop.example.com"\n'},
    )

    result = run_scan(repo, "--allowlist", str(empty_allowlist))

    assert result.returncode == 1
    assert result.stdout.splitlines() == ["backend/src/crawlerai/collect/hosts.py:2: shop.example.com"]


def test_url_host_outside_the_tld_list_fails(tmp_path: Path, empty_allowlist: Path) -> None:
    repo = make_repo(
        tmp_path / "repo", {"backend/src/crawlerai/acquire/fetch.py": 'U = "https://shop.retailer.test/p?q=1"\n'}
    )

    result = run_scan(repo, "--allowlist", str(empty_allowlist))

    assert result.returncode == 1
    assert result.stdout.splitlines() == ["backend/src/crawlerai/acquire/fetch.py:1: shop.retailer.test"]


def test_hosts_are_reported_lowercase_once_per_line(tmp_path: Path, empty_allowlist: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"a.txt": "see https://SHOP.EXAMPLE.COM/x and shop.example.com\n"})

    result = run_scan(repo, "--allowlist", str(empty_allowlist))

    assert result.stdout.splitlines() == ["a.txt:1: shop.example.com"]


def test_tests_are_not_exempt(tmp_path: Path, empty_allowlist: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"backend/tests/unit/test_x.py": 'URL = "https://jobs.example.net/1"\n'})

    result = run_scan(repo, "--allowlist", str(empty_allowlist))

    assert result.returncode == 1
    assert result.stdout.splitlines() == ["backend/tests/unit/test_x.py:1: jobs.example.net"]


@pytest.mark.parametrize(
    "path",
    [
        "backend/src/crawlerai/adapters/platform.py",
        "docs/notes.md",
        "backend/uv.lock",
        "frontend/pnpm-lock.yaml",
        "frontend/package.json",
        "backend/pyproject.toml",
        ".github/workflows/ci.yml",
        "LICENSE",
        "NOTICE",
        "backend/data/manifest.json",
    ],
)
def test_exempt_paths_pass(tmp_path: Path, empty_allowlist: Path, path: str) -> None:
    repo = make_repo(tmp_path / "repo", {path: "https://shop.example.com/\n"})

    result = run_scan(repo, "--allowlist", str(empty_allowlist))

    assert result.returncode == 0, result.stdout


def test_path_exemptions_do_not_leak_to_similar_paths(tmp_path: Path, empty_allowlist: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {
            "backend/src/crawlerai/adapters_extra/x.py": 'H = "shop.example.com"\n',
            "backend/docs/x.md": "shop.example.com\n",
        },
    )

    result = run_scan(repo, "--allowlist", str(empty_allowlist))

    assert result.returncode == 1
    assert sorted(result.stdout.splitlines()) == [
        "backend/docs/x.md:1: shop.example.com",
        "backend/src/crawlerai/adapters_extra/x.py:1: shop.example.com",
    ]


def test_default_allowlist_exempts_reserved_names(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {
            "backend/tests/unit/test_x.py": (
                'A = "https://shop.example.com/p"\n'
                'B = "www.example.org"\n'
                'C = "https://jobs.retailer.test/1"\n'
                'D = "http://localhost:8000/healthz"\n'
                'E = "https://x.invalid/"\n'
                'F = "https://shop.example/"\n'
            )
        },
    )

    result = run_scan(repo)

    assert result.returncode == 0, result.stdout


def test_dotted_entry_covers_the_name_and_its_subdomains_only(tmp_path: Path) -> None:
    allowlist = write_allowlist(tmp_path / "allowlist.txt", [".shop.example  # reserved test name"])
    repo = make_repo(
        tmp_path / "repo",
        {"a.txt": "https://shop.example/\nhttps://a.shop.example/\nhttps://othershop.example/\n"},
    )

    result = run_scan(repo, "--allowlist", str(allowlist))

    assert result.stdout.splitlines() == ["a.txt:3: othershop.example"]


def test_plain_entry_matches_exactly(tmp_path: Path) -> None:
    allowlist = write_allowlist(tmp_path / "allowlist.txt", ["shop.example  # reserved test name"])
    repo = make_repo(tmp_path / "repo", {"a.txt": "https://shop.example/\nhttps://a.shop.example/\n"})

    result = run_scan(repo, "--allowlist", str(allowlist))

    assert result.stdout.splitlines() == ["a.txt:2: a.shop.example"]


def test_allowlist_entry_without_justification_is_rejected(tmp_path: Path) -> None:
    allowlist = write_allowlist(tmp_path / "allowlist.txt", ["shop.example"])
    repo = make_repo(tmp_path / "repo", {"a.txt": "nothing here\n"})

    result = run_scan(repo, "--allowlist", str(allowlist))

    assert result.returncode == 2
    assert "justification" in result.stderr


def test_non_public_url_hosts_pass(tmp_path: Path, empty_allowlist: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {"infra/env.txt": "A=http://127.0.0.1:8000\nB=http://api:8000/healthz\nC=http://192.0.2.10/\n"},
    )

    result = run_scan(repo, "--allowlist", str(empty_allowlist))

    assert result.returncode == 0, result.stdout


def test_untracked_and_binary_files_are_skipped(tmp_path: Path, empty_allowlist: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"blob.bin": b"\x00\x01shop.example.com\x00"})
    (repo / "untracked.txt").write_text("shop.example.com\n", encoding="utf-8")

    result = run_scan(repo, "--allowlist", str(empty_allowlist))

    assert result.returncode == 0, result.stdout


def test_clean_repo_passes_with_one_summary_line(tmp_path: Path, empty_allowlist: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"a.txt": "no hosts\n", "b.txt": "still none\n"})

    result = run_scan(repo, "--allowlist", str(empty_allowlist))

    assert result.returncode == 0
    assert result.stdout == "site-literals: ok, 2 files scanned\n"


# Dotted names that are not hosts but end in a real TLD are joined at run time, so that this file, which the scan
# also reads, contains no such token.
CALL = ".".join(["items", "map"])
MODULE_PATH = ["pkg", "api", "app"]
STDLIB_MODULE = ".".join(["collections", "abc"])


def test_python_code_is_read_only_in_strings_and_comments(tmp_path: Path, empty_allowlist: Path) -> None:
    source = (
        f"values = {CALL}(f)\n"
        'URL = f"https://shop.example.com/{x}"\n'
        "# copied from jobs.example.net\n"
        'DOC = """first line\nsecond line names www.example.org\n"""\n'
    )
    repo = make_repo(tmp_path / "repo", {"backend/src/crawlerai/collect/c.py": source})

    result = run_scan(repo, "--allowlist", str(empty_allowlist))

    assert result.stdout.splitlines() == [
        "backend/src/crawlerai/collect/c.py:2: shop.example.com",
        "backend/src/crawlerai/collect/c.py:3: jobs.example.net",
        "backend/src/crawlerai/collect/c.py:5: www.example.org",
    ]


def test_python_that_does_not_tokenize_is_read_whole(tmp_path: Path, empty_allowlist: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"broken.py": 'x = (\nhost = "shop.example.com"\n'})

    result = run_scan(repo, "--allowlist", str(empty_allowlist))

    assert result.stdout.splitlines() == ["broken.py:2: shop.example.com"]


def test_typescript_code_is_read_only_in_strings_and_comments(tmp_path: Path, empty_allowlist: Path) -> None:
    source = (
        f"const rows = {CALL}((r) => r);\n"
        'const base = "https://api.example.com/v1";\n'
        "const t = `${base}/x`; // see shop.example.net\n"
        "/* a block comment\n   naming www.example.org\n*/ const z = 1;\n"
        'const quote = /"/;\n'
        "const page = `first line\n  https://cdn.example.com/a`;\n"
    )
    repo = make_repo(tmp_path / "repo", {"frontend/src/a.tsx": source})

    result = run_scan(repo, "--allowlist", str(empty_allowlist))

    assert result.stdout.splitlines() == [
        "frontend/src/a.tsx:2: api.example.com",
        "frontend/src/a.tsx:3: shop.example.net",
        "frontend/src/a.tsx:5: www.example.org",
        "frontend/src/a.tsx:9: cdn.example.com",
    ]


def test_names_of_tracked_files_and_modules_are_not_hosts(tmp_path: Path, empty_allowlist: Path) -> None:
    module_file = "backend/src/" + "/".join(MODULE_PATH) + ".py"
    repo = make_repo(
        tmp_path / "repo",
        {
            module_file: "",
            "README.md": "",
            "Makefile": f"run:\n\tuvicorn {'.'.join(MODULE_PATH)}:app\n",
            "notes.txt": "See README.md and cli.py.\n",
        },
    )

    result = run_scan(repo, "--allowlist", str(empty_allowlist))

    assert result.returncode == 0, result.stdout


def test_url_hosts_are_checked_even_when_they_look_like_file_names(tmp_path: Path, empty_allowlist: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"README.md": "", "notes.txt": "https://readme.example/\n"})

    result = run_scan(repo, "--allowlist", str(empty_allowlist))

    assert result.stdout.splitlines() == ["notes.txt:1: readme.example"]


def test_python_templates_are_read_as_python(tmp_path: Path, empty_allowlist: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {"migrations/script.py.mako": f"from {STDLIB_MODULE} import Sequence\n# mail: email.example.com\n"},
    )

    result = run_scan(repo, "--allowlist", str(empty_allowlist))

    assert result.stdout.splitlines() == ["migrations/script.py.mako:2: email.example.com"]


def test_hosts_written_with_a_leading_dot_are_found(tmp_path: Path, empty_allowlist: Path) -> None:
    source = (
        'SUFFIX = ".shop.example.com"\n'
        'URL = f"https://{sub}.jobs.example.net/"\n'
        'OK = host.endswith(".www.example.org")\n'
        'TAIL = f"{sub}.cdn.example.com"\n'
    )
    repo = make_repo(
        tmp_path / "repo",
        {"backend/src/crawlerai/collect/hosts.py": source, "infra/config.yml": "host: .api.example.com\n"},
    )

    result = run_scan(repo, "--allowlist", str(empty_allowlist))

    assert sorted(result.stdout.splitlines()) == [
        "backend/src/crawlerai/collect/hosts.py:1: shop.example.com",
        "backend/src/crawlerai/collect/hosts.py:2: jobs.example.net",
        "backend/src/crawlerai/collect/hosts.py:3: www.example.org",
        "backend/src/crawlerai/collect/hosts.py:4: cdn.example.com",
        "infra/config.yml:1: api.example.com",
    ]
