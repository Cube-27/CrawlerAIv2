"""A job's crawl location: the one proxy pool every fetch of the job goes
through, and the egress country that gives records (`core.egress`).

A site may price by the visitor's country, so a job's pages must all be fetched from one place: the request's
`fetch.proxy_pool`, else none (a direct fetch). The request is stored with the job, and its workers read the pool from
it.
"""

from crawlerai.core.egress import Egress, Egresses
from crawlerai.services.fetch_options import FetchOptions

__all__ = ["job_egress"]


def job_egress(egresses: Egresses | None, fetch: FetchOptions) -> Egress:
    """The egress the job's pool gives (`egresses`; none known: unknown)."""
    return (egresses or Egresses()).of(fetch.proxy_pool)
