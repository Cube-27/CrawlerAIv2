"""The XPath 1.0 check (SPEC-08 §4.2, D-0034): expressions libxml2 compiles that use only the W3C XPath 1.0 core
function library pass; XPath 2+ syntax and functions, variables and namespace prefixes are refused."""

import re

import pytest

from crawlerai.config_ir.xpath1 import XPath1Error, check_xpath1

# Expressions of the shapes induction and the CSS translator write, plus every operator name in operator position.
# XPath 2.0/3.1 (W3C) syntax that libxml2 does not parse, and an unclosed call.
REFUSED_SYNTAX = [
    "for $a in //a return $a",
    "//a || //b",
    "concat('a'",
]


# W3C XPath 1.0 §4.1-4.4: the core function library.
@pytest.mark.parametrize("expression", REFUSED_SYNTAX)
def test_xpath2_syntax_is_refused(expression: str) -> None:
    with pytest.raises(XPath1Error):
        check_xpath1(expression)


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("upper-case(//h1)", "upper-case() is not an XPath 1.0 function"),
        ("mod(1)", "mod() is not an XPath 1.0 function"),
        ("//p[1] and div(2)", "div() is not an XPath 1.0 function"),
        ("//svg:rect", "namespace prefix in svg:rect"),
        ("//a[@href = $url]", "variable references are not allowed"),
    ],
)
def test_refusals_name_the_construct(expression: str, message: str) -> None:
    with pytest.raises(XPath1Error, match=re.escape(message)):
        check_xpath1(expression)
