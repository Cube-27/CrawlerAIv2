"""Fail when a tracked file names a site outside the places allowed to (SPEC-00 §4.7, INV-03, C3).

A site literal is the host of an `http(s)://` URL, or a whole dotted token whose last label is in the IANA root-zone
list (pinned in `backend/data/manifest.json`). Hosts in `tools/site_literal_allowlist.txt` and files under the exempt
paths pass. Tests are not exempt (C9).

Dotted tokens are also file names (`cli.py`) and attribute accesses in code, so:
- in source code (Python, including `*.py.*` templates, and JS/TS) only string literals and comments are scanned;
- a two-label token whose last label is the extension of a tracked file, or of a data file
  `backend/data/manifest.json` pins (a fetched one is not tracked; SPEC-04 §4.6), is a file name;
- a token that is the dotted path of a tracked Python module is a module name;
- a two-label token `table.column` naming a column of a table the repository's schema defines is a qualified column
  reference (SQL's `<column reference>`), as in `ForeignKey("table.column")`. The schema is read from the tracked
  Python files: Alembic `create_table` and `add_column`, SQLAlchemy `Table`, and declarative `__tablename__` classes;
- a token that is, as written, a schema.org property path some tracked schema document maps a field to is that path.
  A schema document is a JSON object with a `name`, a `page_kind` and a `fields` object
  (SPEC-04 §4.2); the paths are the `schema_org` values of its fields, of their `item` and of their nested `fields`,
  up to any `+`, that follow schema.org naming. The paths are read from the documents, as columns are read from the
  schema.
Schemas (the tables and the schema documents) are read only from files outside the exempt paths: an exempt file
is not scanned, so a name it defines would excuse a host it is free to hold. URL hosts are always checked.

With `--public`, `--staged` (the pre-commit hook) scans only the files staged for commit, as the index holds
them. Names of tracked files, modules and schemas still come from the whole repository, as above.

Prints `path:line: host` per finding and exits 1, or prints one summary line and exits 0. Exits 2 when the
allowlist or the TLD list cannot be used, or when `--allowlist` lies outside the scanned repository (`--root`);
the default is that repository's `tools/site_literal_allowlist.txt`.

`--hidden-hosts-from-env VAR` (the protected job, INV-04) reads hidden hosts from the environment variable VAR,
separated by whitespace or commas, and scans every tracked file, with no path exemption and no allowlist. A host
matches itself and its subdomains, case-insensitively, anywhere in a file; any character other than a letter, digit,
`.` or `-` bounds it. The job log is public, so it prints only `path:line` per finding (`path:0` when the path itself
names a host), with every occurrence of a host in the path replaced by `[hidden]`, and never a host. An unset or
empty VAR passes: the environment holding the list may not exist yet (SPEC-00 §4.6).
"""

import argparse
import ast
import io
import ipaddress
import json
import os
import re
import subprocess
import sys
import tokenize
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]
TLD_LIST = REPO / "backend/data/iana/tlds-alpha-by-domain.txt"
DEFAULT_ALLOWLIST = PurePosixPath("tools/site_literal_allowlist.txt")

# Documentation is exempt (D-0004): `docs/` and, since the OpenSpec layout, `openspec/` (D-1136).
EXEMPT_DIRS = ("backend/src/crawlerai/adapters/", "docs/", "openspec/", ".github/")
EXEMPT_NAMES = frozenset({"pnpm-lock.yaml", "package.json", "pyproject.toml", "LICENSE", "NOTICE"})
EXEMPT_SUFFIXES = (".lock",)
DATA_MANIFEST = "backend/data/manifest.json"
EXEMPT_FILES = frozenset({DATA_MANIFEST})

JS_SUFFIXES = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")

