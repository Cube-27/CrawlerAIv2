"""Search, crawl best-first, and follow the jobs: run with SNOWCRAWL_API_KEY (and SNOWCRAWL_URL) set."""

import os

from snowcrawl_sdk import APIError, Snowcrawl

with Snowcrawl(os.environ["SNOWCRAWL_API_KEY"], os.environ.get("SNOWCRAWL_URL", "http://localhost:8000")) as client:
    # Search the web, and scrape the results in a batch job.
    try:
        found = client.search(query="python asyncio event loop", limit=3, scrape={"formats": ["markdown"]})
    except APIError as error:
        if error.type != "search_unavailable":
            raise
        print("no search provider is configured on this server")
    else:
        for hit in found.results:
            print(hit.position, hit.title, hit.url)
        if found.job_id is not None:
            done = client.wait_for_job(found.job_id, poll_interval_s=1, timeout_s=120)
            print("scrape", done.status.value, done.counts.done, "pages")

    # Crawl a docs section best-first: the pages about the query come first.
    job = client.crawl(
        url="https://docs.example.com/guide/",
        formats=["markdown"],
        strategy="best_first",
        query="asyncio event loop",
        max_depth=2,
        limit=5,
    )
    for event in client.events(job.job_id):
        print("event", event.kind)
    for page in client.iter_job_results(job.job_id):
        if page["status"] == "done":
            print(page["url"])
