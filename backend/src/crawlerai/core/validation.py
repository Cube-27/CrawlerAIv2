"""One wording for every validation error the engine reports: a request's 422, a schema document's, a label file's;
and the bound of a request member a PostgreSQL `integer` column stores."""

from collections.abc import Sequence
from typing import Final

from pydantic_core import ErrorDetails

# The largest value of a PostgreSQL `integer` column, a 4-byte signed integer (PostgreSQL docs §8.1.1): a request
# member stored in one is bounded by it, so a larger value is refused with a 422 rather than failing the write.
PG_INTEGER_MAX: Final = 2**31 - 1


def error_path(location: Sequence[int | str]) -> str:
    """The dotted path of a location, an index in brackets: `rows[0].fields.price`; `""` for the whole document."""
    return "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in location).removeprefix(".")


def field_error(error: ErrorDetails) -> tuple[str, str]:
    """The (path, reason) of a pydantic error. Our validators raise ValueError, whose message pydantic prefixes with
    "Value error, ": the reason is the message alone."""
    reason = str(error["ctx"]["error"]) if error["type"] == "value_error" else error["msg"]
    return error_path(error["loc"]), reason
