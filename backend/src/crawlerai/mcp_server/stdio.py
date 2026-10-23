"""The MCP server over stdio, acting with one API key: `CRAWLERAI_API_KEY`. The key is looked up on
every call, as the API looks up each request's, so a revoked key stops working at once. A local process has one
client, so no rate limit stands in front of the lookup."""

from mcp.server.fastmcp.exceptions import ToolError

from crawlerai.core.settings import McpSettings, Settings
from crawlerai.db.keys import authenticate, hash_key
from crawlerai.mcp_server.server import AnyContext, Bind, build_server
from crawlerai.services.runtime import Caller, Runtime, open_runtime


def key_bind(runtime: Runtime, api_key: str) -> Bind:
    """Each call bound to `runtime` and the key, refused while the key is unknown or revoked. Its LLM calls that no job
    pays for count against the key's draft cap (`Caller.of`), as over HTTP."""
    hashed = hash_key(api_key)

    async def bind(ctx: AnyContext) -> Caller:
        async with runtime.database.begin() as conn:
            key_id = await authenticate(conn, hashed)
        if key_id is None:
            raise ToolError("CRAWLERAI_API_KEY is unknown or revoked")
        return Caller.of(runtime, key_id)

    return bind


async def serve() -> None:
    api_key = McpSettings().api_key.get_secret_value()
    async with open_runtime(Settings()) as runtime:
        await build_server(key_bind(runtime, api_key)).run_stdio_async()
