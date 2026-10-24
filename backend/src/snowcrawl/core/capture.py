"""The capture enumerations of shared by the `capture` table and the capture bundle."""

from typing import Literal

CaptureMethod = Literal["http", "browser", "api"]
# The transport outcome of a fetch: the page, a refusal, a
# document without the page, the page's absence, a failure; where a 401 or a redirect left the fetch instead; and a 2xx
# answer that is no HTML document (`unsupported_media`).
BlockClass = Literal[
    "ok",
    "blocked",
    "shell",
    "not_found",
    "error",
    "auth_wall",
    "soft_404",
    "geo_redirect",
    "redirected_to_listing",
    "unsupported_media",
]
