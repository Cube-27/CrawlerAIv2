"""CSS steps keep the XPath they were stored with across cssselect upgrades (SPEC-08 §4.2: `css` is compiled to XPath
at validation time and stored as both). A stored step whose `xpath` is not today's translation of its `css` is
refused, so an upgrade that translated any selector differently would stop stored configs from loading. This replays
translations recorded with the locked cssselect: a dependency bump that changes one fails here, before it ships."""

import json
from pathlib import Path

import pytest

from crawlerai.config_ir.model import CssStep

RECORDED = Path(__file__).parents[1] / "fixtures" / "synthetic" / "css_translations.json"
TRANSLATIONS: dict[str, str] = json.loads(RECORDED.read_text(encoding="utf-8"))


@pytest.mark.parametrize(("css", "xpath"), TRANSLATIONS.items())
def test_a_stored_css_step_loads_with_the_translation_it_was_stored_with(css: str, xpath: str) -> None:
    step = CssStep.model_validate({"css": css, "xpath": xpath})

    assert (step.css, step.xpath) == (css, xpath)
