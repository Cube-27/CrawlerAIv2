"""A capture's artifacts (SPEC-02, SPEC-01 §4.4): files the browser made of the page it rendered, a screenshot and a
PDF, stored beside the capture's bundle under keys derived from the bundle's.

An artifact is not part of the bundle: the bundle holds what replay reads (INV-10), and an artifact is output only. It
lives and dies with its capture: `scheduler.retention` deletes the names below with the bundle.
"""

from typing import Final

from pydantic import BaseModel

from crawlerai.storage.base import ObjectStore
from crawlerai.storage.capture_bundle import CAPTURES_PREFIX

SCREENSHOT: Final = "screenshot.png"
PDF: Final = "page.pdf"
# Name to media type: a screenshot is a PNG (W3C PNG Third Edition, `image/png`), a print of the page a PDF
# (RFC 8118, `application/pdf`). The names are the only ones the API serves.
ARTIFACT_TYPES: Final = {SCREENSHOT: "image/png", PDF: "application/pdf"}
_BUNDLE_SUFFIX: Final = ".bundle.zst"


class Artifact(BaseModel):
    """A stored artifact as an answer names it: the URL the API serves it at, which needs the API's own key like any
    other route, and its media type."""

    url: str
    content_type: str


def artifact_key(bundle_key: str, name: str) -> str:
    """The object key of artifact `name` of the capture whose bundle is at `bundle_key`: `captures/Y/M/<id>.<name>`.
    Only production captures (under `captures/`) have artifacts."""
    if (
        name not in ARTIFACT_TYPES
        or not bundle_key.startswith(CAPTURES_PREFIX)
        or not bundle_key.endswith(_BUNDLE_SUFFIX)
    ):
        raise ValueError(f"no artifact {name!r} for bundle key {bundle_key!r}")
    return f"{bundle_key.removesuffix(_BUNDLE_SUFFIX)}.{name}"


def artifact_url(capture_id: object, name: str) -> str:
    return f"/v1/captures/{capture_id}/artifacts/{name}"


def artifact_of(capture_id: object, name: str) -> Artifact:
    return Artifact(url=artifact_url(capture_id, name), content_type=ARTIFACT_TYPES[name])


def stored_names(store: ObjectStore, bundle_key: str) -> frozenset[str]:
    """The names of the artifacts stored for the capture whose bundle is at `bundle_key`; none for a bundle that cannot
    have any (an eval capture's)."""
    if not bundle_key.startswith(CAPTURES_PREFIX):
        return frozenset()
    return frozenset(name for name in ARTIFACT_TYPES if store.exists(artifact_key(bundle_key, name)))
