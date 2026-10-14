"""The LLM client (SPEC-06 §4.2, ARCHITECTURE §11): one request shape for every role, JSON-schema output, budgets
and usage.

`MeteredClient` asks its first `Provider` for JSON, fails over to the next one once if the first does not answer
(a rate limit, a server error or a timeout), checks the reply against the request's JSON Schema (draft 2020-12) and
retries once with the validation error appended. A reply cut at the request's output token cap is not retried: the
retry would ask the same with the same cap. A provider's refusal is logged once per provider, model and status. Before
every provider call it checks the job's `llm_calls` budget; after every call that answered, it records `llm_calls`,
`llm_tokens_in` and `llm_tokens_out` (INV-23), and a failure carries the calls that answered before it. Usage is
committed in a transaction of its own, never the caller's: a task that fails afterwards rolls its transaction back,
and the calls it made must still count against the job's budget (D-0151). So a caller must not hold an uncommitted
write to the job's row when it calls the client: the client's own `UPDATE job` would wait on that lock.

Model output is data: it is parsed as JSON and validated, never executed (INV-17, §18).
"""

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import ClassVar, Final, Literal, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, best_match
from pydantic import BaseModel, ConfigDict, JsonValue, field_validator
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.db.models import JobId, UsageResource
from crawlerai.db.usage import BUDGET_EXHAUSTED, budget_remaining, record_usage
from crawlerai.storage.capture_bundle import sha256_hex

log = logging.getLogger(__name__)

# The role of each call (SPEC-06 §4.2); `usage_event.metadata.prompt_kind` and the replay key carry it.
PromptKind = Literal["c_extract_detail", "c_extract_listing", "c_prefill", "a_synth", "a_repair", "d_bind", "s_draft"]
# `fast` for role C, `strong` for A, D and S (§2); settings map each class to a model per provider.
ModelClass = Literal["fast", "strong"]

# Per-call timeouts (§4.7).
TIMEOUT_S: Final[dict[ModelClass, int]] = {"fast": 60, "strong": 120}

