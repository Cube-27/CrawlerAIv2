"""Contract suite for the `ObjectStore` backends (SPEC-01 §4.4, §6). Every backend runs the same tests; `s3` runs
against moto's in-process stub, never real credentials."""

from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from crawlerai.storage import open_store
from crawlerai.storage.base import ObjectNotFound, ObjectStore

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


def test_put_overwrites(store: ObjectStore) -> None:
    store.put("k", b"first")
    store.put("k", b"second")

    assert store.get("k") == b"second"


def test_get_of_missing_key_raises_object_not_found(store: ObjectStore) -> None:
    with pytest.raises(ObjectNotFound):
        store.get("captures/missing.bundle.zst")


def test_exists_reflects_put_and_delete(store: ObjectStore) -> None:
    assert store.exists("eval/dev/a.bundle.zst") is False

    store.put("eval/dev/a.bundle.zst", b"x")
    assert store.exists("eval/dev/a.bundle.zst") is True

    store.delete("eval/dev/a.bundle.zst")
    assert store.exists("eval/dev/a.bundle.zst") is False
    with pytest.raises(ObjectNotFound):
        store.get("eval/dev/a.bundle.zst")


def test_delete_of_missing_key_is_a_no_op(store: ObjectStore) -> None:
    store.delete("never/written")

    assert store.list("") == []


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


@pytest.mark.parametrize("key", ["", "/abs", "a//b", "a/", "../x", "a/../b", "a/./b", ".hidden", "a\\b", "a\x00b"])
def test_rejects_keys_that_are_not_relative_slash_separated_paths(store: ObjectStore, key: str) -> None:
    with pytest.raises(ValueError, match="object key"):
        store.put(key, b"x")
    with pytest.raises(ValueError, match="object key"):
        store.get(key)


def test_fs_store_writes_the_key_as_a_relative_path_under_its_root(tmp_path: Path) -> None:
    store = open_store(_fs_url(tmp_path))

    store.put("captures/2026/10/a.bundle.zst", b"payload")

    assert (tmp_path / "captures" / "2026" / "10" / "a.bundle.zst").read_bytes() == b"payload"


@pytest.mark.usefixtures("aws")
def test_s3_store_prepends_its_prefix_to_every_key() -> None:
    store = open_store(f"s3://{_BUCKET}/main/")

    store.put("captures/a", b"payload")

    body = boto3.client("s3").get_object(Bucket=_BUCKET, Key="main/captures/a")["Body"].read()
    assert body == b"payload"


@pytest.mark.usefixtures("aws")
def test_s3_stores_with_different_prefixes_in_one_bucket_do_not_see_each_other() -> None:
    main = open_store(f"s3://{_BUCKET}/main")
    private = open_store(f"s3://{_BUCKET}/main-private")
    main.put("eval/dev/a", b"main")
    private.put("eval/hidden/b", b"private")

    assert main.list("") == ["eval/dev/a"]
    assert private.list("") == ["eval/hidden/b"]
    assert main.exists("eval/hidden/b") is False


@pytest.mark.usefixtures("aws")
def test_s3_store_without_prefix_uses_the_bucket_root() -> None:
    store = open_store(f"s3://{_BUCKET}")

    store.put("captures/a", b"payload")

    assert boto3.client("s3").get_object(Bucket=_BUCKET, Key="captures/a")["Body"].read() == b"payload"
    assert store.list("") == ["captures/a"]


@pytest.mark.parametrize("url", ["file:///srv/objects", "s3:/bucket", "gs://bucket/prefix", "fs://relative"])
def test_open_store_rejects_urls_outside_the_settings_grammar(url: str) -> None:
    with pytest.raises(ValueError, match="object store URL"):
        open_store(url)
