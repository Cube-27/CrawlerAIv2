"""A capture as an HTTP Archive (HAR 1.2, W3C Web Performance WG draft "HTTP Archive (HAR) format"): the page's
document and each call the capture kept, in capture order, for the engineer's own tools.

The archive holds what the bundle holds and nothing else: headers as the capture recorded them, so without cookies
(`acquire.headers.recorded`) and with the values of the caller's own headers masked (`acquire.outcome`); no cookie
lists. What the bundle does not keep is written as HAR says an unknown is: `-1` for a size or a timing that may be
unknown, the empty string for the HTTP version, and 0 for the timings that must be known (`send`, `wait`, `receive`).
Every entry starts when the page's fetch started (`fetched_at`): a call's own start is not kept.
"""

import base64
from collections.abc import Sequence
from typing import Final
from urllib.parse import parse_qsl, urlsplit

from pydantic import JsonValue

from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.storage.capture_bundle import CaptureBundle, HeaderList

__all__ = ["HAR_VERSION", "har"]

HAR_VERSION: Final = "1.2"
_CREATOR: Final = "CrawlerAI"
_PAGE: Final = "page_1"
# HAR 1.2 `content.encoding`: a body that is not UTF-8 text is written in base64.
_BASE64: Final = "base64"


def har(bundle: CaptureBundle) -> dict[str, JsonValue]:
    """The capture `bundle` as a HAR 1.2 log (module docstring)."""
    manifest = bundle.manifest
    started = manifest.fetched_at.isoformat()
    document = _entry(
        started,
        method="GET",
        url=manifest.final_url,
        request_headers=manifest.headers.request,
        request_body=None,
        status=manifest.status_code,
        response_headers=manifest.headers.response,
        content_type=_header(manifest.headers.response, "content-type"),
        answer=bundle.raw_body if bundle.raw_body is not None else bundle.body,
    )
    calls = [
        _entry(
            started,
            method=entry.method or "GET",
            url=entry.url,
            request_headers=entry.request_headers or (),
            request_body=entry.request_body,
            status=entry.status,
            response_headers=entry.response_headers or (),
            content_type=entry.content_type,
            answer=data,
        )
        for entry, data in zip(manifest.network_bodies, bundle.network, strict=True)
    ]
    page: dict[str, JsonValue] = {
        "startedDateTime": started,
        "id": _PAGE,
        "title": manifest.url,
        "pageTimings": {"onContentLoad": -1, "onLoad": -1},
    }
    log: dict[str, JsonValue] = {
        "version": HAR_VERSION,
        "creator": {"name": _CREATOR, "version": ENGINE_VERSION},
        "pages": [page],
        "entries": [document, *calls],
    }
    return {"log": log}


def _entry(
    started: str,
    *,
    method: str,
    url: str,
    request_headers: HeaderList,
    request_body: str | None,
    status: int,
    response_headers: HeaderList,
    content_type: str | None,
    answer: bytes,
) -> JsonValue:
    request: dict[str, JsonValue] = {
        "method": method,
        "url": url,
        "httpVersion": "",
        "cookies": [],
        "headers": _headers(request_headers),
        "queryString": [{"name": name, "value": value} for name, value in parse_qsl(urlsplit(url).query, True)],
        "headersSize": -1,
        "bodySize": -1 if request_body is None else len(request_body.encode()),
    }
    if request_body is not None:
        mime = _header(request_headers, "content-type") or ""
        request["postData"] = {"mimeType": mime, "text": request_body}
    return {
        "pageref": _PAGE,
        "startedDateTime": started,
        "time": 0,
        "request": request,
        "response": {
            "status": status,
            "statusText": "",
            "httpVersion": "",
            "cookies": [],
            "headers": _headers(response_headers),
            "content": _content(answer, content_type),
            "redirectURL": _header(response_headers, "location") or "",
            "headersSize": -1,
            "bodySize": -1,
        },
        "cache": {},
        "timings": {"send": 0, "wait": 0, "receive": 0},
    }


def _content(answer: bytes, content_type: str | None) -> JsonValue:
    """HAR 1.2 `content`: the answer as text, or in base64 when it is not UTF-8."""
    content: dict[str, JsonValue] = {"size": len(answer), "mimeType": content_type or ""}
    try:
        content["text"] = answer.decode("utf-8")
    except UnicodeDecodeError:
        content["text"] = base64.b64encode(answer).decode("ascii")
        content["encoding"] = _BASE64
    return content


def _headers(headers: Sequence[tuple[str, str]]) -> list[JsonValue]:
    return [{"name": name, "value": value} for name, value in headers]


def _header(headers: Sequence[tuple[str, str]], name: str) -> str | None:
    """The last value of header `name` (RFC 9110 §5.1: names compare case-insensitively)."""
    values = [value for header, value in headers if header.lower() == name]
    return values[-1] if values else None
