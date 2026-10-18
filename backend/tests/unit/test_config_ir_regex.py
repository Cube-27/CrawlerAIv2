"""The portable regex subset (learning-configs spec, D-0034): patterns and replacements that Python `re` and PCRE read
the same way pass; constructs only one of them has, or that they read differently, are refused."""

import re

import pytest

from crawlerai.config_ir.portable_regex import RegexError, check_pattern, check_replacement

ACCEPTED = [
    r"^\d{3}-\d{2,}$",
    r"(?i)sku\s*[:#]\s*([A-Z0-9\-]+)",
    r"(?P<amount>\d+)(?:\.\d{2})?",
    r"(?P<q>['\"]).*?(?P=q)",
    r"(?<=\$)\d+|(?<!x)y(?=z)(?!w)",
    r"[^\]\\]+\.\x41",
    r"(a)(b)\2\1",
    r"\bword\B\W\S\D\n\t\r\f\A",
    r"a{2}b{1,3}c{0,}d*?e+?f??",
    r"(?s:.+)(?m-i:^x$)",
    "[à-ÿ]+",
    r"(?i)sku\x2D\x7F",
]

# Each is accepted by Python `re` (or compiles there with a different meaning) but is outside the shared subset.
REFUSED = [
    (r"\d+\Z", r"\\Z"),  # Python: end of string; PCRE: end or before a final newline
    ("\\u" + "0041", r"\\u"),  # Python only; PCRE writes \x{41}
    (r"\N{EM DASH}", r"\\N"),
    (r"a\vb", r"\\v"),  # PCRE: any vertical whitespace
    (r"\0", r"\\0"),
    (r"(a)\10", r"\\10"),
    (r"(?a)\w", r"\(\?a"),  # ASCII flag: Python only
    (r"(?x) a b", r"\(\?x"),
    (r"(?<name>x)", r"\(\?<n"),
    (r"(?>ab)", r"\(\?>"),
    (r"x{,3}", r"\{,3\}"),
    (r"x{a}", r"\{a\}"),
    (r"[[:alpha:]]", r"\["),
    (r"[a&&b]", r"&&"),
    (r"[a--b]", r"--"),
    (r"[]a]", r"\]"),
    (r"[\b]", r"\\b"),
    (r"(?P<n" + "x" * 32 + r">a)", r"\(\?P<"),  # PCRE2 group names are at most 32 characters
    # PCRE2 in UTF mode (`/u`) folds case for non-ASCII letters; Python with `re.ASCII` folds ASCII only.
    ("(?i)straße", "non-ASCII"),
    ("(?m-i:x)é", "non-ASCII"),
    (r"(?i)\xe9", "non-ASCII"),
]


@pytest.mark.parametrize("pattern", ACCEPTED)
def test_portable_patterns_pass(pattern: str) -> None:
    assert check_pattern(pattern) == pattern


@pytest.mark.parametrize(("pattern", "construct"), REFUSED)
def test_constructs_outside_the_subset_are_refused(pattern: str, construct: str) -> None:
    with pytest.raises(RegexError, match=construct):
        check_pattern(pattern)


# A grammar of the shared subset: literals, escapes both engines read alike, classes, groups and quantifiers.
@pytest.mark.parametrize(
    ("replacement", "groups", "construct"),
    [
        (r"\g<1>", 1, r"\\g"),  # Python only
        (r"\n", 0, r"\\n"),  # Python turns it into a newline, PHP keeps it
        ("$1", 1, r"\$1"),  # PHP group reference, Python literal
        ("${1}", 1, r"\$\{"),
        (r"\12", 12, r"\\12"),
        (r"\2", 1, "group 2"),
        ("x\\", 0, "trailing"),
    ],
)
def test_replacements_outside_the_subset_are_refused(replacement: str, groups: int, construct: str) -> None:
    pattern = re.compile("(a)" * groups)
    with pytest.raises(RegexError, match=construct):
        check_replacement(replacement, pattern)
