"""Bearer authentication with a rate limit in front of it. The limit is taken before
any database lookup, keyed by the key's hash so that unknown keys are limited too, or by the client's address when
the request carries no key."""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from snowcrawl.api.forwarded import Network, client_address
from snowcrawl.api.problems import ProblemError
from snowcrawl.api.runtime import database, runtime
from snowcrawl.db.keys import authenticate, hash_key
from snowcrawl.db.models import ApiKeyId
from snowcrawl.services.runtime import Caller

_BEARER = "bearer"  # the auth scheme is case-insensitive (RFC 9110 §11.1)


@dataclass
class _Bucket:
    tokens: float
    at: float


class RateLimiter:
    """In-process token buckets (one per API process): `burst` requests at once, refilled at `rate`
    per second."""

    def __init__(self, rate: float, burst: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._rate = rate
        self._burst = burst
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._pruned_at = clock()

    def __len__(self) -> int:
        return len(self._buckets)

    def take(self, key: str) -> float | None:
        """Take a token from `key`'s bucket: None when there was one, else the seconds until there is."""
        now = self._clock()
        self._prune(now)
        bucket = self._buckets.get(key)
        tokens = self._burst if bucket is None else min(self._burst, bucket.tokens + (now - bucket.at) * self._rate)
        if tokens < 1:
            self._buckets[key] = _Bucket(tokens, now)
            return (1 - tokens) / self._rate
        self._buckets[key] = _Bucket(tokens - 1, now)
        return None

    def _prune(self, now: float) -> None:
        """Drop the buckets that have refilled: a full bucket is the same as none, so memory follows the keys seen
        in the last refill period, not every key ever sent."""
        refill_s = self._burst / self._rate
        if now - self._pruned_at < refill_s:
            return
        self._pruned_at = now
        self._buckets = {key: bucket for key, bucket in self._buckets.items() if now - bucket.at < refill_s}


def _unauthorized(detail: str) -> ProblemError:
    # RFC 6750 §3: a 401 names the scheme the resource accepts.
    return ProblemError(401, "unauthorized", "Unauthorized", detail, headers={"WWW-Authenticate": "Bearer"})


def _bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    return token if scheme.lower() == _BEARER and token else None


def _bucket_key(request: Request, token: str | None) -> str:
    if token is not None:
        return "key:" + hash_key(token)[:16]
    proxies: tuple[Network, ...] = request.app.state.trusted_proxies
    peer = request.client.host if request.client else None
    return "client:" + client_address(peer, request.headers.items(), proxies)


# Declares the bearer scheme (RFC 6750) in the OpenAPI document of every route that depends on `require_api_key`. It
# never refuses a request (`auto_error=False`): `require_api_key` parses the header and answers with its problems.
_DECLARED_BEARER = HTTPBearer(auto_error=False)


async def require_api_key(
    request: Request, _declared: Annotated[HTTPAuthorizationCredentials | None, Depends(_DECLARED_BEARER)] = None
) -> ApiKeyId:
    """The dependency of every authenticated route: the id of the request's API key."""
    token = _bearer_token(request)
    limiter: RateLimiter = request.app.state.rate_limiter
    wait_s = limiter.take(_bucket_key(request, token))
    if wait_s is not None:
        # Retry-After is whole seconds (RFC 9110 §10.2.3), rounded up so that a retry finds a token.
        retry_after = {"Retry-After": str(max(1, math.ceil(wait_s)))}
        raise ProblemError(429, "rate_limited", "Too many requests", "the rate limit is exceeded", headers=retry_after)
    if token is None:
        raise _unauthorized("the request has no bearer API key")
    engine = database(request)
    async with engine.begin() as conn:
        key_id = await authenticate(conn, hash_key(token))
    if key_id is None:
        raise _unauthorized("the API key is unknown or revoked")
    return key_id


def caller(request: Request, key: Annotated[ApiKeyId, Depends(require_api_key)]) -> Caller:
    """The dependency of a route that calls the services as its key: an LLM call no job pays for counts against the
    key's draft cap, as over MCP."""
    return Caller.of(runtime(request), key)
