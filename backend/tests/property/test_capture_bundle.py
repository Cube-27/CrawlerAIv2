"""Capture bundle format (SPEC-01 §4.5, ARCHITECTURE §15): encode/decode round-trips exactly (INV-10 relies on it)
and the archive layout is the documented one."""

import hashlib
import io
import json
import tarfile
import uuid
from datetime import UTC, datetime
from typing import get_args

import pytest
import zstandard
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.storage.capture_bundle import (
    CaptureBundle,
    CaptureManifest,
    CorruptBundle,
    Headers,
    NetworkBody,
    capture_key,
    decode,
    dev_eval_capture_key,
    encode,
)

_CAPTURE_ID = uuid.UUID("0192f0c8-7b1e-7000-8000-000000000001")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bundle(
    method: CaptureMethod = "browser",
    body: bytes = b"<html></html>",
    network: tuple[bytes, ...] = (),
    raw_body: bytes | None = None,
) -> CaptureBundle:
    return CaptureBundle(
        manifest=CaptureManifest(
            capture_id=_CAPTURE_ID,
            url="https://shop.example.test/p/1",
            final_url="https://shop.example.test/p/1?ref=x",
            fetched_at=datetime(2026, 10, 12, 8, 30, tzinfo=UTC),
            method=method,
            status_code=200,
            block_class="ok",
            headers=Headers(
                request=(("accept", "text/html"),), response=(("set-cookie", "a=1"), ("set-cookie", "b=2"))
            ),
            timings_ms={"total": 412},
            html_sha256=_sha(body),
            raw_html_sha256=None if raw_body is None else _sha(raw_body),
            network_bodies=tuple(
                NetworkBody(
                    url=f"https://api.example.test/{i}",
                    status=200,
                    content_type="application/json",
                    sha256=_sha(data),
                    file=f"network/{i + 1:04d}.json",
                )
                for i, data in enumerate(network)
            ),
            fetch_policy={"proxy": None, "robots_override": False},
            engine_version="0123abc+cal.feed",
        ),
        body=body,
        network=network,
        raw_body=raw_body,
    )


def _tar_zst(members: dict[str, bytes]) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return zstandard.ZstdCompressor().compress(raw.getvalue())


def _members(blob: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(zstandard.ZstdDecompressor().decompress(blob)), mode="r:") as tar:
        files = {m.name: tar.extractfile(m) for m in tar.getmembers()}
        return {name: file.read() for name, file in files.items() if file is not None}


_text = st.text(max_size=40)
_headers = st.lists(st.tuples(st.text(min_size=1, max_size=20), _text), max_size=6).map(tuple)
_json = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False, allow_infinity=False) | _text,
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(_text, inner, max_size=3),
    max_leaves=10,
)


@st.composite
def bundles(draw: st.DrawFn) -> CaptureBundle:
    method: CaptureMethod = draw(st.sampled_from(get_args(CaptureMethod)))
    body = draw(st.binary(max_size=2048))
    network = draw(st.lists(st.binary(max_size=256), max_size=4)) if method == "browser" else []
    raw_body = draw(st.none() | st.binary(max_size=512)) if method == "browser" else None
    manifest = CaptureManifest(
        capture_id=draw(st.uuids()),
        url=draw(_text),
        final_url=draw(_text),
        fetched_at=draw(st.datetimes(timezones=st.just(UTC))),
        method=method,
        status_code=draw(st.integers(100, 599)),
        block_class=draw(st.sampled_from(get_args(BlockClass))),
        headers=Headers(request=draw(_headers), response=draw(_headers)),
        timings_ms=draw(st.dictionaries(_text, st.integers(0, 10**7), max_size=4)),
        html_sha256=_sha(body),
        raw_html_sha256=None if raw_body is None else _sha(raw_body),
        network_bodies=tuple(
            NetworkBody(
                url=draw(_text),
                status=draw(st.integers(100, 599)),
                content_type=draw(st.none() | _text),
                sha256=_sha(data),
                file=f"network/{i + 1:04d}.json",
            )
            for i, data in enumerate(network)
        ),
        fetch_policy=draw(st.dictionaries(_text, _json, max_size=3)),
        engine_version=draw(_text),
    )
    return CaptureBundle(manifest=manifest, body=body, network=tuple(network), raw_body=raw_body)


@given(bundles())
def test_decode_inverts_encode(bundle: CaptureBundle) -> None:
    assert decode(encode(bundle)) == bundle


@given(bundles())
def test_encode_is_deterministic(bundle: CaptureBundle) -> None:
    assert encode(bundle) == encode(bundle.model_copy(deep=True))


def test_archive_holds_manifest_html_body_and_numbered_network_files_in_order() -> None:
    bundle = _bundle(network=(b'{"a":1}', b'{"b":2}'))

    members = _members(encode(bundle))

    assert list(members) == ["manifest.json", "body.html", "network/0001.json", "network/0002.json"]
    assert members["body.html"] == b"<html></html>"
    assert members["network/0002.json"] == b'{"b":2}'
    manifest = json.loads(members["manifest.json"])
    assert manifest["bundle_version"] == 1
    assert manifest["capture_id"] == str(_CAPTURE_ID)
    assert manifest["headers"]["response"] == [["set-cookie", "a=1"], ["set-cookie", "b=2"]]
    assert manifest["network_bodies"][1]["file"] == "network/0002.json"


