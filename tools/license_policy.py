"""Fail when a dependency's declared license is on the deny-list (CI job 3).

Reads the reports that `tools/license_scan.sh` collects: `pip-licenses --from=all --format=json` for the Python
environment and `pnpm licenses list --json` for the frontend. A declaration is matched as an SPDX license
expression, by whole identifier and never by substring, so LGPL does not match GPL. `OR` passes when any
branch is clean, `AND` needs every operand clean, and `WITH` judges the license it modifies. A declaration that is
not a valid expression (a trove classifier, free text) is matched by its whole name.

Exit status: 0 when no package is denied, 1 otherwise, with one stderr line per denied package.
"""

import argparse
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

DENIED_SPDX = [
    "AGPL-3.0",
    "AGPL-3.0-only",
    "AGPL-3.0-or-later",
    "GPL-2.0",
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0",
    "GPL-3.0-only",
    "GPL-3.0-or-later",
    "SSPL-1.0",
    "CC-BY-NC-4.0",
    "CC-BY-NC-SA-4.0",
    "CC-BY-NC-ND-4.0",
    "PolyForm-Noncommercial-1.0.0",
    "Commons-Clause",
]
# The PyPI trove classifiers (https://pypi.org/classifiers/) that name the same denied licenses. Packages that
# predate PEP 639 declare their license only this way.
DENIED_TROVE = [
    "GNU Affero General Public License v3",
    "GNU Affero General Public License v3 or later (AGPLv3+)",
    "GNU General Public License (GPL)",
    "GNU General Public License v2 (GPLv2)",
    "GNU General Public License v2 or later (GPLv2+)",
    "GNU General Public License v3 (GPLv3)",
    "GNU General Public License v3 or later (GPLv3+)",
]
DENIED = {name.casefold(): name for name in DENIED_SPDX + DENIED_TROVE}
UNKNOWN = "UNKNOWN"  # pip-licenses' value for a field the package does not declare

TOKEN = re.compile(r"\s*(\(|\)|[A-Za-z0-9.+:-]+)")


class ExpressionError(ValueError):
    pass


def denied_name(name: str) -> set[str]:
    """Whole-name match, ignoring case; returns the deny-list spelling."""
    key = name.strip().casefold()
    return {DENIED[key]} if key in DENIED else set()


def tokenize(expression: str) -> list[str]:
    expression = expression.strip()
    tokens: list[str] = []
    position = 0
    while position < len(expression):
        match = TOKEN.match(expression, position)
        if match is None:
            raise ExpressionError(expression)
        tokens.append(match.group(1))
        position = match.end()
    return tokens


class Parser:
    """SPDX license expression (SPDX spec Annex D); precedence WITH > AND > OR.

    Each parse method returns the denied licenses the expression cannot avoid.
    """

    def __init__(self, expression: str) -> None:
        self.tokens = tokenize(expression)
        self.position = 0

    def parse(self) -> set[str]:
        denied = self.or_expression()
        if self.current() is not None:
            raise ExpressionError(self.tokens[self.position])
        return denied

    def current(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def peek_operator(self, operator: str) -> bool:
        token = self.current()
        return token is not None and token.upper() == operator

    def or_expression(self) -> set[str]:
        branches = [self.and_expression()]
        while self.peek_operator("OR"):
            self.position += 1
            branches.append(self.and_expression())
        return set() if not all(branches) else set().union(*branches)

    def and_expression(self) -> set[str]:
        denied = self.with_expression()
        while self.peek_operator("AND"):
            self.position += 1
            denied |= self.with_expression()
        return denied

    def with_expression(self) -> set[str]:
        denied = self.primary()
        if self.peek_operator("WITH"):
            self.position += 1
            # An exception never makes a denied license acceptable, and Commons-Clause is itself written as one.
            denied |= denied_name(self.identifier())
        return denied

    def primary(self) -> set[str]:
        if self.current() == "(":
            self.position += 1
            denied = self.or_expression()
            if self.current() != ")":
                raise ExpressionError("unbalanced parentheses")
            self.position += 1
            return denied
        return denied_name(self.identifier().removesuffix("+"))  # `+` is SPDX "or later"

    def identifier(self) -> str:
        token = self.current()
        if token is None:
            raise ExpressionError("expected a license identifier")
        if token in ("(", ")") or token.upper() in ("AND", "OR", "WITH"):
            raise ExpressionError(token)
        self.position += 1
        return token


def denied_licenses(declared: str) -> set[str]:
    try:
        return Parser(declared).parse()
    except ExpressionError:
        return denied_name(declared)


def python_declarations(package: dict[str, str]) -> list[str]:
    """The declaration that governs: License-Expression (PEP 639), else every classifier, else License metadata."""
    if package["License-Expression"] != UNKNOWN:
        return [package["License-Expression"]]
    if package["License-Classifier"] != UNKNOWN:
        return package["License-Classifier"].split("; ")
    return [package["License-Metadata"]]


def violation(ecosystem: str, package: str, declared: str) -> str | None:
    denied = denied_licenses(declared)
    if not denied:
        return None
    return f"denied license: {ecosystem} {package}: {', '.join(sorted(denied))} (declared {declared!r})"


def node_packages(node: dict[str, list[dict[str, Any]]]) -> Iterator[tuple[str, str]]:
    """(`name version`, declared license) for every installed version in a `pnpm licenses list --json` report."""
    for group in node.values():
        for package in group:
            for version in package["versions"]:
                yield f"{package['name']} {version}", package["license"]


def violations(python: list[dict[str, str]], node: dict[str, list[dict[str, Any]]]) -> list[str]:
    found = [
        violation("python", f"{package['Name']} {package['Version']}", declared)
        for package in python
        for declared in python_declarations(package)
    ]
    found += [violation("node", package, declared) for package, declared in node_packages(node)]
    return [line for line in found if line is not None]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--python", type=Path, required=True, help="pip-licenses --from=all --format=json output")
    parser.add_argument("--node", type=Path, required=True, help="pnpm licenses list --json output")
    args = parser.parse_args()
    python = json.loads(args.python.read_text(encoding="utf-8"))
    node = json.loads(args.node.read_text(encoding="utf-8"))

    found = violations(python, node)
    for line in found:
        print(line, file=sys.stderr)
    if found:
        return 1
    print(f"licenses ok: {len(python)} python and {sum(1 for _ in node_packages(node))} node packages checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
