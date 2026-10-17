"""Verifying a completion webhook: `X-CrawlerAI-Signature: sha256=<hex>`, the HMAC-SHA256 (RFC 2104) of the request
body keyed with the UTF-8 bytes of the API key's webhook secret."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from crawlerai_sdk.errors import CrawlerAIError
from crawlerai_sdk.models import JobSummary

SIGNATURE_HEADER = "X-CrawlerAI-Signature"


class InvalidSignature(CrawlerAIError):
    """The body was not signed with the secret."""


def sign(secret: str, body: bytes) -> str:
    """The signature header's value for `body`."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    """Whether `signature` (the header's value) is `body`'s, compared in constant time."""
    return signature is not None and hmac.compare_digest(sign(secret, body), signature)


def parse_webhook(secret: str, body: bytes, signature: str | None) -> JobSummary:
    """The job summary a verified webhook carries. Raises `InvalidSignature` for a body not signed with `secret`."""
    if not verify_signature(secret, body, signature):
        raise InvalidSignature("the webhook's signature does not match its body")
    payload: Any = json.loads(body)
    return JobSummary.model_validate(payload)
