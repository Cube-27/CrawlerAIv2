"""The browser's request blocking (`acquire.blocklist`, acquisition spec "HTTP and browser rungs"): a listed server and
its subdomains are blocked, a third-party server only from another site's document, a type-limited one only for those
types, and neither an anti-bot vendor's resource nor the main frame's navigation ever is, whatever the lists say."""

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.blocklist import Blocklist, blocked_request
from crawlerai.adapters.challenges import SIGNATURES

_LABEL = st.from_regex(r"[a-z][a-z0-9]{0,8}", fullmatch=True)
_TYPES = st.sampled_from(["script", "xhr", "fetch", "document", "stylesheet", "image", "ping", "other"])
_BY_TYPE = frozenset({"image", "ping"})  # blocked by resource type alone, wherever they go
_PAGE = "https://shop.example.com/item"
_VENDOR_PATHS = [path for signature in SIGNATURES for path in signature.script_paths]


@given(_LABEL, st.lists(_LABEL, max_size=2), _TYPES)
def test_a_listed_server_is_blocked_as_its_rule_says(name: str, sub: list[str], kind: str) -> None:
    lists = Blocklist.parse(
        f"! a comment\n||{name}.example.net^\n||{name}.example.org^$third-party\n"
        f"||{name}.example.edu^$script,xmlhttprequest,third-party\n||x.test/path\n||y.test^$domain=a.test\n"
    )
    host = ".".join([*sub, name])

    assert blocked_request(f"https://{host}.example.net/a", kind, _PAGE, navigation=False, blocklist=lists)
    third = f"https://{host}.example.org/a"
    assert blocked_request(third, kind, _PAGE, navigation=False, blocklist=lists)
    # From a document on the third-party server's own site it is first-party: only the resource type may block it.
    own = f"https://www.{name}.example.org/"
    assert blocked_request(third, kind, own, navigation=False, blocklist=lists) == (kind in _BY_TYPE)
    typed = blocked_request(f"https://{host}.example.edu/a", kind, _PAGE, navigation=False, blocklist=lists)
    assert typed == (kind in _BY_TYPE | {"script", "xhr", "fetch"})
    # A line with a path or an option not read blocks nothing.
    for unread in ("https://x.test/path", "https://y.test/"):
        assert blocked_request(unread, kind, _PAGE, navigation=False, blocklist=lists) == (kind in _BY_TYPE)


@given(st.sampled_from(_VENDOR_PATHS), _TYPES, st.booleans())
def test_an_anti_bot_resource_and_the_main_navigation_are_never_blocked(path: str, kind: str, navigation: bool) -> None:
    # A vendor's script path names its host, or a path on the page's own host.
    url = f"https://shop.example.com{path}" if path.startswith("/") else f"https://{path}/s.js"
    lists = Blocklist.parse(f"||{path.strip('/')}^\n||example.com^\n")

    assert not blocked_request(url, kind, _PAGE, navigation=navigation, blocklist=lists)
    assert not blocked_request("https://ads.example.com/", "document", None, navigation=True, blocklist=lists)
