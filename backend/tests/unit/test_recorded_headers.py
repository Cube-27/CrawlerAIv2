"""The headers a capture records (`acquire.headers.recorded`): the header fields sent or received, in order."""

from crawlerai.acquire.headers import recorded


def test_a_capture_records_header_fields_but_no_credentials_or_pseudo_headers() -> None:
    sent = (
        (":method", "GET"),
        (":authority", "shop.example.test"),
        ("accept", "application/json"),
        ("Cookie", "a=b"),
        (":path", "/items"),
        ("X-Requested-With", "fetch"),
        ("authorization", "Bearer c"),
    )
    assert recorded(sent) == (("accept", "application/json"), ("X-Requested-With", "fetch"))
