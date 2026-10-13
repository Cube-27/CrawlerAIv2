"""Every error the API answers is an RFC 9457 problem (SPEC-07 §4.3): its own, raised as `ProblemError`, and the
framework's (unknown path, wrong method, request validation, an unexpected exception)."""

from collections.abc import Mapping, Sequence
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from crawlerai.api.dto import FieldErrorOut, Problem

PROBLEM_JSON = "application/problem+json"  # RFC 9457 §3


class ProblemError(Exception):
    """Raised by a router or dependency to answer with a problem; `errors` are (field, reason) pairs."""

    def __init__(
        self, status: int, type_: str, title: str, detail: str, errors: Sequence[tuple[str, str]] = ()
    ) -> None:
        super().__init__(detail)
        self.status, self.type, self.title, self.detail, self.errors = status, type_, title, detail, errors


def problem_response(request: Request, error: ProblemError, headers: Mapping[str, str] | None = None) -> JSONResponse:
    problem = Problem(
        type=error.type,
        title=error.title,
        status=error.status,
        detail=error.detail,
        instance=request.url.path,
        errors=[FieldErrorOut(field=field, reason=reason) for field, reason in error.errors],
    )
    return JSONResponse(problem.model_dump(), status_code=error.status, headers=headers, media_type=PROBLEM_JSON)


def _status_only(status: int, detail: str | None = None) -> ProblemError:
    """A problem that is no more than its HTTP status: `about:blank`, titled with the status phrase (RFC 9457
    §4.2.1)."""
    phrase = HTTPStatus(status).phrase
    return ProblemError(status, "about:blank", phrase, detail or phrase)


def _field(location: Sequence[int | str]) -> str:
    """The dotted path of a validation error: within the body as is, else prefixed with where it is (`query.x`)."""
    parts = [str(part) for part in location]
    return ".".join(parts[1:] if parts[:1] == ["body"] else parts)


async def _on_problem(request: Request, exc: ProblemError) -> JSONResponse:
    return problem_response(request, exc)


async def _on_http(request: Request, exc: HTTPException) -> JSONResponse:
    if exc.status_code == HTTPStatus.NOT_FOUND:
        error = ProblemError(404, "not_found", "Not found", f"no resource at {request.url.path}")
    else:
        error = _status_only(exc.status_code, exc.detail if isinstance(exc.detail, str) else None)
    return problem_response(request, error, exc.headers)  # e.g. `Allow` on a 405 (RFC 9110 §15.5.6)


async def _on_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [(_field(error["loc"]), error["msg"]) for error in exc.errors()]
    return problem_response(
        request, ProblemError(422, "validation", "Invalid request", "the request is invalid", errors)
    )


async def _on_unexpected(request: Request, exc: Exception) -> JSONResponse:
    # The message is left out: it may carry internals. The server still logs the exception.
    return problem_response(request, _status_only(500, "the server failed to answer the request"))


def install(app: FastAPI) -> None:
    # The decorator form takes handlers typed with their exception class.
    app.exception_handler(ProblemError)(_on_problem)
    app.exception_handler(HTTPException)(_on_http)
    app.exception_handler(RequestValidationError)(_on_validation)
    app.exception_handler(Exception)(_on_unexpected)
