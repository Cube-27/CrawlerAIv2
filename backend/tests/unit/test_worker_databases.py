"""Under pytest-xdist each worker runs the DB tests in a database of its own (`tests/db/conftest.py`)."""

from tests.db.conftest import worker_database_url

URL = "postgresql+asyncpg://app:app@127.0.0.1:5432/snowcrawl"


def test_a_worker_gets_the_database_named_after_it() -> None:
    assert worker_database_url(URL, "gw2") == "postgresql+asyncpg://app:app@127.0.0.1:5432/snowcrawl_gw2"
