"""Fixtures shared by unit tests: for the platform adapter tests (SPEC-02 §4.9) a JSONPath selector and the presets'
schema.org projections."""

import re
from collections.abc import Callable
from typing import Any

import pytest

from crawlerai.schemas.registry import load_presets


def _select(path: str, document: Any) -> list[Any]:
    """The values a mapped path selects: `$`, then `['name']` member and `[*]` wildcard segments (RFC 9535 §2.5)."""
    nodes = [document]
    for segment in re.findall(r"\['([^']*)'\]|\[\*\]", path.removeprefix("$")):
        if segment:
            nodes = [node[segment] for node in nodes if isinstance(node, dict) and segment in node]
        else:
            nodes = [item for node in nodes for item in node]
    return nodes


@pytest.fixture
def select_json() -> Callable[[str, Any], list[Any]]:
    return _select


def _preset_fields(preset: str) -> dict[str, str]:
    """The preset's `field -> schema.org path` projection, what an adapter's `map` takes."""
    (schema,) = (s for s in load_presets() if s.name == preset)
    return {name: spec.schema_org for name, spec in schema.fields.items() if spec.schema_org is not None}


@pytest.fixture
def preset_fields() -> Callable[[str], dict[str, str]]:
    return _preset_fields
