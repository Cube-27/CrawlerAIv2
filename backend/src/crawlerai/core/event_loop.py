"""A peer's reset of a closing connection, kept out of the error log.

On Windows, asyncio's Proactor transports close a socket in `_ProactorBasePipeTransport._call_connection_lost`, which
calls `socket.shutdown()` without catching the error a peer that has already reset the connection raises
(`ConnectionResetError`, WinError 10054; CPython 3.12 `Lib/asyncio/proactor_events.py`, still uncaught there). The
callback's exception reaches the loop's exception handler, which logs it at ERROR with a traceback, although the
connection was being closed anyway and nothing is lost. `quiet_peer_resets` logs exactly that case at DEBUG; every
other exception goes to the handler the loop had.
"""

import asyncio
import logging
from asyncio import proactor_events
from types import CodeType, TracebackType
from typing import Any, Final

log = logging.getLogger(__name__)

# Read from the class's namespace: typeshed does not declare the private method.
_CLOSING: Final[CodeType] = vars(proactor_events._ProactorBasePipeTransport)["_call_connection_lost"].__code__


def quiet_peer_resets(loop: asyncio.AbstractEventLoop) -> None:
    """Install the handler on `loop` (module docstring), in front of the loop's own."""
    previous = loop.get_exception_handler()

    def handle(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        error = context.get("exception")
        if isinstance(error, ConnectionResetError) and _raised_while_closing(error.__traceback__):
            log.debug("a peer reset a connection being closed: %s", error)
        elif previous is not None:
            previous(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(handle)


def _raised_while_closing(traceback: TracebackType | None) -> bool:
    while traceback is not None:
        if traceback.tb_frame.f_code is _CLOSING:
            return True
        traceback = traceback.tb_next
    return False
