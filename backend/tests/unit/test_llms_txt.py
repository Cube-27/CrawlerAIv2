"""`llms.txt` and `llms-full.txt` (`content.llms`, llmstxt.org): the opening, the sections and the links."""

from crawlerai.content.llms import LlmsPage, llms_full_txt, llms_txt

PAGES = [
    LlmsPage("https://docs.example.test/guide/", "Guide home", "How to use it.\nIn short."),
    LlmsPage("https://docs.example.test/guide/install", "Install"),
    LlmsPage("https://docs.example.test/guide/api/users", "Users [v2]", "List users."),
    LlmsPage("https://docs.example.test/guide/api/orders-and-carts"),
    LlmsPage("https://docs.example.test/guide/api/overview.html", None, None),
]


def test_llms_txt_has_an_h1_a_blockquote_and_sections_of_links_in_page_order() -> None:
    assert llms_txt(PAGES) == (
        "# Guide home\n\n"
        "> How to use it. In short.\n\n"
        "## Pages\n\n"
        "- [Guide home](https://docs.example.test/guide/): How to use it. In short.\n"
        "- [Install](https://docs.example.test/guide/install)\n\n"
        "## Api\n\n"
        "- [Users \\[v2\\]](https://docs.example.test/guide/api/users): List users.\n"
        "- [orders-and-carts](https://docs.example.test/guide/api/orders-and-carts)\n"
        "- [overview.html](https://docs.example.test/guide/api/overview.html)\n"
    )


def test_the_site_is_named_by_its_host_when_the_first_page_has_no_title() -> None:
    assert llms_txt([LlmsPage("https://docs.example.test/a")]).startswith("# docs.example.test\n")


def test_a_site_page_names_the_site_and_summarizes_it_beside_the_listed_urls() -> None:
    text = llms_txt([LlmsPage("https://docs.example.test/a")], LlmsPage("https://docs.example.test/", "Docs", "All."))
    assert text.startswith("# Docs\n\n> All.\n")
    assert "- [a](https://docs.example.test/a)" in text


def test_no_pages_give_the_h1_alone() -> None:
    assert llms_txt([]) == "# Site\n"


def test_llms_full_txt_follows_the_opening_with_each_page_under_its_name() -> None:
    text = llms_full_txt(PAGES[:2], ["# Guide\n\nHello.", ""])
    assert text == (
        "# Guide home\n\n> How to use it. In short.\n\n"
        "## Guide home\n\nSource: https://docs.example.test/guide/\n\n# Guide\n\nHello.\n\n"
        "## Install\n\nSource: https://docs.example.test/guide/install\n"
    )