# Escapes such as backslash-n in a source literal separate words; they are not part of the token that follows.
ESCAPE = re.compile(r"\\[nrtfv]")
URL = re.compile(r"(?i)\bhttps?://(?:[^\s/@?#]*@)?(\[[^\]\s]*\]|[^\s/:?#'\"<>()\[\]{}\\,;`]+)")
# A whole dotted token; the lookahead stops a token that does not end in a TLD from yielding its leading labels.
# A leading dot is not part of the token, so `.shop.example.com` and `{sub}.shop.example.com` are still hosts. Only
# host characters bound a token, so `_` separates it from a neighbouring word (`cache_shop.example.com`).
DOTTED = re.compile(r"(?i)(?<![a-z0-9-])[a-z0-9-]+(?:\.[a-z0-9-]+)+(?![a-z0-9-]|\.[a-z0-9-])")
# A qualified column reference: two SQL identifiers (letters, digits, `_`) joined by one dot, bounded by characters
# that are neither identifier nor host characters, so `cache_shop.example.com` is not one.
COLUMN_REF = re.compile(r"(?i)(?<![\w.-])([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)(?![\w-]|\.[\w-])")
# schema.org naming conventions (https://schema.org/docs/styleguide.html): a path starts at an UpperCamelCase type and
# follows lowerCamelCase properties; `+` joins a second property of the last type (SPEC-04 §4.2), and `|` separates
# alternative paths (SPEC-13 §4.1). A path is matched only as written, so a host in its usual lowercase form is never
# one.
SCHEMA_ORG_PATH = re.compile(r"([A-Z][A-Za-z0-9]*(?:\.[a-z][A-Za-z0-9]*)+)(?:\+[a-z][A-Za-z0-9]*)?")
# Hidden mode reads every run of host characters as a token, so any other character, `_` included, separates hosts.
HOST_RUN = re.compile(r"(?i)[a-z0-9.-]+")
# JS/TS string literals and comments, matched left to right. Quoted strings stay on one line, so a regex literal
# holding a quote cannot swallow the rest of the file; template literals and block comments may span lines.
JS_DOUBLE_QUOTED = r'"(?:[^"\\\n]|\\.)*"'
JS_SINGLE_QUOTED = r"'(?:[^'\\\n]|\\.)*'"
JS_TEMPLATE = r"`(?:[^`\\]|\\.)*`"
JS_LINE_COMMENT = r"//[^\n]*"
JS_BLOCK_COMMENT = r"/\*.*?\*/"
JS_PIECE = re.compile(
    "|".join((JS_DOUBLE_QUOTED, JS_SINGLE_QUOTED, JS_TEMPLATE, JS_LINE_COMMENT, JS_BLOCK_COMMENT)), re.DOTALL
)

HIDDEN = "[hidden]"

Segment = tuple[int, str]


class UsageError(Exception):
    pass


@dataclass(frozen=True)
class Allowlist:
    exact: frozenset[str]
    suffixes: tuple[str, ...]

    @classmethod
    def load(cls, path: Path) -> "Allowlist":
        exact: set[str] = set()
        suffixes: list[str] = []
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            entry, _, justification = raw.partition("#")
            entry = entry.strip().lower()
            if not entry:
                continue
            if not justification.strip():
                raise UsageError(f"{path.name}:{number}: '{entry}' needs a justification after '#'")
            if entry.startswith("."):
                suffixes.append(entry)
            else:
                exact.add(entry)
        return cls(frozenset(exact), tuple(suffixes))

    def allows(self, host: str) -> bool:
        """A plain entry matches only itself; an entry starting with '.' matches that name and its subdomains."""
        return host in self.exact or host.endswith(self.suffixes) or f".{host}" in self.suffixes


def call_name(node: ast.expr) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    return node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)


def string_arg(node: ast.expr) -> str | None:
    first = node.args[0] if isinstance(node, ast.Call) and node.args else None
    return first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None


def schema_columns(file: Path) -> Iterator[tuple[str, str]]:
    """The `(table, column)` pairs a Python file's schema definitions declare; none when it does not parse."""
    try:
        tree = ast.parse(file.read_bytes())
    except (OSError, SyntaxError, ValueError):
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and call_name(node) in {"create_table", "Table", "add_column"}:
            yield from table_call_columns(node)
        elif isinstance(node, ast.ClassDef):
            yield from declarative_columns(node)


def table_call_columns(node: ast.Call) -> Iterator[tuple[str, str]]:
    """Alembic `create_table` and `add_column`, SQLAlchemy `Table`: the table name, then `Column("name", ...)`s."""
    table = string_arg(node)
    if not table:
        return
    for argument in node.args[1:]:
        if call_name(argument) == "Column" and (column := string_arg(argument)):
            yield table, column


