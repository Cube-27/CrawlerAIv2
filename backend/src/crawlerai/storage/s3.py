"""S3 `ObjectStore` (SPEC-01 §4.4). Any S3-compatible service works: boto3 reads credentials, region and
`AWS_ENDPOINT_URL` from its standard environment and config files, so the app adds no settings of its own.

Lifecycle rules may be configured on the bucket, but the app does not manage them; `expire_captures` enforces
expiry (SPEC-01 §4.4).
"""

import builtins
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError

from crawlerai.storage.base import ObjectNotFound, check_key

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client  # stubs are a dev dependency

# S3 error codes for an absent key: GetObject reports `NoSuchKey`; HeadObject has no body, so only the HTTP status.
_MISSING = {"NoSuchKey", "404"}


class S3Store:
    def __init__(self, client: "S3Client", bucket: str, prefix: str) -> None:
        """`prefix` is prepended to every key; `""` or a path ending in `/`."""
        self._client = client
        self._bucket = bucket
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return self._prefix + check_key(key)

    def put(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=self._key(key), Body=data)

    def get(self, key: str) -> bytes:
        try:
            return self._client.get_object(Bucket=self._bucket, Key=self._key(key))["Body"].read()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in _MISSING:
                raise ObjectNotFound(key) from None
            raise

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=self._key(key))
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in _MISSING:
                return False
            raise
        return True

    def delete(self, key: str) -> None:
        # DeleteObject succeeds for a missing key, which gives the protocol's no-op.
        self._client.delete_object(Bucket=self._bucket, Key=self._key(key))

    def list(self, prefix: str) -> builtins.list[str]:
        pages = self._client.get_paginator("list_objects_v2").paginate(
            Bucket=self._bucket, Prefix=self._prefix + prefix
        )
        # ListObjectsV2 returns keys in ascending UTF-8 binary order, which is Python's str order.
        return [obj["Key"].removeprefix(self._prefix) for page in pages for obj in page.get("Contents", [])]
