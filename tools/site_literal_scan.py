"""Fail when a tracked file names a site outside the places allowed to (SPEC-00 §4.7, INV-03, C3).

A site literal is the host of an `http(s)://` URL, or a whole dotted token whose last label is in the IANA root-zone
list (pinned in `backend/data/manifest.json`). Hosts in `tools/site_literal_allowlist.txt` and files under the exempt
paths pass. Tests are not exempt (C9).

Dotted tokens are also file names (`cli.py`) and attribute accesses in code, so:
- in source code only string literals and comments are scanned;
- a two-label token whose last label is the extension of a tracked file is a file name;
- a token that is the dotted path of a tracked Python module, or that a line imports (`from <token> import`), is
  a module name.
URL hosts are always checked.

Prints `path:line: host` per finding and exits 1, or prints one summary line and exits 0. Exits 2 when the
allowlist or the TLD list cannot be used.
"""

import argparse
import io
import ipaddress
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
# An import statement at the start of a line; prose such as "copied from <host>" is not one.
IMPORT = re.compile(r"^\s*(?:from|import)\s+$")
URL = re.compile(r"(?i)\bhttps?://(?:[^\s/@?#]*@)?(\[[^\]\s]*\]|[^\s/:?#'\"<>()\[\]{}\\,;`]+)")
# String literals, line comments and block-comment openers in JS/TS, matched left to right on one line.
JS_PIECE = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`|//.*|/\*")

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
        return host in self.exact or any(host == suffix[1:] or host.endswith(suffix) for suffix in self.suffixes)


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


def hostname_pattern(tld_list: Path) -> re.Pattern[str]:
    tlds = [line.strip().lower() for line in tld_list.read_text(encoding="ascii").splitlines()]
    tlds = sorted((tld for tld in tlds if tld and not tld.startswith("#")), key=len, reverse=True)
    if not tlds:
        raise UsageError(f"{tld_list} lists no TLDs")
    # The lookarounds keep the match to a whole dotted token: a token that does not end in a TLD yields nothing,
    # rather than its leading labels.
    alternatives = "|".join(map(re.escape, tlds))
    return re.compile(r"(?i)(?<![\w.-])(?:[a-z0-9-]+\.)+(?:" + alternatives + r")(?![\w-]|\.[\w-])")


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


def tracked_files(root: Path) -> list[str]:
    listing = subprocess.run(  # noqa: S603
        ["git", "-C", str(root), "ls-files", "-z"],  # noqa: S607
        capture_output=True,
        check=True,
    )
    return [name for name in listing.stdout.decode("utf-8").split("\0") if name]


def split_lines(first_line: int, text: str) -> Iterator[Segment]:
    for offset, line in enumerate(text.splitlines()):
        yield first_line + offset, line


def python_segments(text: str) -> list[Segment]:
    """String literals and comments; the whole file when it does not tokenize."""
    kept = {tokenize.STRING, tokenize.COMMENT, tokenize.FSTRING_MIDDLE}
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError):
        return list(split_lines(1, text))
    return [segment for token in tokens if token.type in kept for segment in split_lines(token.start[0], token.string)]


def js_segments(text: str) -> list[Segment]:
    """String literals and comments, read line by line (a template literal spanning lines is read as code)."""
    segments: list[Segment] = []
    in_block = False
    for number, line in split_lines(1, text):
        rest = line
        while rest:
            if in_block:
                comment, closed, rest = rest.partition("*/")
                segments.append((number, comment))
                in_block = not closed
                continue
            match = JS_PIECE.search(rest)
            if match is None:
                break
            if match.group(0) == "/*":
                in_block = True
            else:
                segments.append((number, match.group(0)))
            rest = rest[match.end() :]
    return segments


def segments_of(path: str, text: str) -> list[Segment]:
    if path.endswith(".py"):
        return python_segments(text)
    if path.endswith(JS_SUFFIXES):
        return js_segments(text)
    return list(split_lines(1, text))


def hosts_in(text: str, hostnames: re.Pattern[str], repo_names: RepoNames) -> Iterator[str]:
    text = ESCAPE.sub(" ", text)
    for match in URL.finditer(text):
        host = match.group(1).lower().rstrip(".")
        if not names_no_public_site(host):
            yield host
    for match in hostnames.finditer(text):
        token = match.group(0).lower()
        if not (repo_names.names(token) or IMPORT.search(text, 0, match.start())):
            yield token


def scan(root: Path, allowlist: Allowlist, hostnames: re.Pattern[str]) -> tuple[list[str], int]:
    """Return the findings and the number of files scanned."""
    paths = tracked_files(root)
    repo_names = RepoNames.of(paths)
    findings: list[str] = []
    scanned = 0
    for path in paths:
        file = root / path
        if is_exempt(path) or not file.is_file():
            continue
        data = file.read_bytes()
        if b"\0" in data:
            continue
        scanned += 1
        reported: set[tuple[int, str]] = set()
        for number, text in segments_of(path, data.decode("utf-8", errors="replace")):
            for host in hosts_in(text, hostnames, repo_names):
                if (number, host) not in reported and not allowlist.allows(host):
                    reported.add((number, host))
                    findings.append(f"{path}:{number}: {host}")
    return findings, scanned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--public", action="store_true", required=True, help="scan with exemptions (CI, hooks)")
    parser.add_argument("--root", type=Path, default=REPO, help="repository to scan")
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    args = parser.parse_args(argv)

    try:
        allowlist = Allowlist.load(args.allowlist)
        hostnames = hostname_pattern(TLD_LIST)
    except (OSError, UsageError) as error:
        print(f"site-literals: {error}", file=sys.stderr)
        return 2

    findings, scanned = scan(args.root, allowlist, hostnames)
    for finding in findings:
        print(finding)
    if findings:
        print(f"site-literals: {len(findings)} site literal(s) outside adapters/ (C3)", file=sys.stderr)
        return 1
    print(f"site-literals: ok, {scanned} files scanned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