def declared_table(node: ast.ClassDef) -> str | None:
    """The `__tablename__` a declarative class assigns, when it is a string."""
    for statement in node.body:
        if (
            isinstance(statement, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "__tablename__" for target in statement.targets)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            return statement.value.value
    return None


def assignment(statement: ast.stmt) -> tuple[list[ast.expr], ast.expr] | None:
    """The targets and value of a class-body assignment, annotated or not; None for any other statement."""
    if isinstance(statement, ast.AnnAssign) and statement.value:
        return [statement.target], statement.value
    if isinstance(statement, ast.Assign):
        return statement.targets, statement.value
    return None


def declarative_columns(node: ast.ClassDef) -> Iterator[tuple[str, str]]:
    table = declared_table(node)
    if table is None:
        return
    for statement in node.body:
        assigned = assignment(statement)
        if assigned is None or call_name(assigned[1]) not in {"mapped_column", "Column"}:
            continue
        targets, value = assigned
        yield from ((table, string_arg(value) or target.id) for target in targets if isinstance(target, ast.Name))


def schema_org_paths(file: Path) -> Iterator[str]:
    """The schema.org paths a JSON schema document maps its fields to; none when the file is not one."""
    try:
        document = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # UnicodeDecodeError is a ValueError
        return
    if not (
        isinstance(document, dict)
        and isinstance(document.get("name"), str)
        and isinstance(document.get("page_kind"), str)
        and isinstance(document.get("fields"), dict)
    ):
        return
    stack = list(document["fields"].values())
    while stack:
        field = stack.pop()
        if not isinstance(field, dict):
            continue
        yield from _paths(field.get("schema_org"))
        if isinstance(item := field.get("item"), dict):
            stack.append(item)
        if isinstance(fields := field.get("fields"), dict):
            stack.extend(fields.values())


def _paths(value: object) -> Iterator[str]:
    """The paths of a field's `schema_org` value, one per `|` alternative, each up to any `+`."""
    if isinstance(value, str):
        for alternative in value.split("|"):
            if match := SCHEMA_ORG_PATH.fullmatch(alternative):
                yield match[1]


def module_names(pure: PurePosixPath) -> set[str]:
    """Every dotted name a Python file can be imported as: its full module path and each of its suffixes."""
    parts = [*pure.parent.parts, pure.stem] if pure.stem != "__init__" else list(pure.parent.parts)
    return {".".join(parts[start:]).lower() for start in range(len(parts))}


@dataclass(frozen=True)
class RepoNames:
    """Names the repository itself defines, which dotted tokens may refer to instead of a host."""

    extensions: frozenset[str]
    modules: frozenset[str]
    columns: frozenset[tuple[str, str]]
    schema_paths: frozenset[str]

    @classmethod
    def of(cls, root: Path, paths: list[str]) -> "RepoNames":
        extensions: set[str] = set()
        modules: set[str] = set()
        for path in paths:
            pure = PurePosixPath(path)
            if pure.suffix:
                extensions.add(pure.suffix[1:].lower())
            if pure.suffix == ".py":
                modules.update(module_names(pure))
            if path == DATA_MANIFEST:
                extensions.update(manifest_extensions(root / path))
        # An exempt file is not scanned, so it may hold anything: a schema it defines excuses no token.
        sources = [PurePosixPath(path) for path in paths if not is_exempt(path)]
        columns = {
            (table.lower(), column.lower())
            for path in sources
            if path.suffix == ".py"
            for table, column in schema_columns(root / path)
        }
        schema_paths = {found for path in sources if path.suffix == ".json" for found in schema_org_paths(root / path)}
        return cls(frozenset(extensions), frozenset(modules), frozenset(columns), frozenset(schema_paths))

    def names(self, token: str) -> bool:
        """Whether the token, as written, is a file name, a module or a schema.org path."""
        lowered = token.lower()
        labels = lowered.split(".")
        return (
            (len(labels) == 2 and labels[1] in self.extensions) or lowered in self.modules or token in self.schema_paths
        )

    def without_column_references(self, text: str) -> str:
        """The text with each `table.column` reference to a column the schema defines blanked out."""
        return COLUMN_REF.sub(
            lambda match: " " * len(match[0]) if (match[1].lower(), match[2].lower()) in self.columns else match[0],
            text,
        )


def manifest_extensions(manifest: Path) -> Iterator[str]:
    """The extensions, lowercase, of the data files the manifest pins; nothing when it does not read as one."""
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8")).get("entries")
    except (OSError, ValueError, AttributeError):
        return
    for entry in entries if isinstance(entries, list) else []:
        path = entry.get("path") if isinstance(entry, dict) else None
        if isinstance(path, str) and (suffix := PurePosixPath(path).suffix):
            yield suffix[1:].lower()


def load_tlds(tld_list: Path) -> frozenset[str]:
    lines = (line.strip().lower() for line in tld_list.read_text(encoding="ascii").splitlines())
    tlds = frozenset(line for line in lines if line and not line.startswith("#"))
    if not tlds:
        raise UsageError(f"{tld_list} lists no TLDs")
    return tlds


def is_exempt(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (
        path in EXEMPT_FILES or path.startswith(EXEMPT_DIRS) or name in EXEMPT_NAMES or name.endswith(EXEMPT_SUFFIXES)
    )


def names_no_public_site(url_host: str) -> bool:
    """Single-label hosts (`localhost`, compose service names) and non-global IP literals name no public site."""
    host = url_host.strip("[]")
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return "." not in host


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True).stdout  # noqa: S603, S607


def git_paths(root: Path, *args: str) -> list[str]:
    """The paths a `-z` git listing prints."""
    return [name for name in git(root, *args).decode("utf-8").split("\0") if name]


def tracked_files(root: Path) -> list[str]:
    return git_paths(root, "ls-files", "-z")


def lines_from(first_line: int, text: str) -> list[Segment]:
    return list(enumerate(text.splitlines(), start=first_line))


def python_segments(text: str) -> list[Segment]:
    """String literals and comments; the whole file when it does not tokenize."""
    kept = {tokenize.STRING, tokenize.COMMENT, tokenize.FSTRING_MIDDLE}
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError):
        return lines_from(1, text)
    return [segment for token in tokens if token.type in kept for segment in lines_from(token.start[0], token.string)]


