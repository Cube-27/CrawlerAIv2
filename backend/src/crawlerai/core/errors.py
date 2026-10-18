"""What every interface may tell a caller about a failed request (rest-api spec, jobs spec).

A `Refusal` is a request the engine refuses or cannot answer, with a message written for the caller: it carries no
internals. REST answers each kind with its own problem; MCP passes the message on. Any other exception may carry
internals (SQL and its parameters, paths), so both answer it with `UNEXPECTED` and the server logs it.
"""

from typing import Final

UNEXPECTED: Final = "the server failed to answer the request"


class Refusal(Exception):
    pass
