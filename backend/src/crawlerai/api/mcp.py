"""The MCP server over streamable HTTP at `/mcp`: behind the same rate limit and bearer API key as every
other route (`require_api_key`), and running with the app's runtime."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final, cast

from fastapi import FastAPI, Request
from mcp.server.fastmcp import FastMCP
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from crawlerai.api.auth import require_api_key
from crawlerai.api.problems import ProblemError, problem_response
from crawlerai.mcp_server.server import AnyContext, build_server
from crawlerai.services.runtime import Caller, Runtime

PATH: Final = "/mcp"


class _Authenticated:
    """Answers a request that `require_api_key` refuses with its problem; passes any other on with its key's id in
    the request's state, where `_bind` reads it."""

    def __init__(self, server: FastMCP) -> None:
        self._manager = server.session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        try:
            request.state.api_key_id = await require_api_key(request)
        except ProblemError as e:
            await problem_response(request, e)(scope, receive, send)
            return
        await self._manager.handle_request(scope, receive, send)


async def _bind(ctx: AnyContext) -> Caller:
    request = cast(Request, ctx.request_context.request)  # the HTTP transport's request
    runtime: Runtime = request.app.state.runtime
    return Caller.of(runtime, request.state.api_key_id)


def mount(app: FastAPI) -> None:
    server = build_server(_bind)
    server.streamable_http_app()  # creates the session manager the route hands requests to
    app.state.mcp = server
    route = Route(PATH, _Authenticated(server), methods=["GET", "POST", "DELETE"], include_in_schema=False)
    app.router.routes.append(route)


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[None]:
    """The session manager's task group, for the app's lifespan; a manager runs once, as an app starts once."""
    server: FastMCP = app.state.mcp
    async with server.session_manager.run():
        yield
