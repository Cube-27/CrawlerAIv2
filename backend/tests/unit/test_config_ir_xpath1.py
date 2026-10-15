"""The XPath 1.0 check (SPEC-08 §4.2, D-0034): expressions libxml2 compiles that use only the W3C XPath 1.0 core
function library pass; XPath 2+ syntax and functions, variables and namespace prefixes are refused."""

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.config_ir.xpath1 import XPATH1_FUNCTIONS, XPath1Error, check_xpath1

# Expressions of the shapes induction and the CSS translator write, plus every operator name in operator position.
ACCEPTED = [
    "//h1",
    "normalize-space(//h1[@data-testid='title'])",
    "descendant-or-self::li[count(preceding-sibling::*) mod 2 = 0]",
    "descendant-or-self::input[(@checked and name(.) = 'input')and (@type = 'radio')]",
    "count(//li) div (2) * 3",
    "//*[local-name()='div' or starts-with(@id, 'x')]/node()",
    "//a | //b",
    "//a[. != 'x' and position() >= 1]",
]

# XPath 2.0/3.1 (W3C) syntax that libxml2 does not parse, and an unclosed call.
REFUSED_SYNTAX = [
    "for $a in //a return $a",
    "//a || //b",
    "concat('a'",
]


@pytest.mark.parametrize("expression", ACCEPTED)
def test_xpath1_expressions_pass(expression: str) -> None:
    assert check_xpath1(expression) == expression


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


_NCNAME = st.from_regex(r"[a-z][a-z0-9]{0,6}(-[a-z0-9]{1,6}){0,2}", fullmatch=True)


@given(_NCNAME.filter(lambda name: name not in XPATH1_FUNCTIONS | {"node", "text", "comment"}))
def test_any_function_outside_the_core_library_is_refused(name: str) -> None:
    expression = f"//p[{name}(.)]"
    with pytest.raises(XPath1Error, match=rf"{name}\(\) is not an XPath 1.0 function"):
        check_xpath1(expression)
