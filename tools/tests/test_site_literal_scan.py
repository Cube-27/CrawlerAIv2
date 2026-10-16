"""Behaviour of `tools/site_literal_scan.py --public` (SPEC-00 §4.7), run as CI runs it.

Every host here is reserved by RFC 2606 or RFC 6761. Detection tests pass an explicit allowlist so that those
reserved names are not exempted.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from scan_repo import SCAN, commit, git, make_repo


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


def test_hostname_in_generic_code_fails_with_path_line_and_host(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {"backend/src/crawlerai/collect/hosts.py": 'X = 1\nHOST = "shop.example.com"\n'},
    )

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 1
    assert result.stdout.splitlines() == ["backend/src/crawlerai/collect/hosts.py:2: shop.example.com"]


def test_url_host_outside_the_tld_list_fails(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "repo", {"backend/src/crawlerai/acquire/fetch.py": 'U = "https://shop.retailer.test/p?q=1"\n'}
    )

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 1
    assert result.stdout.splitlines() == ["backend/src/crawlerai/acquire/fetch.py:1: shop.retailer.test"]


def test_hosts_are_reported_lowercase_once_per_line(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"a.txt": "see https://SHOP.EXAMPLE.COM/x and shop.example.com\n"})

    result = run_scan(repo, allowlist=[])

    assert result.stdout.splitlines() == ["a.txt:1: shop.example.com"]


def test_tests_are_not_exempt(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"backend/tests/unit/test_x.py": 'URL = "https://jobs.example.net/1"\n'})

    result = run_scan(repo, allowlist=[])

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
def test_exempt_paths_pass(tmp_path: Path, path: str) -> None:
    repo = make_repo(tmp_path / "repo", {path: "https://shop.example.com/\n"})

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 0, result.stdout


def test_path_exemptions_do_not_leak_to_similar_paths(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {
            "backend/src/crawlerai/adapters_extra/x.py": 'H = "shop.example.com"\n',
            "backend/docs/x.md": "shop.example.com\n",
        },
    )

    result = run_scan(repo, allowlist=[])

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
            ),
            "tools/site_literal_allowlist.txt": (SCAN.parent / "site_literal_allowlist.txt").read_bytes(),
        },
    )

    result = run_scan(repo)

    assert result.returncode == 0, result.stdout


def test_dotted_entry_covers_the_name_and_its_subdomains_only(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {"a.txt": "https://shop.example/\nhttps://a.shop.example/\nhttps://othershop.example/\n"},
    )

    result = run_scan(repo, allowlist=[".shop.example  # reserved test name"])

    assert result.stdout.splitlines() == ["a.txt:3: othershop.example"]


def test_plain_entry_matches_exactly(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"a.txt": "https://shop.example/\nhttps://a.shop.example/\n"})

    result = run_scan(repo, allowlist=["shop.example  # reserved test name"])

    assert result.stdout.splitlines() == ["a.txt:2: a.shop.example"]


def test_allowlist_entry_without_justification_is_rejected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"a.txt": "nothing here\n"})

    result = run_scan(repo, allowlist=["shop.example"])

    assert result.returncode == 2
    assert "justification" in result.stderr


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


def test_non_public_url_hosts_pass(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {"infra/env.txt": "A=http://127.0.0.1:8000\nB=http://api:8000/healthz\nC=http://192.0.2.10/\n"},
    )

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 0, result.stdout


def test_untracked_and_binary_files_are_skipped(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"blob.bin": b"\x00\x01shop.example.com\x00"})
    (repo / "untracked.txt").write_text("shop.example.com\n", encoding="utf-8")

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 0, result.stdout


def test_clean_repo_passes_with_one_summary_line(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"a.txt": "no hosts\n", "b.txt": "still none\n"})

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 0
    assert result.stdout == "site-literals: ok, 2 files scanned\n"


# Dotted names that are not hosts but end in a real TLD are joined at run time, so that this file, which the scan
# also reads, contains no such token.
CALL = ".".join(["items", "map"])
MODULE_PATH = ["pkg", "api", "app"]
STDLIB_MODULE = ".".join(["collections", "abc"])


def test_python_code_is_read_only_in_strings_and_comments(tmp_path: Path) -> None:
    source = (
        f"values = {CALL}(f)\n"
        'URL = f"https://shop.example.com/{x}"\n'
        "# copied from jobs.example.net\n"
        'DOC = """first line\nsecond line names www.example.org\n"""\n'
    )
    repo = make_repo(tmp_path / "repo", {"backend/src/crawlerai/collect/c.py": source})

    result = run_scan(repo, allowlist=[])

    assert result.stdout.splitlines() == [
        "backend/src/crawlerai/collect/c.py:2: shop.example.com",
        "backend/src/crawlerai/collect/c.py:3: jobs.example.net",
        "backend/src/crawlerai/collect/c.py:5: www.example.org",
    ]


def test_python_that_does_not_tokenize_is_read_whole(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"broken.py": 'x = (\nhost = "shop.example.com"\n'})

    result = run_scan(repo, allowlist=[])

    assert result.stdout.splitlines() == ["broken.py:2: shop.example.com"]


def test_typescript_code_is_read_only_in_strings_and_comments(tmp_path: Path) -> None:
    source = (
        f"const rows = {CALL}((r) => r);\n"
        'const base = "https://api.example.com/v1";\n'
        "const t = `${base}/x`; // see shop.example.net\n"
        "/* a block comment\n   naming www.example.org\n*/ const z = 1;\n"
        'const quote = /"/;\n'
        "const page = `first line\n  https://cdn.example.com/a`;\n"
    )
    repo = make_repo(tmp_path / "repo", {"frontend/src/a.tsx": source})

    result = run_scan(repo, allowlist=[])

    assert result.stdout.splitlines() == [
        "frontend/src/a.tsx:2: api.example.com",
        "frontend/src/a.tsx:3: shop.example.net",
        "frontend/src/a.tsx:5: www.example.org",
        "frontend/src/a.tsx:9: cdn.example.com",
    ]


def test_names_of_tracked_files_and_modules_are_not_hosts(tmp_path: Path) -> None:
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

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 0, result.stdout


def test_names_with_the_extension_of_a_data_file_the_manifest_pins_are_not_hosts(tmp_path: Path) -> None:
    # A fetched data file is not tracked (SPEC-04 §4.6), so its extension is known from the manifest, not from git.
    manifest = json.dumps({"entries": [{"path": "geo/cities.md", "fetched": True}]})
    code = 'CITIES = "cities.md"\nOTHER = "towns.md"\n'
    files: dict[str, str | bytes] = {"backend/src/crawlerai/normalize/geo.py": code}
    without = make_repo(tmp_path / "without", files)
    with_manifest = make_repo(tmp_path / "with", {**files, "backend/data/manifest.json": manifest})

    assert run_scan(without, allowlist=[]).stdout.splitlines() == [
        "backend/src/crawlerai/normalize/geo.py:1: cities.md",
        "backend/src/crawlerai/normalize/geo.py:2: towns.md",
    ]
    assert run_scan(with_manifest, allowlist=[]).returncode == 0


def test_an_unreadable_manifest_adds_no_extensions(tmp_path: Path) -> None:
    # Tracked but gone from the working tree: the scan reads no extensions from it and still runs.
    repo = make_repo(tmp_path / "repo", {"backend/data/manifest.json": "{}", "a.txt": "see cities.md\n"})
    (repo / "backend/data/manifest.json").unlink()

    assert run_scan(repo, allowlist=[]).stdout.splitlines() == ["a.txt:1: cities.md"]


def test_url_hosts_are_checked_even_when_they_look_like_file_names(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"README.md": "", "notes.txt": "https://readme.example/\n"})

    result = run_scan(repo, allowlist=[])

    assert result.stdout.splitlines() == ["notes.txt:1: readme.example"]


def test_python_templates_are_read_as_python(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {"migrations/script.py.mako": f"from {STDLIB_MODULE} import Sequence\n# mail: email.example.com\n"},
    )

    result = run_scan(repo, allowlist=[])

    assert result.stdout.splitlines() == ["migrations/script.py.mako:2: email.example.com"]


def test_hosts_written_with_a_leading_dot_are_found(tmp_path: Path) -> None:
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

    result = run_scan(repo, allowlist=[])

    assert sorted(result.stdout.splitlines()) == [
        "backend/src/crawlerai/collect/hosts.py:1: shop.example.com",
        "backend/src/crawlerai/collect/hosts.py:2: jobs.example.net",
        "backend/src/crawlerai/collect/hosts.py:3: www.example.org",
        "backend/src/crawlerai/collect/hosts.py:4: cdn.example.com",
        "infra/config.yml:1: api.example.com",
    ]


def test_hosts_joined_to_underscores_are_found(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "repo", {"a.txt": "foo_shop.example.com_v2\n", "b.py": 'NAME = "cache_jobs.example.net"\n'}
    )

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 1
    assert result.stdout.splitlines() == ["a.txt:1: shop.example.com", "b.py:1: jobs.example.net"]


# `table.column` references, joined at run time like the names above: `.id` and `.io` are TLDs.
WIDGET_ID = ".".join(["widget", "id"])
WIDGET_IO = ".".join(["widget", "io"])
WIDGET_PART_ID = ".".join(["widget_part", "id"])
GADGET_ID = ".".join(["gadget", "id"])
MIGRATION = (
    "import sqlalchemy as sa\n"
    "from alembic import op\n"
    "def upgrade():\n"
    '    op.create_table("widget", sa.Column("id", sa.Uuid()), sa.Column("name", sa.Text()))\n'
    '    op.create_table("widget_part", sa.Column("id", sa.Uuid()))\n'
)


def test_references_to_columns_the_schema_defines_are_not_hosts(tmp_path: Path) -> None:
    models = (
        "from sqlalchemy import ForeignKey\n"
        f'A = ForeignKey("{WIDGET_ID}")\n'
        f'B = ForeignKey("{WIDGET_PART_ID}")\n'
        f"# joins on {WIDGET_ID} = {WIDGET_PART_ID}\n"
    )
    repo = make_repo(
        tmp_path / "repo",
        {"backend/migrations/versions/0001_widgets.py": MIGRATION, "backend/src/crawlerai/db/models.py": models},
    )

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 0, result.stdout


def test_declarative_models_and_added_columns_define_the_schema(tmp_path: Path) -> None:
    models = (
        "class Gadget(Base):\n"
        '    __tablename__ = "gadget"\n'
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "class WidgetPart(Base):\n"
        '    __tablename__ = "widget_part"\n'
        "    id = Column(Uuid)\n"
        "def upgrade():\n"
        '    op.add_column("widget", sa.Column("io", sa.Text()))\n'
    )
    notes = f"{GADGET_ID}, {WIDGET_PART_ID} and {WIDGET_IO}\n"
    repo = make_repo(tmp_path / "repo", {"backend/src/crawlerai/db/models.py": models, "notes.txt": notes})

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 0, result.stdout


def test_table_column_shapes_the_schema_does_not_define_are_hosts(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {
            "backend/migrations/versions/0001_widgets.py": MIGRATION,
            "backend/src/crawlerai/db/refs.py": f'A = "{GADGET_ID}"\nB = "{WIDGET_IO}"\n',
        },
    )

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        f"backend/src/crawlerai/db/refs.py:1: {GADGET_ID}",
        f"backend/src/crawlerai/db/refs.py:2: {WIDGET_IO}",
    ]


def test_hosts_that_start_with_a_table_name_are_still_found(tmp_path: Path) -> None:
    hosts = (
        'A = "widget.example.com"\n'
        f'B = "https://{WIDGET_ID}/p"\n'
        f'C = "shop.{WIDGET_ID}"\n'
        f'D = "{WIDGET_ID}.example.net"\n'
    )
    repo = make_repo(
        tmp_path / "repo",
        {"backend/migrations/versions/0001_widgets.py": MIGRATION, "backend/src/crawlerai/collect/hosts.py": hosts},
    )

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "backend/src/crawlerai/collect/hosts.py:1: widget.example.com",
        f"backend/src/crawlerai/collect/hosts.py:2: {WIDGET_ID}",
        f"backend/src/crawlerai/collect/hosts.py:3: shop.{WIDGET_ID}",
        f"backend/src/crawlerai/collect/hosts.py:4: {WIDGET_ID}.example.net",
    ]


def test_staged_mode_scans_only_staged_files(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"old.txt": "shop.example.com\n", "new.txt": "clean\n"})
    commit(repo)
    (repo / "new.txt").write_text("clean\njobs.example.net\n", encoding="utf-8")
    git(repo, "add", "new.txt")

    result = run_scan(repo, "--staged", allowlist=[])

    assert result.returncode == 1
    assert result.stdout.splitlines() == ["new.txt:2: jobs.example.net"]


def test_staged_mode_reads_the_index_not_the_working_tree(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"a.txt": "shop.example.com\n", "b.txt": "clean\n"})
    (repo / "a.txt").write_text("clean now\n", encoding="utf-8")
    (repo / "b.txt").write_text("jobs.example.net\n", encoding="utf-8")

    result = run_scan(repo, "--staged", allowlist=[])

    assert result.returncode == 1
    assert result.stdout.splitlines() == ["a.txt:1: shop.example.com"]


def test_staged_mode_passes_with_nothing_staged_or_only_deletions(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"old.txt": "shop.example.com\n"})
    commit(repo)

    nothing = run_scan(repo, "--staged", allowlist=[])
    git(repo, "rm", "-q", "old.txt")
    deletion = run_scan(repo, "--staged", allowlist=[])

    assert (nothing.returncode, nothing.stdout) == (0, "site-literals: ok, 0 files scanned\n")
    assert (deletion.returncode, deletion.stdout) == (0, "site-literals: ok, 0 files scanned\n")


def test_staged_mode_keeps_exemptions_and_names_from_the_whole_repo(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"backend/src/crawlerai/collect/hosts.py": "X = 1\n"})
    commit(repo)
    make_repo(
        repo,
        {
            "docs/notes.md": "https://shop.example.com/\n",
            "backend/src/crawlerai/collect/use.py": '"""See crawlerai.collect.hosts."""\n',
        },
    )

    result = run_scan(repo, "--staged", allowlist=[])

    assert (result.returncode, result.stdout) == (0, "site-literals: ok, 1 files scanned\n")


# schema.org paths ending in a TLD (`.name`), joined at run time like the names above.
PRODUCT_NAME = ".".join(["Product", "name"])
BRAND_NAME = ".".join(["Product", "brand", "name"])
OFFER_NAME = ".".join(["Offer", "name"])
# A host in the place of a schema.org path; it is in no allowlist the tests pass.
SHOP = ".".join(["shop", "example", "com"])


def schema_document(fields: dict[str, object], **extra: object) -> str:
    """A JSON schema document (SPEC-04 §4.2) with the given fields, on one line."""
    return json.dumps({"name": "p", "page_kind": "listing", "fields": fields, **extra}) + "\n"


PRESET = schema_document(
    {
        "title": {"type": "text", "schema_org": PRODUCT_NAME},
        "rows": {"type": "list", "item": {"type": "object", "fields": {"brand": {"schema_org": BRAND_NAME}}}},
        "price": {"type": "money", "schema_org": "Offer.price+priceCurrency"},
    }
)


def test_schema_org_paths_the_schema_documents_define_are_not_hosts(tmp_path: Path) -> None:
    refs = f'A = "{PRODUCT_NAME}"\n# maps to {BRAND_NAME}\n'
    repo = make_repo(tmp_path / "repo", {"schemas/p.json": PRESET, "refs.py": refs})

    result = run_scan(repo, allowlist=[])

    assert (result.returncode, result.stdout) == (0, "site-literals: ok, 2 files scanned\n")


def test_schema_org_shapes_no_schema_document_defines_are_hosts(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "repo",
        {
            "schemas/p.json": PRESET,
            "q.json": f'{{"same_as": "{OFFER_NAME}"}}\n',  # another key
            "broken.json": f'{{"schema_org": "{OFFER_NAME}"\n',  # not JSON
            "refs.py": f'A = "{OFFER_NAME}"\nB = "shop.{PRODUCT_NAME}"\n',
        },
    )

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        f"broken.json:1: {OFFER_NAME.lower()}",
        f"q.json:1: {OFFER_NAME.lower()}",
        f"refs.py:1: {OFFER_NAME.lower()}",
        f"refs.py:2: shop.{PRODUCT_NAME.lower()}",
    ]


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(json.dumps({"schema_org": OFFER_NAME}), id="not-a-schema-document"),
        pytest.param(json.dumps({"fields": {"a": {"schema_org": OFFER_NAME}}}), id="no-name-page-kind"),
        pytest.param(schema_document({}, schema_org=OFFER_NAME), id="outside-a-field"),
        pytest.param(schema_document({"a": {"description": {"schema_org": OFFER_NAME}}}), id="not-a-field-key"),
    ],
)
def test_schema_org_values_outside_field_specs_of_schema_documents_are_hosts(tmp_path: Path, document: str) -> None:
    repo = make_repo(tmp_path / "repo", {"d.json": document, "refs.py": f'A = "{OFFER_NAME}"\n'})

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 1
    assert f"refs.py:1: {OFFER_NAME.lower()}" in result.stdout.splitlines()


def test_schema_org_paths_follow_schema_org_naming_and_match_as_written(tmp_path: Path) -> None:
    """A path is an UpperCamelCase type, then lowerCamelCase properties: a lowercase host in a field's `schema_org`
    exempts nothing, and a path written in another case is not that path."""
    repo = make_repo(
        tmp_path / "repo",
        {
            "schemas/p.json": PRESET,
            "d.json": schema_document({"a": {"type": "text", "schema_org": SHOP}}),
            "refs.py": f'A = "{SHOP}"\nB = "{PRODUCT_NAME.lower()}"\n',
        },
    )

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        f"d.json:1: {SHOP}",
        f"refs.py:1: {SHOP}",
        f"refs.py:2: {PRODUCT_NAME.lower()}",
    ]


def test_each_alternative_of_a_schema_org_path_is_a_path(tmp_path: Path) -> None:
    preset = schema_document({"sku": {"type": "identifier", "schema_org": f"Product.sku|{OFFER_NAME}"}})
    repo = make_repo(tmp_path / "repo", {"schemas/p.json": preset, "refs.py": f'A = "{OFFER_NAME}"\n'})

    result = run_scan(repo, allowlist=[])

    assert (result.returncode, result.stdout) == (0, "site-literals: ok, 2 files scanned\n")


# Exempt paths are not scanned, so they may hold anything; a name they define must not excuse a host elsewhere.
ADAPTER = "backend/src/crawlerai/adapters/shop.py"
EXEMPT_SCHEMAS = {
    ADAPTER: 'def upgrade():\n    op.create_table("widget", sa.Column("io", sa.Text()))\n',
    "docs/p.json": schema_document({"a": {"type": "text", "schema_org": OFFER_NAME}}),
}
REFS = f'A = "{WIDGET_IO}"\nB = "{OFFER_NAME}"\n'
EXPECTED_REFS = [f"refs.py:1: {WIDGET_IO}", f"refs.py:2: {OFFER_NAME.lower()}"]


def test_schemas_under_exempt_paths_define_no_names(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {**EXEMPT_SCHEMAS, "refs.py": REFS})

    result = run_scan(repo, allowlist=[])

    assert result.returncode == 1
    assert result.stdout.splitlines() == EXPECTED_REFS


def test_staged_mode_takes_schemas_from_non_exempt_tracked_files_only(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {**EXEMPT_SCHEMAS, "backend/migrations/versions/0001_widgets.py": MIGRATION})
    commit(repo)
    make_repo(repo, {"refs.py": f'{REFS}C = "{WIDGET_ID}"\n'})

    result = run_scan(repo, "--staged", allowlist=[])

    assert result.returncode == 1
    assert result.stdout.splitlines() == EXPECTED_REFS
