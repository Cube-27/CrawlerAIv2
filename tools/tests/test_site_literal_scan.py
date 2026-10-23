"""Behaviour of `tools/site_literal_scan.py --public`, run as CI runs it.

Every host here is reserved by RFC 2606 or RFC 6761. Detection tests pass an explicit allowlist so that those
reserved names are not exempted.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from scan_repo import SCAN, make_repo


def run_scan(root: Path, *args: str, allowlist: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the scan on `root`; `allowlist` lines go to an untracked file inside `root`, passed as `--allowlist`."""
    if allowlist is not None:
        path = root / "allowlist.txt"
        path.write_text("".join(f"{line}\n" for line in allowlist), encoding="utf-8")
        args = (*args, "--allowlist", str(path))
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCAN), "--public", "--root", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_hostname_in_generic_code_fails_with_path_line_and_lowercase_host_once_per_line(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {
            "backend/src/crawlerai/collect/hosts.py": 'X = 1\nHOST = "shop.example.com"\n',
            "backend/src/crawlerai/acquire/fetch.py": 'U = "https://shop.retailer.test/p?q=1"\n',
            "backend/tests/unit/test_x.py": 'URL = "https://jobs.example.net/1"\n',
            "a.txt": "see https://SHOP.EXAMPLE.COM/x and shop.example.com\n",
        },
    )

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 1
    assert sorted(result.stdout.splitlines()) == [
        "a.txt:1: shop.example.com",
        "backend/src/crawlerai/acquire/fetch.py:1: shop.retailer.test",
        "backend/src/crawlerai/collect/hosts.py:2: shop.example.com",
        "backend/tests/unit/test_x.py:1: jobs.example.net",
    ]


@pytest.mark.parametrize("path", ["backend/src/crawlerai/adapters/platform.py", "docs/notes.md", "backend/uv.lock"])
def test_exempt_paths_pass(tmp_path: Path, path: str) -> None:
    repo = make_repo(tmp_path / "repo", {path: "https://shop.example.com/\n"})

    assert run_scan(repo, allowlist=[]).returncode == 0


@pytest.mark.parametrize("dotdot", [False, True], ids=["absolute", "dotdot"])
def test_allowlist_outside_the_scanned_repository_is_rejected(tmp_path: Path, dotdot: bool) -> None:
    outside = tmp_path / "allowlist.txt"
    outside.write_text("shop.example  # reserved test name\n", encoding="utf-8")
    repo = make_repo(tmp_path / "repo", {"a.txt": "https://shop.example/\n"})
    path = repo / ".." / "allowlist.txt" if dotdot else outside

    result = run_scan(repo, "--allowlist", str(path))

    assert result.returncode == 2
    assert result.stdout == ""
    assert "outside the repository" in result.stderr


# Dotted names that are not hosts but end in a real TLD are joined at run time, so that this file, which the scan
# also reads, contains no such token.
CALL = ".".join(["items", "map"])
MODULE_PATH = ["pkg", "api", "app"]


def test_python_code_is_read_only_in_strings_and_comments(tmp_path: Path) -> None:
    source = (
        f"values = {CALL}(f)\n"
        'URL = f"https://shop.example.com/{x}"\n'
        "# copied from jobs.example.net\n"
        'DOC = """first line\nsecond line names www.example.org\n"""\n'
    )
    repo = make_repo(
        tmp_path / "repo",
        {"backend/src/crawlerai/collect/c.py": source, "broken.py": 'x = (\nhost = "shop.example.com"\n'},
    )

    result = run_scan(repo, allowlist=[])

    assert sorted(result.stdout.splitlines()) == [
        "backend/src/crawlerai/collect/c.py:2: shop.example.com",
        "backend/src/crawlerai/collect/c.py:3: jobs.example.net",
        "backend/src/crawlerai/collect/c.py:5: www.example.org",
        "broken.py:2: shop.example.com",
    ]


