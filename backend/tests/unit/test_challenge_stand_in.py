"""Stand-in markers (D-1470, INV-24 amended): a 2xx HTML document that shows a vendor's stand-in marker is `blocked`
and labelled with that vendor; nothing else in the vendor data changes a block class. The markers come from the
adapter package's data, never from this file (C3)."""

import pytest

from crawlerai.acquire.challenge import block_class_of, challenge_label
from crawlerai.adapters.challenges import SIGNATURES, ChallengeSignature, stand_in_vendor

_HTML = (("content-type", "text/html"),)
_LINKS = "".join(f'<a href="/item/{i}">Item {i}</a>' for i in range(8))
_STAND_INS = [s for s in SIGNATURES if s.stand_in_markers]
URL = "https://shop.example.test/item/1"


def _page(extra: str = "") -> str:
    """A page with site structure: enough text and links to other pages of its host."""
    return f"<html><body><h1>Item</h1><p>{'word ' * 80}</p>{_LINKS}{extra}</body></html>"


@pytest.mark.parametrize("sig", _STAND_INS, ids=[s.vendor for s in _STAND_INS])
@pytest.mark.parametrize("status", [200, 202])
def test_a_2xx_page_showing_a_stand_in_marker_is_blocked_and_labelled(sig: ChallengeSignature, status: int) -> None:
    body = _page(f"<!-- {sig.stand_in_markers[0]} -->")

    assert block_class_of(status, _HTML, body) == "blocked"
    assert challenge_label(status, _HTML, body, URL) == sig.vendor


@pytest.mark.parametrize("signature", [s for s in SIGNATURES if s.cookie_prefixes or s.script_paths])
def test_cookies_and_script_paths_alone_never_block_a_2xx_page(signature: ChallengeSignature) -> None:
    # A vendor sets its cookies and loads its script on the pages it lets through too.
    scripts = "".join(f'<script src="https://cdn.example.test{path}x.js"></script>' for path in signature.script_paths)
    headers = (*_HTML, *(("set-cookie", f"{prefix}1=v") for prefix in signature.cookie_prefixes))

    assert stand_in_vendor(_page(scripts)) is None
    assert block_class_of(200, headers, _page(scripts)) == "ok"


@pytest.mark.parametrize("sig", _STAND_INS, ids=[s.vendor for s in _STAND_INS])
def test_usable_content_beats_a_stand_in_marker(sig: ChallengeSignature) -> None:
    # The marker needs corroboration: a document that carries the page's structured data is the page.
    price = '<meta property="product:price:amount" content="9.50">'
    assert block_class_of(200, _HTML, _page(f"<!-- {sig.stand_in_markers[0]} -->{price}")) == "ok"
