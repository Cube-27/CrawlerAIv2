"""Fail when a tracked file names a site outside the places allowed to (SPEC-00 §4.7, INV-03, C3).

A site literal is the host of an `http(s)://` URL, or a whole dotted token whose last label is in the IANA root-zone
list (pinned in `backend/data/manifest.json`). Hosts in `tools/site_literal_allowlist.txt` and files under the exempt
paths pass. Tests are not exempt (C9).

Dotted tokens are also file names (`cli.py`) and attribute accesses in code, so:
- in source code (Python, including `*.py.*` templates, and JS/TS) only string literals and comments are scanned;
- a two-label token whose last label is the extension of a tracked file is a file name;
- a token that is the dotted path of a tracked Python module is a module name.
URL hosts are always checked.

With `--public`, `--staged` (the pre-commit hook) scans only the files staged for commit, as the index holds
them. Names of tracked files and modules still come from the whole repository.

Prints `path:line: host` per finding and exits 1, or prints one summary line and exits 0. Exits 2 when the
allowlist or the TLD list cannot be used.

`--hidden-hosts-from-env VAR` (the protected job, INV-04) reads hidden hosts from the environment variable VAR,
separated by whitespace or commas, and scans every tracked file, with no path exemption and no allowlist. A host
matches itself and its subdomains, case-insensitively, anywhere in a file; any character other than a letter, digit,
`.` or `-` bounds it. The job log is public, so it prints only `path:line` per finding (`path:0` when the path itself
names a host), with every occurrence of a host in the path replaced by `[hidden]`, and never a host. An unset or
empty VAR passes: the environment holding the list may not exist yet (SPEC-00 §4.6).
"""

import argparse
import io
import ipaddress
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
DEFAULT_ALLOWLIST = REPO / "tools/site_literal_allowlist.txt"

EXEMPT_DIRS = ("backend/src/crawlerai/adapters/", "docs/", ".github/")
EXEMPT_NAMES = frozenset({"pnpm-lock.yaml", "package.json", "pyproject.toml", "LICENSE", "NOTICE"})
EXEMPT_SUFFIXES = (".lock",)
EXEMPT_FILES = frozenset({"backend/data/manifest.json"})

JS_SUFFIXES = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")

# Escapes such as backslash-n in a source literal separate words; they are not part of the token that follows.
ESCAPE = re.compile(r"\\[nrtfv]")
URL = re.compile(r"(?i)\bhttps?://(?:[^\s/@?#]*@)?(\[[^\]\s]*\]|[^\s/:?#'\"<>()\[\]{}\\,;`]+)")
# A whole dotted token; the lookahead stops a token that does not end in a TLD from yielding its leading labels.
# A leading dot is not part of the token, so `.shop.example.com` and `{sub}.shop.example.com` are still hosts. Only
# host characters bound a token, so `_` separates it from a neighbouring word (`cache_shop.example.com`).
DOTTED = re.compile(r"(?i)(?<![a-z0-9-])[a-z0-9-]+(?:\.[a-z0-9-]+)+(?![a-z0-9-]|\.[a-z0-9-])")
# Hidden mode reads every run of host characters as a token, so any other character, `_` included, separates hosts.
HOST_RUN = re.compile(r"(?i)[a-z0-9.-]+")
# JS/TS string literals and comments, matched left to right. Quoted strings stay on one line, so a regex literal
# holding a quote cannot swallow the rest of the file; template literals and block comments may span lines.
JS_PIECE = re.compile(r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`|//[^\n]*|/\*.*?\*/", re.DOTALL)

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


@dataclass(frozen=True)
class RepoNames:
    """Names the repository itself defines, which dotted tokens may refer to instead of a host."""

    extensions: frozenset[str]
    modules: frozenset[str]

    @classmethod
    def of(cls, paths: list[str]) -> "RepoNames":
        extensions: set[str] = set()
        modules: set[str] = set()
        for path in paths:
            pure = PurePosixPath(path)
            if pure.suffix:
                extensions.add(pure.suffix[1:].lower())
            if pure.suffix == ".py":
                parts = [*pure.parent.parts, pure.stem] if pure.stem != "__init__" else list(pure.parent.parts)
                modules.update(".".join(parts[start:]).lower() for start in range(len(parts)))
        return cls(frozenset(extensions), frozenset(modules))

    def names(self, token: str) -> bool:
        labels = token.split(".")
        return (len(labels) == 2 and labels[1] in self.extensions) or token in self.modules


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


def tracked_files(root: Path) -> list[str]:
    return [name for name in git(root, "ls-files", "-z").decode("utf-8").split("\0") if name]


def staged_files(root: Path) -> list[str]:
    """Files added, copied, modified or renamed in the index; a deletion leaves nothing to scan."""
    listing = git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [name for name in listing.decode("utf-8").split("\0") if name]


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
    for match in DOTTED.finditer(text):
        token = match.group(0).lower()
        if token.rsplit(".", 1)[1] in tlds and not repo_names.names(token):
            yield token


def scan(root: Path, allowlist: Allowlist, tlds: frozenset[str], *, staged: bool) -> tuple[list[str], int]:
    """Return the findings and the number of files scanned."""
    tracked = tracked_files(root)
    repo_names = RepoNames.of(tracked)
    findings: list[str] = []
    scanned = 0
    for path in staged_files(root) if staged else tracked:
        file = root / path
        if is_exempt(path) or not (staged or file.is_file()):
            continue
        data = git(root, "show", f":{path}") if staged else file.read_bytes()
        if b"\0" in data:
            continue
        scanned += 1
        reported: set[tuple[int, str]] = set()
        for number, text in segments_of(path, data.decode("utf-8", errors="replace")):
            for host in hosts_in(text, tlds, repo_names):
                if (number, host) not in reported and not allowlist.allows(host):
                    reported.add((number, host))
                    findings.append(f"{path}:{number}: {host}")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--public", action="store_true", help="scan with exemptions (CI, hooks)")
    mode.add_argument("--hidden-hosts-from-env", metavar="VAR", help="scan everything for the hosts listed in VAR")
    parser.add_argument("--staged", action="store_true", help="public mode only: scan staged files (hooks)")
    parser.add_argument("--root", type=Path, default=REPO, help="repository to scan")
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST, help="public mode only")
    args = parser.parse_args(argv)

    if args.hidden_hosts_from_env is not None:
        return run_hidden(args.root.resolve(), args.hidden_hosts_from_env)

    try:
        allowlist = Allowlist.load(args.allowlist)
        tlds = load_tlds(TLD_LIST)
    except (OSError, UsageError) as error:
        print(f"site-literals: {error}", file=sys.stderr)
        return 2

    findings, scanned = scan(args.root.resolve(), allowlist, tlds, staged=args.staged)
    for finding in findings:
        print(finding)
    if findings:
        print(f"site-literals: {len(findings)} site literal(s) outside adapters/ (C3)", file=sys.stderr)
        return 1
    print(f"site-literals: ok, {scanned} files scanned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
