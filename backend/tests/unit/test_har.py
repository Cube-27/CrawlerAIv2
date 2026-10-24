"""A capture as a HAR 1.2 log (`services.har`): the page's document, then each kept call in capture order, with the
members HAR 1.2 requires, the headers as the capture recorded them, and a body that is not UTF-8 in base64."""

import json
from typing import Any

from snowcrawl.services.har import har
from tests.support.captures import PAGE_URL, call, capture

_ITEMS = b'{"items": [{"name": "First item"}]}'
_PIXEL = b"\x89PNG\r\n\x1a\n\xff"


def test_a_capture_is_a_har_log_of_its_document_and_its_calls() -> None:
    form = (("Content-Type", "application/x-www-form-urlencoded"), ("X-Token", "**********"))
    bundle = capture(
        b"<html><body>page</body></html>",
        method="browser",
        request_headers=(("Accept", "text/html"),),
        network=(
            call(0, "https://shop.example.test/api/items?page=2&sort=new", _ITEMS, method="GET"),
            call(
                1,
                "https://api.example.net/submit",
                _PIXEL,
                content_type="image/png",
                method="POST",
                request_body="q=shoes",
                request_headers=form,
            ),
        ),
    )

    log: Any = json.loads(json.dumps(har(bundle)))["log"]  # a JSON document

    assert log["version"] == "1.2"
    entries = log["entries"]
    assert [(e["request"]["method"], e["request"]["url"]) for e in entries] == [
        ("GET", PAGE_URL),
        ("GET", "https://shop.example.test/api/items?page=2&sort=new"),
        ("POST", "https://api.example.net/submit"),
    ]
    items, submitted = entries[1], entries[2]
    assert items["request"]["queryString"] == [
        {"name": "page", "value": "2"},
        {"name": "sort", "value": "new"},
    ]
    assert items["response"]["content"] == {
        "size": len(_ITEMS),
        "mimeType": "application/json",
        "text": _ITEMS.decode(),
    }
    assert submitted["request"]["postData"] == {
        "mimeType": "application/x-www-form-urlencoded",
        "text": "q=shoes",
    }
    assert {"name": "X-Token", "value": "**********"} in submitted["request"]["headers"]
    assert submitted["response"]["content"]["encoding"] == "base64"
    for entry in entries:
        assert {"startedDateTime", "time", "request", "response", "cache", "timings"} <= entry.keys()
        assert entry["request"]["cookies"] == entry["response"]["cookies"] == []


def test_a_page_a_step_submitted_a_form_to_is_its_document_posted_once() -> None:
    form = (("Content-Type", "application/x-www-form-urlencoded"),)
    answer = b"<html><body>results</body></html>"
    bundle = capture(
        answer,
        method="browser",
        network=(
            call(
                0,
                PAGE_URL,
                answer,
                content_type="text/html",
                method="POST",
                resource_type="document",
                request_body="q=shoes",
                request_headers=form,
                action=1,
            ),
        ),
    )

    entries: Any = json.loads(json.dumps(har(bundle)))["log"]["entries"]

    assert [(e["request"]["method"], e["request"]["url"]) for e in entries] == [("POST", PAGE_URL)]
    assert entries[0]["request"]["postData"]["text"] == "q=shoes"
