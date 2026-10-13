"""The `markdown` content format (SPEC-07 §4.5, ARCHITECTURE §8.5): the page's main content, by trafilatura.

trafilatura reads the page's lxml tree, not the body, so the capture is parsed once (INV-26), and copies the tree
before it prunes it, so the shared tree stays as parsed. No per-site rules (C2). A browser capture's body is the
rendered DOM, so the same call covers both rungs.
"""

import trafilatura

from crawlerai.content.page import ParsedPage


def markdown(page: ParsedPage) -> str:
    """The main content as Markdown, with its links and images; `""` when trafilatura finds none."""
    extracted = trafilatura.extract(
        page.lxml_tree,
        output_format="markdown",
        include_links=True,
        include_images=True,
        favor_precision=True,
    )
    return extracted or ""
