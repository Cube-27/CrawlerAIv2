"""The API's runtime: the one the app opens at startup (`app.state.runtime`), for every route and dependency."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.services.runtime import Runtime


def runtime(request: Request) -> Runtime:
    """The app's runtime; a dependency (`Depends(runtime)`) or a plain call on the request."""
    opened: Runtime = request.app.state.runtime
    return opened


def database(request: Request) -> AsyncEngine:
    """The runtime's database engine; a dependency (`Depends(database)`) or a plain call on the request."""
    return runtime(request).database
