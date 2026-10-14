"""Hypothesis profiles: CI runs every property test with a fixed `max_examples=200` (SPEC-04 §6); local runs keep
the Hypothesis default. GitHub Actions sets `CI`. For INV-26, counters of HTML parser constructions."""

import os
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from hypothesis import settings
from lxml import html as lxml_html
from selectolax import lexbor

settings.register_profile("ci", max_examples=200)
settings.load_profile("ci" if os.environ.get("CI") else "default")


class ParserCounter:
    """Counts the constructions of one parser, with the first argument of each (the document parsed)."""

    def __init__(self) -> None:
        self.inputs: list[object] = []

    @property
    def calls(self) -> int:
        return len(self.inputs)

    def wrap(self, constructor: Callable[..., Any]) -> Callable[..., Any]:
        def counted(*args: Any, **kwargs: Any) -> Any:
            self.inputs.append(args[0] if args else None)
            return constructor(*args, **kwargs)

        return counted


@pytest.fixture
def parses(monkeypatch: pytest.MonkeyPatch) -> Mapping[str, ParserCounter]:
    """INV-26: the selectolax and lxml parser constructions while the test runs."""
    counters = {"selectolax": ParserCounter(), "lxml": ParserCounter()}
    monkeypatch.setattr(lexbor, "LexborHTMLParser", counters["selectolax"].wrap(lexbor.LexborHTMLParser))
    monkeypatch.setattr(lxml_html, "document_fromstring", counters["lxml"].wrap(lxml_html.document_fromstring))
    return counters
