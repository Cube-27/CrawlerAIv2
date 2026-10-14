"""The problems a job submission answers with (`POST /v1/batch/scrape`, `/v1/crawl`): the errors the services raise
before they store anything, as problem details (SPEC-07 §4.8)."""

from collections.abc import Iterator
from contextlib import contextmanager

from crawlerai.api.problems import ProblemError, conflict, invalid, records_unavailable
from crawlerai.services.fetching import TargetsRejected
from crawlerai.services.schemas import InvalidSchema, SchemaConflict
from crawlerai.services.scrape import RecordsUnavailable
from crawlerai.services.scrape_steps import SchemaUnusable


@contextmanager
def submission_problems() -> Iterator[None]:
    """Raise the submission's errors as problems: a refused target and an unusable schema are 422s, a conflicting
    inline schema a 409, and `records` without the engine's data a 503."""
    try:
        yield
    except TargetsRejected as e:
        # 422: the request names a target the API may not fetch (INV-16).
        raise ProblemError(422, "ssrf_rejected", "Target refused", str(e), [(e.member, e.reason)]) from e
    except SchemaUnusable as e:
        raise invalid(str(e), [("schema", str(e))]) from e
    except InvalidSchema as e:
        raise invalid(str(e), [(f"schema.inline.{field}".rstrip("."), reason) for field, reason in e.errors]) from e
    except SchemaConflict as e:
        raise conflict(str(e)) from e
    except RecordsUnavailable as e:
        raise records_unavailable(str(e)) from e
