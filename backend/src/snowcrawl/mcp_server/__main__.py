"""`python -m snowcrawl.mcp_server`: the MCP server over stdio (`snowcrawl.mcp_server.stdio`)."""

import anyio

from snowcrawl.mcp_server.stdio import serve

anyio.run(serve)
