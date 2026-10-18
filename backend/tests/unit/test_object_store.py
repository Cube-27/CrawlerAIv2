"""Contract suite for the `ObjectStore` backends (SPEC-01 §4.4, §6). Every backend runs the same tests; `s3` runs
against moto's in-process stub, never real credentials."""

from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from crawlerai.storage import open_store
from crawlerai.storage.base import ObjectStore

_BUCKET = "objects"


def _fs_url(path: Path) -> str:
    return path.as_uri().replace("file:", "fs:", 1)


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=_BUCKET)
        yield


@pytest.fixture(params=["fs", "s3"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> ObjectStore:
    if request.param == "fs":
        return open_store(_fs_url(tmp_path))
    request.getfixturevalue("aws")
    return open_store(f"s3://{_BUCKET}/main")


def test_get_returns_the_bytes_put(store: ObjectStore) -> None:
    store.put("captures/2026/10/a.bundle.zst", b"\x00\x01payload")

    assert store.get("captures/2026/10/a.bundle.zst") == b"\x00\x01payload"


def test_list_matches_keys_by_string_prefix_in_sorted_order(store: ObjectStore) -> None:
    for key in ["eval/dev/b", "captures/2026/10/b", "captures/2026/09/a", "captures/2025/12/c", "captures2/x"]:
        store.put(key, b"")

    assert store.list("captures/2026") == ["captures/2026/09/a", "captures/2026/10/b"]
    assert store.list("captures/") == ["captures/2025/12/c", "captures/2026/09/a", "captures/2026/10/b"]
    assert store.list("eval/") == ["eval/dev/b"]
    assert store.list("") == [
        "captures/2025/12/c",
        "captures/2026/09/a",
        "captures/2026/10/b",
        "captures2/x",
        "eval/dev/b",
    ]
    assert store.list("nothing/") == []


# One per refused class: an empty segment, a segment starting with `.`, a backslash, a NUL.
@pytest.mark.parametrize("key", ["/abs", "../x", "a\\b", "a\x00b"])
def test_rejects_keys_that_are_not_relative_slash_separated_paths(store: ObjectStore, key: str) -> None:
    with pytest.raises(ValueError, match="object key"):
        store.put(key, b"x")
    with pytest.raises(ValueError, match="object key"):
        store.get(key)


@pytest.mark.usefixtures("aws")
def test_s3_store_prepends_its_prefix_to_every_key() -> None:
    store = open_store(f"s3://{_BUCKET}/main/")

    store.put("captures/a", b"payload")

    body = boto3.client("s3").get_object(Bucket=_BUCKET, Key="main/captures/a")["Body"].read()
    assert body == b"payload"