# Appended to the prompt for the one retry after an invalid reply (§4.2).
RETRY_NOTE: Final = "Your previous reply was rejected: {error}. Reply with one JSON object that matches the schema."


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LLMRequest(_Model):
    prompt_kind: PromptKind
    model_class: ModelClass
    system: str
    user: str
    output_schema: dict[str, JsonValue]  # JSON Schema (draft 2020-12) of the response
    max_output_tokens: int
    job_id: JobId | None  # None only for an eval replay or the labeling pre-fill, which no job pays for

    @field_validator("output_schema")
    @classmethod
    def _closed_object_schema(cls, schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as error:
            raise ValueError(f"not a valid JSON Schema: {error.message}") from None
        # §4.6: the root is a closed object, so a model cannot add fields that downstream code might pick up.
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            raise ValueError('the root must be {"type": "object", "additionalProperties": false}')
        return schema


def closed_object(properties: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """An object schema with exactly `properties`, each required: the closed object `LLMRequest` requires at its root
    (§4.6), which roles also use for the objects inside it."""
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


class AnsweredCall(_Model):
    """One provider call that answered, charged to the request's job (INV-23), as `extraction.llm_calls` records it
    (§4.2)."""

    provider: str
    model: str
    request_hash: str
    tokens_in: int
    tokens_out: int


class LLMResponse(_Model):
    data: dict[str, JsonValue]  # validated against the request's output_schema
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    request_hash: str
    # The answered call whose invalid reply was retried (§4.2), if any: charged like the one that gave `data`.
    retried: tuple[AnsweredCall, ...] = ()

    @property
    def answered(self) -> tuple[AnsweredCall, ...]:
        """Every answered call that gave this response, in order: the retried one, then the one that gave `data`. A
        failure's `LLMFailure.answered` is the same record."""
        final = AnsweredCall(
            provider=self.provider,
            model=self.model,
            request_hash=self.request_hash,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
        )
        return (*self.retried, final)


# A role's own check of a reply that matches the output schema: why the reply is invalid, or None. JSON Schema can't
# express every rule of a role's output (that every field of a schema document is described, say); a failed check is
# retried like a schema mismatch, within the same one retry.
ReplyCheck = Callable[[dict[str, JsonValue]], str | None]


class LLMClient(Protocol):
    async def complete_json(self, req: LLMRequest, check: ReplyCheck | None = None) -> LLMResponse: ...


def request_hash(req: LLMRequest) -> str:
    """sha256 of (prompt kind, model class, system, user, output schema) as a canonical JSON array (INV-10): an array
    keeps the parts apart, and sorted keys make the schema's key order irrelevant. The model is the requested class;
    the provider picks the concrete model after the request exists (failover), so the hash can't depend on it."""
    parts = [req.prompt_kind, req.model_class, req.system, req.user, req.output_schema]
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_hex(canonical.encode())


class ProviderCall(_Model):
    """What a provider receives: the request without its bookkeeping, at temperature 0."""

    model_class: ModelClass
    system: str
    user: str
    output_schema: dict[str, JsonValue]
    max_output_tokens: int
    timeout_s: int


class ProviderReply(_Model):
    model: str
    text: str  # the raw reply, parsed and validated by the client
    tokens_in: int
    tokens_out: int
    cut: bool = False  # the reply stopped at the call's `max_output_tokens`


class Provider(Protocol):
    @property
    def name(self) -> str: ...

    async def complete(self, call: ProviderCall) -> ProviderReply:
        """Raises `ProviderError` on a rate limit, a server error or a timeout, and `ProviderRefused` when the
        provider refuses the request."""
        ...


class ProviderError(Exception):
    """The provider did not answer: a rate limit, a server error or a timeout."""


def redacted(message: str, secret: str) -> str:
    """`message` without `secret`: a provider's error message is logged and stored, and must never carry its key."""
    return message.replace(secret, "[redacted]") if secret else message


def is_transient(status: int) -> bool:
    """Whether an HTTP status says the provider did not answer this time: 408 Request Timeout (RFC 9110 §15.5.9),
    429 Too Many Requests (RFC 6585 §4) or a 5xx server error (RFC 9110 §15.6). Other errors are the request's own
    fault (a bad key, an unknown model, a refused schema): the provider raises `ProviderRefused`, which is not failed
    over."""
    return status in (408, 429) or 500 <= status <= 599


class LLMFailure(Exception):
    """A call that gave no valid reply (§4.7); `code` names why, as a task's `last_error` and a problem type, and
    `field_reason` as the reason of the fields the call was for, which stay `missing`. `answered` holds the calls that
    answered before it failed, which are charged all the same (an invalid reply, then its retry)."""

    code: ClassVar[str]
    field_reason: ClassVar[str]

    def __init__(self, message: str = "", *, answered: tuple[AnsweredCall, ...] = ()) -> None:
        super().__init__(message)
        self.answered = answered

    def cause(self) -> str | None:
        """What a page's diagnostics may say of the failure besides its reason: never page content."""
        return None


class BudgetExhausted(LLMFailure):
    """The job has no `llm_calls` budget left; the call was not made (§4.7)."""

    code = BUDGET_EXHAUSTED
    field_reason = "llm_budget"


class ProviderUnavailable(LLMFailure):
    """No provider answered (§4.7)."""

    code = field_reason = "llm_unavailable"

    def cause(self) -> str | None:
        return str(self)  # each provider's status or error, without the request


class ProviderRefused(ProviderUnavailable):
    """A provider refused the request: an HTTP error status that `is_transient` does not cover. The call gave no reply,
    as when no provider answers, so the fields stay `missing` with `llm_unavailable` (§4.7); the message keeps the
    provider's reason. A retry or another provider would not fix the request, so it is neither."""

    def __init__(self, provider: str, model: str, status: int, message: str) -> None:
        super().__init__(f"{provider}: HTTP {status}: {message}")
        self.provider = provider
        self.model = model
        self.status = status


class OutputInvalid(LLMFailure):
    """The reply did not match the output schema, after the one retry (§4.7)."""

    code = field_reason = "llm_output_invalid"


class OutputCut(OutputInvalid):
    """The reply stopped at the request's `max_output_tokens` before it was valid. It is not retried: the retry would
    ask the same with the same cap (§4.7)."""

    def __init__(self, max_output_tokens: int, *, answered: tuple[AnsweredCall, ...]) -> None:
        super().__init__(f"the reply stopped at its cap of {max_output_tokens} output tokens", answered=answered)

    def cause(self) -> str | None:
        return str(self)


class Unconfigured:
    """The client of a process without a configured provider: every call raises `ProviderUnavailable` with `reason`.
    Work that needs no call, such as a stored draft (role S), still runs."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def complete_json(self, req: LLMRequest, check: ReplyCheck | None = None) -> LLMResponse:
        raise ProviderUnavailable(self._reason)


@dataclass(frozen=True)
class _Invalid:
    error: str


@dataclass(frozen=True)
class _Answer:
    provider: str
    reply: ProviderReply
    latency_ms: int

    def charged(self, key: str) -> AnsweredCall:
        reply = self.reply
        return AnsweredCall(
            provider=self.provider,
            model=reply.model,
            request_hash=key,
            tokens_in=reply.tokens_in,
            tokens_out=reply.tokens_out,
        )


class MeteredClient:
    def __init__(self, providers: Sequence[Provider], engine: AsyncEngine) -> None:
        """`providers` in order of preference (`CRAWLERAI_LLM_PROVIDERS`). A call fails over at most once (§4.2), so
        there are one or two."""
        if not 1 <= len(providers) <= 2:
            raise ValueError("an LLM client needs one or two providers")
        self._providers = tuple(providers)
        self._engine = engine
        self._refusals_logged: set[tuple[str, str, int]] = set()

    async def complete_json(self, req: LLMRequest, check: ReplyCheck | None = None) -> LLMResponse:
        key = request_hash(req)
        validator = Draft202012Validator(req.output_schema)
        answer = await self._call(req, req.user, key)
        checked = _check(answer.reply.text, validator, check)
        retried: tuple[AnsweredCall, ...] = ()
        if isinstance(checked, _Invalid):
            if answer.reply.cut:
                raise OutputCut(req.max_output_tokens, answered=(answer.charged(key),))
            retried = (answer.charged(key),)
            answer = await self._retry(req, f"{req.user}\n\n{RETRY_NOTE.format(error=checked.error)}", key, retried)
            checked = _check(answer.reply.text, validator, check)
        if isinstance(checked, _Invalid):
            answered = (*retried, answer.charged(key))
            if answer.reply.cut:
                raise OutputCut(req.max_output_tokens, answered=answered)
            raise OutputInvalid(checked.error, answered=answered)
        return LLMResponse(
            data=checked,
            provider=answer.provider,
            model=answer.reply.model,
            tokens_in=answer.reply.tokens_in,
            tokens_out=answer.reply.tokens_out,
            latency_ms=answer.latency_ms,
            request_hash=key,
            retried=retried,
        )

    async def _retry(self, req: LLMRequest, user: str, key: str, retried: tuple[AnsweredCall, ...]) -> "_Answer":
        """The retry's answer; a failure of the retry still carries the call that answered before it."""
        try:
            return await self._call(req, user, key)
        except LLMFailure as failure:
            failure.answered = (*retried, *failure.answered)
            raise

    async def _call(self, req: LLMRequest, user: str, key: str) -> _Answer:
        """One answered call, charged to the request's job: budget first, usage after. The first provider is asked;
        if it does not answer, the next one is asked once. A call that did not answer is not charged (D-0347)."""
        if req.job_id is not None:
            await self._check_budget(req.job_id)
        call = ProviderCall(
            model_class=req.model_class,
            system=req.system,
            user=user,
            output_schema=req.output_schema,
            max_output_tokens=req.max_output_tokens,
            timeout_s=TIMEOUT_S[req.model_class],
        )
        errors: list[str] = []
        for provider in self._providers:
            started = time.monotonic()
            try:
                reply = await provider.complete(call)
            except ProviderError as error:
                errors.append(f"{provider.name}: {error}")
                continue
            except ProviderRefused as refused:
                self._log_refusal(refused)
                raise
            answer = _Answer(provider.name, reply, round((time.monotonic() - started) * 1000))
            if req.job_id is not None:
                await self._record(req.job_id, req, key, answer)
            return answer
        raise ProviderUnavailable("; ".join(errors))

    def _log_refusal(self, refused: ProviderRefused) -> None:
        """Once per provider, model and status in this process: a refusal repeats on every call until the settings
        change, and its message (an unknown model, a bad key, a refused schema) is what the operator needs."""
        seen = (refused.provider, refused.model, refused.status)
        if seen not in self._refusals_logged:
            self._refusals_logged.add(seen)
            log.warning("LLM provider %s refused model %s: %s", refused.provider, refused.model, refused)

    async def _check_budget(self, job_id: JobId) -> None:
        async with self._engine.connect() as conn:
            remaining = await budget_remaining(conn, job_id, "llm_calls")
        if remaining == 0:
            raise BudgetExhausted(f"job {job_id} has no llm_calls budget left")

    async def _record(self, job_id: JobId, req: LLMRequest, key: str, answer: _Answer) -> None:
        # Its own transaction: see the module docstring.
        reply = answer.reply
        metadata = {
            "prompt_kind": req.prompt_kind,
            "model": reply.model,
            "request_hash": key,
            "latency_ms": answer.latency_ms,
            # On every row of the call, so its output tokens can be priced by its prompt length too (§4.8).
            "tokens_in": reply.tokens_in,
        }
        usage: tuple[tuple[UsageResource, int], ...] = (
            ("llm_calls", 1),
            ("llm_tokens_in", reply.tokens_in),
            ("llm_tokens_out", reply.tokens_out),
        )
        async with self._engine.begin() as conn:
            for resource, quantity in usage:
                await record_usage(
                    conn,
                    job_id,
                    resource,
                    provider=answer.provider,
                    model_or_pool=reply.model,
                    quantity=quantity,
                    metadata=metadata,
                )


def _check(text: str, validator: Draft202012Validator, check: ReplyCheck | None) -> dict[str, JsonValue] | _Invalid:
    """The reply as a JSON object that matches the schema and passes the role's check, or why it isn't one."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        return _Invalid(f"not JSON ({error.msg})")
    if not isinstance(data, dict):
        return _Invalid("not a JSON object")
    mismatch = best_match(validator.iter_errors(data))
    if mismatch is not None:
        return _Invalid(f"at {mismatch.json_path}: {mismatch.message}")
    refusal = None if check is None else check(data)
    return data if refusal is None else _Invalid(refusal)
