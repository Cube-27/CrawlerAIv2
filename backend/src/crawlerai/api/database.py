"""The API's database: the engine the app opens at startup (`app.state.database`), for every route and dependency."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine


def database(request: Request) -> AsyncEngine:
    """The app's database engine; a dependency (`Depends(database)`) or a plain call on the request."""
    engine: AsyncEngine = request.app.state.database
    return engine