def js_segments(text: str) -> list[Segment]:
    """String literals and comments."""
    segments: list[Segment] = []
    line, position = 1, 0
    for match in JS_PIECE.finditer(text):
        line += text.count("\n", position, match.start())
        position = match.start()
        segments.extend(lines_from(line, match.group(0)))
    return segments


def segments_of(path: str, text: str) -> list[Segment]:
    if ".py" in PurePosixPath(path).suffixes:
        return python_segments(text)
    if path.endswith(JS_SUFFIXES):
        return js_segments(text)
    return lines_from(1, text)


def hosts_in(text: str, tlds: frozenset[str], repo_names: RepoNames) -> Iterator[str]:
    text = ESCAPE.sub(" ", text)
    for match in URL.finditer(text):
        host = match.group(1).lower().rstrip(".")
        if not names_no_public_site(host):
            yield host
    for match in DOTTED.finditer(repo_names.without_column_references(text)):
        token = match.group(0)
        if token.rsplit(".", 1)[1].lower() in tlds and not repo_names.names(token):
            yield token.lower()


def paths_to_scan(root: Path, tracked: list[str], *, staged: bool) -> list[str]:
    if staged:
        # Added, copied, modified or renamed in the index; a deletion leaves nothing to scan.
        return git_paths(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [path for path in tracked if (root / path).is_file()]


def file_findings(path: str, text: str, allowlist: Allowlist, tlds: frozenset[str], repo_names: RepoNames) -> list[str]:
    """One `path:line: host` per host the allowlist doesn't allow, once per line."""
    seen: set[tuple[int, str]] = set()
    findings: list[str] = []
    for number, segment in segments_of(path, text):
        for host in hosts_in(segment, tlds, repo_names):
            if (number, host) not in seen and not allowlist.allows(host):
                seen.add((number, host))
                findings.append(f"{path}:{number}: {host}")
    return findings


def scan(root: Path, allowlist: Allowlist, tlds: frozenset[str], *, staged: bool) -> tuple[list[str], int]:
    """Return the findings and the number of files scanned."""
    tracked = tracked_files(root)
    repo_names = RepoNames.of(root, tracked)
    findings: list[str] = []
    scanned = 0
    for path in paths_to_scan(root, tracked, staged=staged):
        if is_exempt(path):
            continue
        data = git(root, "show", f":{path}") if staged else (root / path).read_bytes()
        if b"\0" in data:
            continue
        scanned += 1
        text = data.decode("utf-8", errors="replace")
        findings.extend(file_findings(path, text, allowlist, tlds, repo_names))
    return findings, scanned


def names_hidden(token: str, hosts: frozenset[str]) -> bool:
    """Whether any run of the token's labels is a hidden host: the host itself, a subdomain, or a prefix."""
    labels = token.lower().split(".")
    return any(
        ".".join(labels[start:end]) in hosts
        for start in range(len(labels))
        for end in range(start + 1, len(labels) + 1)
    )


def withhold(path: str, starts: re.Pattern[str]) -> str:
    """The path with each run of characters covered by a host occurrence replaced by `[hidden]`."""
    covered = [False] * len(path)
    for match in starts.finditer(path):
        covered[match.start(1) : match.end(1)] = [True] * len(match.group(1))
    pieces: list[str] = []
    for index, character in enumerate(path):
        if not covered[index]:
            pieces.append(character)
        elif index == 0 or not covered[index - 1]:
            pieces.append(HIDDEN)
    return "".join(pieces)


def scan_hidden(root: Path, hosts: frozenset[str]) -> tuple[list[str], int]:
    """Return `path:line` findings, with hidden hosts withheld from paths, and the number of files scanned.

    Content tokens are looked up in the host set, so that cost does not grow with the number of hosts. A path is shown
    with every case-insensitive occurrence of a host replaced, whatever surrounds it, so no tokenizing gap can leak one.
    """
    # A lookahead finds the occurrences that start at every position, so overlapping hosts are all found.
    starts = re.compile(f"(?=({'|'.join(map(re.escape, sorted(hosts, key=len, reverse=True)))}))", re.IGNORECASE)
    findings: list[str] = []
    scanned = 0
    for path in tracked_files(root):
        file = root / path
        if not file.is_file():
            continue
        scanned += 1
        shown = withhold(path, starts)
        if any(names_hidden(token, hosts) for token in HOST_RUN.findall(path)):
            findings.append(f"{shown}:0")
        findings.extend(
            f"{shown}:{number}"
            for number, line in lines_from(1, file.read_text(encoding="utf-8", errors="replace"))
            if any(names_hidden(token, hosts) for token in HOST_RUN.findall(ESCAPE.sub(" ", line)))
        )
    return findings, scanned


def run_hidden(root: Path, variable: str) -> int:
    value = os.environ.get(variable, "")
    hosts = frozenset(host for raw in re.split(r"[\s,]+", value) if (host := raw.strip(".").lower()))
    if not hosts:
        print("hidden-hosts: pass, no host list configured")
        return 0
    findings, scanned = scan_hidden(root, hosts)
    for finding in findings:
        print(finding)
    if findings:
        print(f"hidden-hosts: fail, {len(findings)} match(es)", file=sys.stderr)
        return 1
    print(f"hidden-hosts: pass, {scanned} files scanned")
    return 0


def inside(root: Path, path: Path) -> Path:
    """`path` resolved, when it lies inside the resolved `root`: the allowlist is part of the repository it governs."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise UsageError(f"{path} is outside the repository {root}")
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--public", action="store_true", help="scan with exemptions (CI, hooks)")
    mode.add_argument("--hidden-hosts-from-env", metavar="VAR", help="scan everything for the hosts listed in VAR")
    parser.add_argument("--staged", action="store_true", help="public mode only: scan staged files (hooks)")
    parser.add_argument("--root", type=Path, default=REPO, help="repository to scan")
    parser.add_argument("--allowlist", type=Path, help=f"public mode only; default: <root>/{DEFAULT_ALLOWLIST}")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if args.hidden_hosts_from_env is not None:
        return run_hidden(root, args.hidden_hosts_from_env)

    try:
        allowlist = Allowlist.load(inside(root, args.allowlist or root / DEFAULT_ALLOWLIST))
        tlds = load_tlds(TLD_LIST)
    except (OSError, UsageError) as error:
        print(f"site-literals: {error}", file=sys.stderr)
        return 2

    findings, scanned = scan(root, allowlist, tlds, staged=args.staged)
    for finding in findings:
        print(finding)
    if findings:
        print(f"site-literals: {len(findings)} site literal(s) outside adapters/ (C3)", file=sys.stderr)
        return 1
    print(f"site-literals: ok, {scanned} files scanned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