def test_browser_capture_keeps_the_raw_navigation_body_beside_the_rendered_one() -> None:
    bundle = _bundle(body=b"<html>rendered</html>", raw_body=b"<html>raw</html>", network=(b"{}",))

    members = _members(encode(bundle))

    assert list(members) == ["manifest.json", "body.html", "body.raw.html", "network/0001.json"]
    assert members["body.html"] == b"<html>rendered</html>"
    assert members["body.raw.html"] == b"<html>raw</html>"
    assert json.loads(members["manifest.json"])["raw_html_sha256"] == _sha(b"<html>raw</html>")


def test_bundle_without_a_raw_body_has_no_raw_member() -> None:
    members = _members(encode(_bundle(method="http")))

    assert list(members) == ["manifest.json", "body.html"]
    assert json.loads(members["manifest.json"])["raw_html_sha256"] is None


def test_manifest_written_before_raw_bodies_existed_still_decodes() -> None:
    members = _members(encode(_bundle(method="http")))
    manifest = json.loads(members["manifest.json"])
    del manifest["raw_html_sha256"]
    members["manifest.json"] = json.dumps(manifest).encode()

    assert decode(_tar_zst(members)) == _bundle(method="http")


def test_bundle_rejects_a_raw_body_on_a_non_browser_capture() -> None:
    browser = _bundle(raw_body=b"<html>raw</html>")
    manifest = browser.manifest.model_copy(update={"method": "http"})

    with pytest.raises(ValidationError, match="raw body"):
        CaptureBundle(manifest=manifest, body=browser.body, network=(), raw_body=browser.raw_body)


def test_bundle_rejects_a_raw_body_that_does_not_match_raw_html_sha256() -> None:
    good = _bundle(raw_body=b"<html>raw</html>")

    with pytest.raises(ValidationError, match="raw_html_sha256"):
        CaptureBundle(manifest=good.manifest, body=good.body, network=(), raw_body=b"other")
    with pytest.raises(ValidationError, match="raw_html_sha256"):
        CaptureBundle(manifest=good.manifest, body=good.body, network=(), raw_body=None)


def test_decode_raises_corrupt_bundle_when_the_raw_body_is_missing() -> None:
    members = _members(encode(_bundle(raw_body=b"<html>raw</html>")))
    del members["body.raw.html"]
    blob = _tar_zst(members)

    with pytest.raises(CorruptBundle, match=r"body\.raw\.html"):
        decode(blob)


def test_api_capture_body_is_stored_as_body_json() -> None:
    assert list(_members(encode(_bundle(method="api", body=b"{}")))) == ["manifest.json", "body.json"]


def test_bundle_rejects_body_that_does_not_match_html_sha256() -> None:
    good = _bundle()

    with pytest.raises(ValidationError, match="html_sha256"):
        CaptureBundle(manifest=good.manifest, body=b"other", network=())


def test_bundle_rejects_network_bodies_that_do_not_match_the_manifest() -> None:
    good = _bundle(network=(b"{}",))

    with pytest.raises(ValidationError, match="network"):
        CaptureBundle(manifest=good.manifest, body=good.body, network=(b"[]",))
    with pytest.raises(ValidationError, match="network"):
        CaptureBundle(manifest=good.manifest, body=good.body, network=())


def test_bundle_rejects_network_file_names_out_of_sequence() -> None:
    good = _bundle(network=(b"{}",))
    entry = good.manifest.network_bodies[0].model_copy(update={"file": "network/0007.json"})
    manifest = good.manifest.model_copy(update={"network_bodies": (entry,)})

    with pytest.raises(ValidationError, match=r"network/0001\.json"):
        CaptureBundle.model_validate({"manifest": manifest.model_dump(), "body": good.body, "network": good.network})


@pytest.mark.parametrize(
    "blob",
    [
        pytest.param(b"not zstd", id="not-zstd"),
        pytest.param(zstandard.ZstdCompressor().compress(b"not a tar"), id="not-tar"),
        pytest.param(_tar_zst({"body.html": b""}), id="no-manifest"),
        pytest.param(_tar_zst({"manifest.json": b"{"}), id="manifest-not-json"),
    ],
)
def test_decode_raises_corrupt_bundle_for_malformed_archives(blob: bytes) -> None:
    with pytest.raises(CorruptBundle):
        decode(blob)


def test_decode_raises_corrupt_bundle_when_body_was_altered() -> None:
    members = _members(encode(_bundle()))
    members["body.html"] = b"<html>tampered</html>"

    with pytest.raises(CorruptBundle, match="html_sha256"):
        decode(_tar_zst(members))


def test_decode_raises_corrupt_bundle_for_unexpected_members() -> None:
    members = _members(encode(_bundle()))
    members["../escape"] = b""

    with pytest.raises(CorruptBundle, match="unexpected"):
        decode(_tar_zst(members))


def test_capture_keys_follow_the_documented_layout() -> None:
    fetched_at = datetime(2026, 3, 31, 23, 59, tzinfo=UTC)

    assert capture_key(_CAPTURE_ID, fetched_at) == f"captures/2026/03/{_CAPTURE_ID}.bundle.zst"
    assert dev_eval_capture_key(_CAPTURE_ID) == f"eval/dev/{_CAPTURE_ID}.bundle.zst"
