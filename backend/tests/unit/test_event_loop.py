"""A peer's reset of a closing Proactor connection is logged at DEBUG, not ERROR; other callback errors are not
touched. The transport's close step runs on a stand-in socket whose shutdown raises what Windows raises."""

import asyncio
import logging
from asyncio import proactor_events
from collections.abc import Callable
from types import SimpleNamespace

import pytest

from snowcrawl.core import event_loop
from snowcrawl.core.event_loop import quiet_peer_resets


@pytest.fixture(autouse=True)
def _logged(monkeypatch: pytest.MonkeyPatch) -> None:
    # Alembic's `fileConfig` (migrations/env.py) disables existing loggers when a DB test migrates in this process.
    monkeypatch.setattr(event_loop.log, "disabled", False)


def _reset(*_args: object) -> None:
    raise ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host")


def _closing_transport() -> SimpleNamespace:
    socket = SimpleNamespace(shutdown=_reset, fileno=lambda: 3, close=lambda: None)
    protocol = SimpleNamespace(connection_lost=lambda _exc: None)
    return SimpleNamespace(_called_connection_lost=False, _protocol=protocol, _sock=socket, _server=None)


def _run_callback(callback: Callable[..., object], *args: object) -> None:
    async def main() -> None:
        loop = asyncio.get_running_loop()
        quiet_peer_resets(loop)
        loop.call_soon(callback, *args)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(main())


def _errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno >= logging.ERROR]


def test_a_reset_while_a_proactor_transport_closes_is_not_an_error(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=event_loop.log.name)
    close = vars(proactor_events._ProactorBasePipeTransport)["_call_connection_lost"]

    _run_callback(close, _closing_transport(), None)

    assert _errors(caplog) == []
    assert [r.getMessage() for r in caplog.records if r.name == "snowcrawl.core.event_loop"] == [
        "a peer reset a connection being closed: [Errno 10054] An existing connection was forcibly closed by the remote"
        " host"
    ]


def test_a_reset_anywhere_else_is_still_an_error(caplog: pytest.LogCaptureFixture) -> None:
    _run_callback(_reset)

    (error,) = _errors(caplog)
    assert isinstance(error.exc_info[1] if error.exc_info else None, ConnectionResetError)
