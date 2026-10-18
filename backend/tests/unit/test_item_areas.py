"""The browser rung's item geometry (listings spec, "Item groups"): the rendered area of each block of a listing's
repeated item groups, by the element path that names it again in the kept document. The page is a fake (no browser)."""

import asyncio
from typing import cast

from patchright.async_api import Error as PlaywrightError
from patchright.async_api import Page

from crawlerai.acquire.browser import AREAS_JS, item_areas
from crawlerai.acquire.items import element_path, item_groups, lxml_root

BODY = (
    "<html><body><h1>Kettles</h1><ul>"
    + "".join(f'<li class="c"><a href="/p/{i}">Kettle {i}</a><span>{i} EUR</span></li>' for i in range(4))
    + "</ul></body></html>"
).encode()


class _Page:
    """Answers the areas script with one area per element it is asked about, or fails as a closed page does."""

    def __init__(self, *, fails: bool = False, missing: bool = False) -> None:
        self.asked: list[list[list[str]]] = []
        self.fails = fails
        self.missing = missing  # the live document no longer holds the last element

    async def evaluate(self, script: str, refs: list[list[str]]) -> list[float]:
        assert script == AREAS_JS
        if self.fails:
            raise PlaywrightError("Target page, context or browser has been closed")
        self.asked.append(refs)
        return [100.0 + i for i in range(len(refs) - 1)] + [-1.0 if self.missing else 100.0 + len(refs) - 1]


def test_each_block_is_measured_by_the_path_that_names_it_in_the_kept_document() -> None:
    page = _Page()

    areas = asyncio.run(item_areas(cast(Page, page), BODY))

    (group,) = item_groups(lxml_root(BODY.decode()))
    assert areas == {element_path(block): 100.0 + i for i, block in enumerate(group)}
    assert [tag for _, tag in page.asked[0]] == ["li"] * 4
