"""`GET /v1/jobs/{id}/request`: the request a job was submitted with, validated again by its kind's request model, so
the playground and the SDKs read it typed and a renamed member fails here rather than reading as empty."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from snowcrawl.db.models import Job, JobId
from snowcrawl.services.batch import BatchScrapeRequest
from snowcrawl.services.crawl import CrawlRequest
from snowcrawl.services.extract import ExtractRequest
from snowcrawl.services.jobs import JobNotFound
from snowcrawl.services.map import MapRequest
from snowcrawl.services.scrape import ScrapeRequest


class _Stored(BaseModel):
    model_config = ConfigDict(frozen=True)


class StoredScrape(_Stored):
    kind: Literal["scrape"]
    request: ScrapeRequest


class StoredBatchScrape(_Stored):
    kind: Literal["batch_scrape"]
    request: BatchScrapeRequest


class StoredMap(_Stored):
    kind: Literal["map"]
    request: MapRequest


class StoredCrawl(_Stored):
    kind: Literal["crawl"]
    request: CrawlRequest


class StoredExtract(_Stored):
    kind: Literal["extract"]
    request: ExtractRequest


# A `learn` job is started by the system, not submitted with a request: it has none to show.
StoredJobRequest = Annotated[
    StoredScrape | StoredBatchScrape | StoredMap | StoredCrawl | StoredExtract, Field(discriminator="kind")
]


class _AnyStored(RootModel[StoredJobRequest]):
    pass


async def job_request(conn: AsyncConnection, job_id: JobId) -> StoredJobRequest:
    """The request the job was submitted with (`job.request`), with its kind; its `fetch` secrets serialize redacted
    (`FetchOptions`). `JobNotFound` for no job, or a `learn` job."""
    job = (await conn.execute(select(Job.kind, Job.request).where(Job.id == job_id))).one_or_none()
    if job is None:
        raise JobNotFound(f"no job {job_id}")
    if job.kind == "learn":
        raise JobNotFound(f"job {job_id} is a learn job: it was not submitted with a request")
    return _AnyStored.model_validate({"kind": job.kind, "request": job.request}).root
