"""Server-sent events (WHATWG HTML §9.2.5) as the job events endpoint sends them."""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JobEvent:
    """One event: `kind` is the event name (`progress`, `completed`, ...), `id` the id to resume after, `data` the
    decoded JSON payload (the raw text when it is not JSON)."""

    kind: str
    id: str | None
    data: Any


class _Parser:
    """Feeds lines, yields an event at each blank line."""

    def __init__(self) -> None:
        self._kind = ""
        self._id: str | None = None
        self._data: list[str] = []

    def feed(self, line: str) -> JobEvent | None:
        if line == "":
            event = self._finish()
            self._kind, self._data = "", []
            return event
        if line.startswith(":"):
            return None  # a comment: the server's keep-alive
        name, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if name == "event":
            self._kind = value
        elif name == "id":
            self._id = value
        elif name == "data":
            self._data.append(value)
        return None

    def _finish(self) -> JobEvent | None:
        if not self._data:
            return None
        text = "\n".join(self._data)
        try:
            data: Any = json.loads(text)
        except ValueError:
            data = text
        return JobEvent(self._kind or "message", self._id, data)


def parse(lines: Iterable[str]) -> Iterator[JobEvent]:
    parser = _Parser()
    for line in lines:
        if (event := parser.feed(line.rstrip("\r\n"))) is not None:
            yield event


async def aparse(lines: AsyncIterable[str]) -> AsyncIterator[JobEvent]:
    parser = _Parser()
    async for line in lines:
        if (event := parser.feed(line.rstrip("\r\n"))) is not None:
            yield event
