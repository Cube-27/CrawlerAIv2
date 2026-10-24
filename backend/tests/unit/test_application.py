"""A job page that holds its own application: an application form in its markup or a
platform's documented embed of one, never words on the page. The embed's names come from the adapter module (C3)."""

import pytest

from snowcrawl.adapters.greenhouse import APPLICATION_EMBED
from snowcrawl.collect.application import holds_application
from snowcrawl.content.page import ParsedPage

PAGE = "https://careers.example.com/jobs/7"
LOADER = f"https://{sorted(APPLICATION_EMBED.loader_hosts)[0]}{APPLICATION_EMBED.loader_path}?for=example"
EMBED = f'<div id="{APPLICATION_EMBED.container}"></div><script src="{LOADER}"></script>'
POSTING = f"{PAGE}?{APPLICATION_EMBED.posting_param}=123"


@pytest.mark.parametrize(
    ("html", "url", "holds"),
    [
        ('<form><input name="a" autocomplete="given-name"><input type="FILE" name="b"></form>', PAGE, True),
        ('<form><input type="email" name="a"><input type="file" name="b"></form>', PAGE, True),
        ('<form id="f"></form><input type="tel" form="f"><input type="file" form="f">', PAGE, True),
        # A sign-in form asks for no document; a file field without contact is no application.
        ('<form><input type="email" name="a"><input type="password" name="b"></form>', PAGE, False),
        ('<form><input type="file" name="b"></form>', PAGE, False),
        # Contact in one form and an upload in another are two forms.
        ('<form><input type="email"></form><form><input type="file"></form>', PAGE, False),
        ('<form id="g"></form><form><input type="email"><input type="file" form="g"></form>', PAGE, False),
        (EMBED, POSTING, True),
        (EMBED, PAGE, False),  # the board, not one posting
        (f'<div id="{APPLICATION_EMBED.container}"></div>', POSTING, False),
        (EMBED.replace("?for=example", ""), POSTING, False),  # a loader for no board
        ("<p>Apply on this page</p>", POSTING, False),
    ],
)
def test_a_page_holds_an_application_by_its_markup(html: str, url: str, holds: bool) -> None:
    assert holds_application(ParsedPage(html), url) is holds


def test_a_json_body_holds_no_application() -> None:
    page = ParsedPage('{"form": "<form><input type=email><input type=file></form>"}', json_body=True)

    assert holds_application(page, PAGE) is False
