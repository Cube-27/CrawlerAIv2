"""Every error the API answers is an RFC 9457 problem (SPEC-07 §4.3): its own, raised as `ProblemError`, and the
framework's (unknown path, wrong method, request validation, an unexpected exception)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from crawlerai.api.dto import FieldErrorOut, Problem
from crawlerai.core.errors import UNEXPECTED
from crawlerai.llm.client import BudgetExhausted, LLMFailure, OutputInvalid, ProviderUnavailable

PROBLEM_JSON = "application/problem+json"  # RFC 9457 §3


@dataclass
class ProblemError(Exception):
    """Raised by a router or dependency to answer with a problem; `errors` are (field, reason) pairs, `headers` go
    on the response."""

    status: int
    type: str
    title: str
    detail: str
    errors: Sequence[tuple[str, str]] = ()
    headers: Mapping[str, str] = field(default_factory=dict)


def not_found(detail: str) -> ProblemError:
    return ProblemError(404, "not_found", "Not found", detail)


def conflict(detail: str) -> ProblemError:
    return ProblemError(409, "conflict", "Conflict", detail)


def records_unavailable(detail: str) -> ProblemError:
    """The engine's data files are not installed, so no records can be extracted
    (`services.scrape_steps.load_engine_data`)."""
    return ProblemError(503, "records_unavailable", "Records unavailable", detail)


def target_refused(reason: str) -> ProblemError:
    """422: the request names a target the API may not fetch (INV-16); `reason` is the SSRF guard's."""
    return ProblemError(422, "ssrf_rejected", "Target refused", reason)


def invalid(detail: str, errors: Sequence[tuple[str, str]] = ()) -> ProblemError:
    return ProblemError(422, "validation", "Invalid request", detail, errors)


# 422: the request's own `budget.llm_calls` does not cover its work. 503: no provider answered. 502: the model
# answered, but not validly, after the one retry.
_LLM_PROBLEMS: Final[dict[str, tuple[int, str]]] = {
    BudgetExhausted.code: (422, "Budget exhausted"),
    ProviderUnavailable.code: (503, "LLM unavailable"),
    OutputInvalid.code: (502, "LLM output invalid"),
}


def llm_problem(failure: LLMFailure) -> ProblemError:
    """An LLM call that gave no valid reply (SPEC-06 §4.7), as a problem typed with the failure's code."""
    status, title = _LLM_PROBLEMS[failure.code]
    return ProblemError(status, failure.code, title, str(failure))


def problem_response(request: Request, error: ProblemError) -> JSONResponse:
    problem = Problem(
        type=error.type,
        title=error.title,
        status=error.status,
        detail=error.detail,
        instance=request.url.path,
        errors=[FieldErrorOut(field=field, reason=reason) for field, reason in error.errors],
    )
    return JSONResponse(problem.model_dump(), status_code=error.status, headers=error.headers, media_type=PROBLEM_JSON)


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
        error = not_found(f"no resource at {request.url.path}")
    else:
        error = _status_only(exc.status_code, exc.detail if isinstance(exc.detail, str) else None)
    error.headers = exc.headers or {}  # e.g. `Allow` on a 405 (RFC 9110 §15.5.6)
    return problem_response(request, error)


async def _on_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [(_field(error["loc"]), error["msg"]) for error in exc.errors()]
    return problem_response(request, invalid("the request is invalid", errors))


async def _on_unexpected(request: Request, exc: Exception) -> JSONResponse:
    # The message is left out: it may carry internals. The server still logs the exception.
    return problem_response(request, _status_only(500, UNEXPECTED))


def install(app: FastAPI) -> None:
    # The decorator form takes handlers typed with their exception class.
    app.exception_handler(ProblemError)(_on_problem)
    app.exception_handler(HTTPException)(_on_http)
    app.exception_handler(RequestValidationError)(_on_validation)
    app.exception_handler(Exception)(_on_unexpected)
