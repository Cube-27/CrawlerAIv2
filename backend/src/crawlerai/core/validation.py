"""One wording for every validation error the engine reports: a request's 422, a schema document's, a label file's."""

from collections.abc import Sequence

from pydantic_core import ErrorDetails


def error_path(location: Sequence[int | str]) -> str:
    """The dotted path of a location, an index in brackets: `rows[0].fields.price`; `""` for the whole document."""
    return "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in location).removeprefix(".")


def field_error(error: ErrorDetails, location: Sequence[int | str] | None = None) -> tuple[str, str]:
    """The (path, reason) of a pydantic error, at `location` when given (the error's own by default). Our validators
    raise ValueError, whose message pydantic prefixes with "Value error, ": the reason is the message alone."""
    reason = str(error["ctx"]["error"]) if error["type"] == "value_error" else error["msg"]
    return error_path(error["loc"] if location is None else location), reason
