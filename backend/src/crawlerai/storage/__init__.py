"""Object storage for captures. `open_store` turns a `CRAWLERAI_*OBJECT_STORE` URL into a
backend."""

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from crawlerai.core.settings import OBJECT_STORE_URL_PATTERN
from crawlerai.storage.base import ObjectStore
from crawlerai.storage.fs import FsStore


def open_store(url: str) -> ObjectStore:
    """`fs:///<absolute path>` or `s3://<bucket>[/<prefix>]`, the settings grammar."""
    if not re.fullmatch(OBJECT_STORE_URL_PATTERN, url):
        raise ValueError(
            f"invalid object store URL {url!r}: expected fs:///<absolute path> or s3://<bucket>[/<prefix>]"
        )
    parts = urlsplit(url)
    if parts.scheme == "fs":
        # url2pathname maps `/C:/x` to `C:\x` on Windows and leaves POSIX paths as they are.
        return FsStore(Path(url2pathname(parts.path)))
    # Imported here so that importing `crawlerai.storage.*` (e.g. the bundle codec in replay) doesn't load botocore.
    import boto3

    from crawlerai.storage.s3 import S3Store

    prefix = unquote(parts.path).strip("/")
    return S3Store(boto3.client("s3"), parts.netloc, prefix + "/" if prefix else "")
