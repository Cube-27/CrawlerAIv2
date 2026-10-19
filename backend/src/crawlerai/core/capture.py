"""The capture enumerations of shared by the `capture` table and the capture bundle."""

from typing import Literal

CaptureMethod = Literal["http", "browser", "api"]
# The transport outcome of a fetch (acquisition spec, "Structural outcome classification"): the page, a refusal, a
# document without the page, the page's absence, a failure; and where a 401 or a redirect left the fetch instead.
BlockClass = Literal[
    "ok", "blocked", "shell", "not_found", "error", "auth_wall", "soft_404", "geo_redirect", "redirected_to_listing"
]
