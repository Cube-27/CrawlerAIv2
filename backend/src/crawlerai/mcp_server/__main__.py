"""`python -m crawlerai.mcp_server`: the MCP server over stdio (`crawlerai.mcp_server.stdio`)."""

import anyio

from crawlerai.mcp_server.stdio import serve

anyio.run(serve)
