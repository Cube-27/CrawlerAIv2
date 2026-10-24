"""`snowcrawl jobs summary|reextract`: a job's outcomes from what it stored, and its
captures extracted again offline. One JSON document each, on stdout."""

import argparse
import asyncio
import sys
import uuid

from sqlalchemy.ext.asyncio import create_async_engine

from snowcrawl.acquire.rungs import adapter_registry
from snowcrawl.core.settings import DatabaseSettings, Settings
from snowcrawl.db.models import JobId
from snowcrawl.services.job_outcomes import job_outcomes
from snowcrawl.services.jobs import JobNotFound
from snowcrawl.services.reextract import reextract_job
from snowcrawl.services.runtime import load_engine_data
from snowcrawl.storage import open_store


async def _summary(job_id: JobId) -> str:
    engine = create_async_engine(DatabaseSettings().database_url.get_secret_value())
    try:
        async with engine.connect() as conn:
            return (await job_outcomes(conn, job_id)).model_dump_json(indent=2)
    finally:
        await engine.dispose()


async def _reextract(job_id: JobId) -> str:
    """The job's captures through the current engine: they and the database are read, no page is fetched and no LLM
    is called."""
    settings = Settings()
    data = load_engine_data(adapter_registry(settings.disabled_adapters))
    if data is None:
        raise SystemExit("snowcrawl jobs reextract: the engine's data files are missing: run `snowcrawl data fetch`")
    engine = create_async_engine(settings.database_url.get_secret_value())
    try:

        def progress(done: int, total: int) -> None:
            print(f"{done}/{total} captures", file=sys.stderr)

        result = await reextract_job(engine, open_store(settings.object_store), data, job_id, progress)
    finally:
        await engine.dispose()
    return result.model_dump_json(indent=2)


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    run = _summary if args.jobs_command == "summary" else _reextract
    try:
        print(asyncio.run(run(JobId(args.id))))
    except JobNotFound as e:
        parser.exit(2, f"snowcrawl jobs {args.jobs_command}: {e}\n")


def add_job_commands(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    jobs = commands.add_parser("jobs", help="a job's outcomes, and its stored captures extracted again").add_subparsers(
        dest="jobs_command", required=True
    )
    summary = jobs.add_parser("summary", help="the job's pages by outcome and its fields by status, as stored")
    reextract = jobs.add_parser(
        "reextract",
        help="extract the job's stored captures again with the current engine (no network, no LLM, nothing "
        "stored) and print the fields' statuses beside the stored ones",
    )
    for command in (summary, reextract):
        command.set_defaults(handler=_run)
        command.add_argument("id", type=uuid.UUID, help="the job's id (a batch is a job)")