def test_names_of_tracked_files_and_modules_are_not_hosts_but_urls_are_checked(tmp_path: Path) -> None:
    module_file = "backend/src/" + "/".join(MODULE_PATH) + ".py"
    repo = make_repo(
        tmp_path / "repo",
        {
            module_file: "",
            "README.md": "",
            "run.sh": f"uvicorn {'.'.join(MODULE_PATH)}:app\n",
            "notes.txt": "See README.md and cli.py.\n",
            "link.txt": "https://readme.example/\n",
        },
    )

    result = run_scan(repo, allowlist=[])

    assert result.stdout.splitlines() == ["link.txt:1: readme.example"]


# Attributes of modules, joined at run time like the names above: `.now` is a TLD.
MODULE_ATTRIBUTE = ".".join([*MODULE_PATH[1:], "now"])
NEW_MODULE_ATTRIBUTE = ".".join(["pkg", "fresh", "now"])
ONE_LABEL_PREFIX = ".".join([MODULE_PATH[-1], "now"])


def test_attributes_of_modules_are_not_hosts_but_one_label_prefixes_and_urls_are_checked(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {
            "backend/src/" + "/".join(MODULE_PATH) + ".py": "",
            "notes.txt": f"{MODULE_ATTRIBUTE}_stalled() and {NEW_MODULE_ATTRIBUTE}()\n",
            "hosts.txt": f"{ONE_LABEL_PREFIX} and app.example.com\nhttps://{MODULE_ATTRIBUTE}/\n",
        },
    )
    # Not yet added: a module written in the same change as the comment that names it.
    (repo / "backend/src/pkg/fresh.py").write_text("", encoding="utf-8")

    result = run_scan(repo, allowlist=[])

    assert result.stdout.splitlines() == [
        f"hosts.txt:1: {ONE_LABEL_PREFIX}",
        "hosts.txt:1: app.example.com",
        f"hosts.txt:2: {MODULE_ATTRIBUTE}",
    ]


# `table.column` reference, joined at run time like the names above: `.id` is a TLD.
WIDGET_ID = ".".join(["widget", "id"])
MIGRATION = 'def upgrade():\n    op.create_table("widget", sa.Column("id", sa.Uuid()))\n'


def test_references_to_columns_the_schema_defines_are_not_hosts_but_lookalikes_are(tmp_path: Path) -> None:
    models = f'A = ForeignKey("{WIDGET_ID}")\nB = "shop.{WIDGET_ID}"\n'
    repo = make_repo(
        tmp_path / "repo",
        {"backend/migrations/versions/0001_widgets.py": MIGRATION, "backend/src/crawlerai/db/models.py": models},
    )

    result = run_scan(repo, allowlist=[])

    assert result.stdout.splitlines() == [f"backend/src/crawlerai/db/models.py:2: shop.{WIDGET_ID}"]


# schema.org paths ending in a TLD (`.name`), joined at run time like the names above.
PRODUCT_NAME = ".".join(["Product", "name"])
BRAND_NAME = ".".join(["Product", "brand", "name"])
OFFER_NAME = ".".join(["Offer", "name"])
THING_NAME = ".".join(["Thing", "name"])


def schema_document(fields: dict[str, object], **extra: object) -> str:
    """A JSON schema document with the given fields, on one line."""
    return json.dumps({"name": "p", "page_kind": "listing", "fields": fields, **extra}) + "\n"


PRESET = schema_document(
    {
        "title": {"type": "text", "schema_org": PRODUCT_NAME},
        "rows": {"type": "list", "item": {"type": "object", "fields": {"brand": {"schema_org": BRAND_NAME}}}},
        "label": {"type": "text", "schema_org": f"Product.alternateName>{THING_NAME}|Product.sku"},
    }
)


def test_schema_org_paths_the_schema_documents_define_are_not_hosts(tmp_path: Path) -> None:
    refs = f'A = "{PRODUCT_NAME}"\n# maps to {BRAND_NAME}, ranked after another: {THING_NAME}\n'
    repo = make_repo(tmp_path / "repo", {"schemas/p.json": PRESET, "refs.py": refs})

    result = run_scan(repo, allowlist=[])

    assert (result.returncode, result.stdout) == (0, "site-literals: ok, 2 files scanned\n")
