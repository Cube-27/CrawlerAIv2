"""Verifying a completion webhook: `X-Snowcrawl-Signature: sha256=<hex>`, the HMAC-SHA256 (RFC 2104) of the request
body keyed with the UTF-8 bytes of the API key's webhook secret."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from snowcrawl_sdk.errors import SnowcrawlError
from snowcrawl_sdk.models import JobSummary

SIGNATURE_HEADER = "X-Snowcrawl-Signature"


class InvalidSignature(SnowcrawlError):
    """The body was not signed with the secret."""


def sign(secret: str, body: bytes) -> str:
    """The signature header's value for `body`."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    """Whether `signature` (the header's value) is `body`'s, compared in constant time."""
    if signature is None:
        return False
    # Bytes, not str: `compare_digest` raises TypeError on a str with non-ASCII characters, which any sender can put
    # in the header; surrogateescape keeps undecodable header bytes comparable instead of raising.
    return hmac.compare_digest(sign(secret, body).encode(), signature.encode("utf-8", "surrogateescape"))


def parse_webhook(secret: str, body: bytes, signature: str | None) -> JobSummary:
    """The job summary a verified webhook carries. Raises `InvalidSignature` for a body not signed with `secret`."""
    if not verify_signature(secret, body, signature):
        raise InvalidSignature("the webhook's signature does not match its body")
    payload: Any = json.loads(body)
    return JobSummary.model_validate(payload)
