"""SQLAlchemy models of the main database (ARCHITECTURE §6, SPEC-01 §4.2). The models and the Alembic revisions own
the DB shape; `tests/db` checks that the migrated database matches these models.

Enumerations are `text` with a CHECK constraint whose values come from the matching `Literal`.
"""

import uuid
from datetime import datetime
from typing import Any, ClassVar, Literal, NewType, get_args

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Text,
    TextClause,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.core.ids import uuid7

# SQL referential action (ISO/IEC 9075-2 §11.8): a deleted parent leaves the reference empty.
_SET_NULL = "SET NULL"

ProjectId = NewType("ProjectId", uuid.UUID)
ApiKeyId = NewType("ApiKeyId", uuid.UUID)
SiteId = NewType("SiteId", uuid.UUID)
SchemaId = NewType("SchemaId", uuid.UUID)
JobId = NewType("JobId", uuid.UUID)
UrlTaskId = NewType("UrlTaskId", uuid.UUID)
JobEventId = NewType("JobEventId", uuid.UUID)
CaptureId = NewType("CaptureId", uuid.UUID)
ExtractionId = NewType("ExtractionId", uuid.UUID)
CandidateId = NewType("CandidateId", uuid.UUID)
RecordId = NewType("RecordId", uuid.UUID)
ExtractionConfigId = NewType("ExtractionConfigId", uuid.UUID)
UsageEventId = NewType("UsageEventId", uuid.UUID)
EvalPageId = NewType("EvalPageId", uuid.UUID)
EvalRunId = NewType("EvalRunId", uuid.UUID)

FetchMethod = Literal["http", "browser"]
PageKind = Literal["detail", "listing"]
SchemaOrigin = Literal["preset", "user", "prompt_draft"]
SchemaStatus = Literal["active", "retired"]
JobKind = Literal["scrape", "batch_scrape", "map", "crawl", "extract", "learn"]
JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
TaskStatus = Literal["queued", "claimed", "done", "failed", "cancelled"]
# The outcomes of a task that ran to the end (status `done`); `failed` is the outcome of a `failed` task.
FinishedOutcome = Literal[
    "extracted", "partial", "unchanged", "links_only", "blocked", "shell", "not_found", "no_match"
]
TaskOutcome = Literal[FinishedOutcome, "failed"]
ExtractionMode = Literal["adhoc", "config"]
NormalizeStatus = Literal["ok", "ambiguous", "invalid"]
SourceKind = Literal["adapter", "api", "jsonld", "microdata", "og", "js_state", "xhr", "config", "llm"]
ConfigStatus = Literal["draft", "active", "suspended"]
ConfigOrigin = Literal["adapter", "induced", "llm_synth", "operator"]
# `extraction_config.field_status` values (ARCHITECTURE §6, §8.3 step 4).
FieldStatus = Literal["corroborated", "uncorroborated", "operator", "suspended"]
ProgressiveMode = Literal["cold", "learning", "active"]
# What `usage_event` counts (SPEC-01 §4.6), each in whole units: calls, tokens, seconds, bytes, requests.
UsageResource = Literal[
    "llm_calls", "llm_tokens_in", "llm_tokens_out", "browser_seconds", "proxy_bytes", "http_requests"
]
# Evaluation splits and stratification categories (ARCHITECTURE §16.1). Dev cases live in this database; hidden and
# fresh cases only in the private one (C1, `crawlerai.db.private_models`).
Split = Literal["dev", "hidden", "fresh"]
PrivateSplit = Literal["hidden", "fresh"]
EvalCategory = Literal["platform_store", "custom_store", "api_backed", "job_board", "mixed"]
WebhookStatus = Literal["pending", "delivered", "failed"]


def one_of(column: str, values: Any) -> str:
    """The CHECK expression restricting `column` to the members of a `Literal`."""
    return f"{column} IN ({', '.join(repr(value) for value in get_args(values))})"


# Shared with the private eval database's models, so both databases name and type things alike.
TYPE_ANNOTATION_MAP: dict[Any, Any] = dict.fromkeys(
    (
        ProjectId,
        ApiKeyId,
        SiteId,
        SchemaId,
        JobId,
        UrlTaskId,
        JobEventId,
        CaptureId,
        ExtractionId,
        CandidateId,
        RecordId,
        ExtractionConfigId,
        UsageEventId,
        EvalPageId,
        EvalRunId,
    ),
    Uuid,
)
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
}


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = TYPE_ANNOTATION_MAP
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def created_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def empty_object_default() -> TextClause:
    """The server default of a JSONB object column: an empty object."""
    return text("'{}'::jsonb")


def empty_array_default() -> TextClause:
    """The server default of a JSONB array column: an empty array."""
    return text("'[]'::jsonb")


def version_positive() -> CheckConstraint:
    """Versions count from 1."""
    return CheckConstraint("version >= 1", name="version_positive")


class Project(Base):
    __tablename__ = "project"

    id: Mapped[ProjectId] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = created_at_column()


class ApiKey(Base):
    __tablename__ = "api_key"

    id: Mapped[ApiKeyId] = mapped_column(primary_key=True, default=uuid7)
    hashed_key: Mapped[str] = mapped_column(Text, unique=True)
    label: Mapped[str] = mapped_column(Text)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    webhook_secret: Mapped[str] = mapped_column(Text)


class Site(Base):
    __tablename__ = "site"
    __table_args__ = (
        CheckConstraint("host = lower(host)", name="host_lowercase"),
        CheckConstraint(one_of("fetch_method", FetchMethod), name="fetch_method"),
        CheckConstraint("crawl_delay_ms >= 0", name="crawl_delay_ms_non_negative"),
    )

    id: Mapped[SiteId] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[ProjectId] = mapped_column(ForeignKey(Project.id))
    host: Mapped[str] = mapped_column(Text, unique=True)
    platform: Mapped[str | None] = mapped_column(Text)
    fetch_method: Mapped[FetchMethod] = mapped_column(Text, server_default=text("'http'"))
    proxy_pool: Mapped[str | None] = mapped_column(Text)
    robots_snapshot: Mapped[str | None] = mapped_column(Text)
    crawl_delay_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_column()
    fetch_method_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SchemaDef(Base):
    __tablename__ = "schema_def"
    __table_args__ = (
        UniqueConstraint("name", "version"),
        # The target of the (`schema_id`, `schema_version`) foreign keys below: a row naming a schema version names
        # the version that `schema_id` is (ARCHITECTURE §5.2).
        UniqueConstraint("id", "version"),
        # The target of `eval_page`'s (`schema_id`, `schema_name`) foreign key.
        UniqueConstraint("id", "name"),
        version_positive(),
        CheckConstraint(one_of("page_kind", PageKind), name="page_kind"),
        CheckConstraint(one_of("origin", SchemaOrigin), name="origin"),
        CheckConstraint(one_of("status", SchemaStatus), name="status"),
    )

    id: Mapped[SchemaId] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    page_kind: Mapped[PageKind] = mapped_column(Text)
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB)
    required_groups: Mapped[list[list[str]]] = mapped_column(JSONB, server_default=empty_array_default())
    origin: Mapped[SchemaOrigin] = mapped_column(Text)
    status: Mapped[SchemaStatus] = mapped_column(Text)


def _schema_version_fk() -> ForeignKeyConstraint:
    """(`schema_id`, `schema_version`) names an existing schema_def row and its version (ARCHITECTURE §5.2)."""
    return ForeignKeyConstraint(["schema_id", "schema_version"], [SchemaDef.id, SchemaDef.version])


class Capture(Base):
    """A fetched page, whose bytes are the bundle at `object_key` (ARCHITECTURE §15). Production and dev captures
    only: hidden and fresh captures never enter the main database (C1)."""

    __tablename__ = "capture"
    __table_args__ = (
        CheckConstraint(one_of("method", CaptureMethod), name="method"),
        CheckConstraint(one_of("block_class", BlockClass), name="block_class"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
        CheckConstraint("duration_ms >= 0", name="duration_ms_non_negative"),
        # `expire_captures` deletes rows past `expires_at`; dev captures never expire and stay out of the index.
        Index(None, "expires_at", postgresql_where=text("expires_at IS NOT NULL")),
        # A site's recent captures: `scrape`'s `max_age` reuse (SPEC-07 §4.4).
        Index(None, "site_id", "fetched_at"),
    )

    id: Mapped[CaptureId] = mapped_column(primary_key=True, default=uuid7)
    site_id: Mapped[SiteId] = mapped_column(ForeignKey(Site.id))
    url: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    method: Mapped[CaptureMethod] = mapped_column(Text)
    status_code: Mapped[int] = mapped_column(Integer)
    final_url: Mapped[str] = mapped_column(Text)
    block_class: Mapped[BlockClass] = mapped_column(Text)
    object_key: Mapped[str] = mapped_column(Text, unique=True)
    html_sha256: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    duration_ms: Mapped[int] = mapped_column(Integer)
    fetch_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=empty_object_default())


class ExtractionConfig(Base):
    __tablename__ = "extraction_config"
    __table_args__ = (
        _schema_version_fk(),
        UniqueConstraint("site_id", "schema_id", "page_kind", "version"),
        version_positive(),
        CheckConstraint(one_of("page_kind", PageKind), name="page_kind"),
        CheckConstraint(one_of("status", ConfigStatus), name="status"),
        CheckConstraint(one_of("origin", ConfigOrigin), name="origin"),
        # ARCHITECTURE §6: one `active` config per (site, schema, page_kind).
        Index(
            "uq_extraction_config_active",
            "site_id",
            "schema_id",
            "page_kind",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[ExtractionConfigId] = mapped_column(primary_key=True, default=uuid7)
    site_id: Mapped[SiteId] = mapped_column(ForeignKey(Site.id))
    schema_id: Mapped[SchemaId] = mapped_column()
    schema_version: Mapped[int] = mapped_column(Integer)
    page_kind: Mapped[PageKind] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[ConfigStatus] = mapped_column(Text, server_default=text("'draft'"))
    ir: Mapped[dict[str, Any]] = mapped_column(JSONB)
    origin: Mapped[ConfigOrigin] = mapped_column(Text)
    field_status: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=empty_object_default())
    validation_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # SPEC-08 §4.9: per field, `[matched, valid]` for each of the last pages the config ran on.
    drift_window: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=empty_object_default())


class ProgressiveState(Base):
    """How far a (site, schema version, page kind) is on the way to an active config (ARCHITECTURE §8.4)."""

    __tablename__ = "progressive_state"
    __table_args__ = (
        _schema_version_fk(),
        CheckConstraint(one_of("page_kind", PageKind), name="page_kind"),
        CheckConstraint(one_of("mode", ProgressiveMode), name="mode"),
        CheckConstraint("pages_extracted >= 0", name="pages_extracted_non_negative"),
        CheckConstraint("mode <> 'learning' OR learning_started_at IS NOT NULL", name="learning_has_started"),
        CheckConstraint("mode <> 'active' OR active_config_id IS NOT NULL", name="active_has_config"),
        CheckConstraint("retry_at_pages >= 0", name="retry_at_pages_non_negative"),
    )

    site_id: Mapped[SiteId] = mapped_column(ForeignKey(Site.id), primary_key=True)
    schema_id: Mapped[SchemaId] = mapped_column(primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_kind: Mapped[PageKind] = mapped_column(Text, primary_key=True)
    mode: Mapped[ProgressiveMode] = mapped_column(Text, server_default=text("'cold'"))
    pages_extracted: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Set while a `learn` job runs for this state, in any mode (SPEC-08 §4.4).
    learning_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When a learning run last activated a config (§4.8).
    last_learned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_config_id: Mapped[ExtractionConfigId | None] = mapped_column(ForeignKey(ExtractionConfig.id))
    # The `pages_extracted` at which learning is tried again after a failed run; NULL until one fails (§4.8, D-0030).
    retry_at_pages: Mapped[int | None] = mapped_column(Integer)


class UrlState(Base):
    """What recurring runs last saw at a URL of a site (ARCHITECTURE §14)."""

    __tablename__ = "url_state"
    __table_args__ = (CheckConstraint("missing_runs >= 0", name="missing_runs_non_negative"),)

    site_id: Mapped[SiteId] = mapped_column(ForeignKey(Site.id), primary_key=True)
    canonical_url: Mapped[str] = mapped_column(Text, primary_key=True)
    etag: Mapped[str | None] = mapped_column(Text)
    # The header value as received: If-Modified-Since sends it back unchanged (RFC 9110 §13.1.3).
    last_modified: Mapped[str | None] = mapped_column(Text)
    content_fingerprint: Mapped[str | None] = mapped_column(Text)
    record_fingerprint: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    missing_runs: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    gone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The crawl whose listing last held the URL (SPEC-11 §4.5); NULL while no listing has.
    last_seen_job_id: Mapped[JobId | None] = mapped_column(ForeignKey("job.id", ondelete=_SET_NULL))


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (
        CheckConstraint(one_of("kind", JobKind), name="kind"),
        CheckConstraint(one_of("status", JobStatus), name="status"),
    )

    id: Mapped[JobId] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[ProjectId] = mapped_column(ForeignKey(Project.id))
    kind: Mapped[JobKind] = mapped_column(Text)
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)
    schema_id: Mapped[SchemaId | None] = mapped_column(ForeignKey(SchemaDef.id))
    status: Mapped[JobStatus] = mapped_column(Text, server_default=text("'queued'"))
    webhook_url: Mapped[str | None] = mapped_column(Text)
    engine_version: Mapped[str] = mapped_column(Text)
    # What its pages run with, pinned at submit (INV-28: `services.batch.JobPins`); NULL without records.
    pinned: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=empty_object_default())
    created_at: Mapped[datetime] = created_at_column()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # The key that submitted the job: its `webhook_secret` signs the job's webhook (SPEC-10 §4.2). NULL for a job no
    # key submitted (a learning run).
    api_key_id: Mapped[ApiKeyId | None] = mapped_column(ForeignKey(ApiKey.id))


class UrlTask(Base):
    __tablename__ = "url_task"
    __table_args__ = (
        CheckConstraint(one_of("page_kind", PageKind), name="page_kind"),
        CheckConstraint(one_of("status", TaskStatus), name="status"),
        CheckConstraint(one_of("outcome", TaskOutcome), name="outcome"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint("depth >= 0", name="depth_non_negative"),
        Index(None, "status", "next_attempt_at", "priority"),
        # A crawl enqueues each canonical URL once per job (SPEC-10 §4). Its index, led by `job_id`, also serves the
        # per-job task counts that settle a job (`crawlerai.db.queue`).
        UniqueConstraint("job_id", "canonical_url"),
        # Settling a job first asks whether any of its tasks is still open (`crawlerai.db.queue`).
        Index(None, "job_id", postgresql_where=text("status IN ('queued', 'claimed')")),
    )

    id: Mapped[UrlTaskId] = mapped_column(primary_key=True, default=uuid7)
    job_id: Mapped[JobId] = mapped_column(ForeignKey(Job.id))
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text)
    page_kind: Mapped[PageKind | None] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(Text, server_default=text("'queued'"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Captures expire after 30 days (ARCHITECTURE §15) and the task outlives its capture. Indexed for that delete.
    capture_id: Mapped[CaptureId | None] = mapped_column(ForeignKey(Capture.id, ondelete=_SET_NULL), index=True)
    outcome: Mapped[TaskOutcome | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    claimed_by: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    priority: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    depth: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    parent_task_id: Mapped[UrlTaskId | None] = mapped_column(ForeignKey(f"{__tablename__}.id"))


class JobEvent(Base):
    """A run event of a job (ARCHITECTURE §17), stored so that SSE clients can resume (SPEC-01 §4.2)."""

    __tablename__ = "job_event"
    # The event stream reads a job's events in id order, after the last one sent (SPEC-10 §4.2).
    __table_args__ = (Index(None, "job_id", "id"),)

    id: Mapped[JobEventId] = mapped_column(primary_key=True, default=uuid7)
    job_id: Mapped[JobId] = mapped_column(ForeignKey(Job.id))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=empty_object_default())


class WebhookDelivery(Base):
    """The completion webhook of an ended job (SPEC-10 §4.2): `pending` until it is delivered or its attempts run out.
    Written with the job's end, so a job never ends without its webhook being owed."""

    __tablename__ = "webhook_delivery"
    __table_args__ = (
        CheckConstraint(one_of("status", WebhookStatus), name="status"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        # The scheduler reads the pending deliveries that are due.
        Index(None, "next_attempt_at", postgresql_where=text("status = 'pending'")),
    )

    job_id: Mapped[JobId] = mapped_column(ForeignKey(Job.id), primary_key=True)
    status: Mapped[WebhookStatus] = mapped_column(Text, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)


class UsageEvent(Base):
    """One use of a counted resource by a job (ARCHITECTURE §6, §17): for visibility and budgets, not billing."""

    __tablename__ = "usage_event"
    __table_args__ = (
        CheckConstraint(one_of("resource", UsageResource), name="resource"),
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
        # A job's events, for the LLM cost on its summary (SPEC-06 §4.8, SPEC-10 §4.2).
        Index(None, "job_id", "id"),
    )

    id: Mapped[UsageEventId] = mapped_column(primary_key=True, default=uuid7)
    job_id: Mapped[JobId] = mapped_column(ForeignKey(Job.id))
    resource: Mapped[UsageResource] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)
    model_or_pool: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[int] = mapped_column(BigInteger)
    # `metadata` is taken by the declarative base; the column keeps the §6 name.
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default=empty_object_default())


class Extraction(Base):
    """One resolver run over a capture (ARCHITECTURE §6)."""

    __tablename__ = "extraction"
    __table_args__ = (
        CheckConstraint(one_of("mode", ExtractionMode), name="mode"),
        CheckConstraint("llm_calls >= 0", name="llm_calls_non_negative"),
    )

    id: Mapped[ExtractionId] = mapped_column(primary_key=True, default=uuid7)
    # Indexed for a finished task's events, which report its extraction (SPEC-10 §4.2).
    url_task_id: Mapped[UrlTaskId] = mapped_column(ForeignKey(UrlTask.id), index=True)
    # Captures expire after 30 days (ARCHITECTURE §15) and the extraction, which records cite, stays. Indexed for
    # that delete.
    capture_id: Mapped[CaptureId | None] = mapped_column(ForeignKey(Capture.id, ondelete=_SET_NULL), index=True)
    engine_version: Mapped[str] = mapped_column(Text)
    config_version: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[ExtractionMode] = mapped_column(Text)
    llm_calls: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # What the collectors skipped and why (SPEC-05 §4.14): an invalid JSON block, a collector that raised.
    diagnostics: Mapped[list[str]] = mapped_column(JSONB, server_default=empty_array_default())


class Candidate(Base):
    """One value a collector proposed for a field (ARCHITECTURE §6, §8.1). Kept 30 days."""

    __tablename__ = "candidate"
    __table_args__ = (
        CheckConstraint(one_of("normalize_status", NormalizeStatus), name="normalize_status"),
        CheckConstraint(one_of("source_kind", SourceKind), name="source_kind"),
        # `expire_candidates` deletes rows older than 30 days.
        Index(None, "created_at"),
    )

    id: Mapped[CandidateId] = mapped_column(primary_key=True, default=uuid7)
    extraction_id: Mapped[ExtractionId] = mapped_column(ForeignKey(Extraction.id), index=True)
    entity_ref: Mapped[str] = mapped_column(Text)
    field: Mapped[str] = mapped_column(Text)
    raw_value: Mapped[Any] = mapped_column(JSONB)
    normalized_value: Mapped[Any | None] = mapped_column(JSONB)
    normalize_status: Mapped[NormalizeStatus] = mapped_column(Text)
    source_kind: Mapped[SourceKind] = mapped_column(Text)
    independent: Mapped[bool] = mapped_column(Boolean)
    locator: Mapped[str] = mapped_column(Text)
    chosen: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    reject_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()


class Record(Base):
    """A published entity: `data` holds published fields only (ARCHITECTURE §6). A new version points at the one it
    replaces through `supersedes_record_id` (§14)."""

    __tablename__ = "record"
    __table_args__ = (
        _schema_version_fk(),
        CheckConstraint(one_of("mode", ExtractionMode), name="mode"),
        version_positive(),
        # Recurring runs compare fingerprints per (site, entity, schema) (SPEC-11 §4.4), and find the newest record that
        # stands for a page, by id (`recurring.state.standing_record`).
        Index(None, "site_id", "entity_key", "schema_id", "id"),
        # The change feed (`changed_since`), and the commit stamp of migration 0018's trigger.
        Index(None, "created_at"),
        # `GET /v1/records` by job or by schema, newest first by id (SPEC-07 §4.6), and a capture's records for replay.
        Index(None, "job_id", "id"),
        Index(None, "schema_id", "id"),
        Index(None, "extraction_id"),
    )

    id: Mapped[RecordId] = mapped_column(primary_key=True, default=uuid7)
    extraction_id: Mapped[ExtractionId] = mapped_column(ForeignKey(Extraction.id))
    job_id: Mapped[JobId] = mapped_column(ForeignKey(Job.id))
    site_id: Mapped[SiteId] = mapped_column(ForeignKey(Site.id))
    schema_id: Mapped[SchemaId] = mapped_column()
    schema_version: Mapped[int] = mapped_column(Integer)
    entity_key: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    field_meta: Mapped[dict[str, Any]] = mapped_column(JSONB)
    complete: Mapped[bool] = mapped_column(Boolean)
    changed_fields: Mapped[list[str]] = mapped_column(JSONB, server_default=empty_array_default())
    mode: Mapped[ExtractionMode] = mapped_column(Text)
    fingerprint: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    supersedes_record_id: Mapped[RecordId | None] = mapped_column(ForeignKey(f"{__tablename__}.id"))


class TaskRecord(Base):
    """A record a task's page stands for (SPEC-11 §4.2, §4.4): one it stored, or the entity's latest version when the
    page's record was unchanged and stored nothing. A job's records are those of its tasks (SPEC-10 §4.2 results).
    Plumbing for §4.2's `url_task.record_id`, as a table because a listing page stands for one record per row."""

    __tablename__ = "task_record"

    url_task_id: Mapped[UrlTaskId] = mapped_column(ForeignKey(UrlTask.id, ondelete="CASCADE"), primary_key=True)
    # Indexed for the records a job lists, which join on it, and for a record's delete.
    record_id: Mapped[RecordId] = mapped_column(ForeignKey(Record.id, ondelete="CASCADE"), primary_key=True, index=True)
    # When the task stood for the record (`recurring.state.standing_record`); links made before migration 0018 have
    # their record's time.
    created_at: Mapped[datetime] = created_at_column()


class EvalPageColumns:
    """The `eval_page` columns both eval databases share (ARCHITECTURE §6, SPEC-03 §4.3). Each database adds the
    split it may hold and the capture its rows reference.

    `schema_name` is plumbing: the private database has no `schema_def` to join, and pages are listed by schema name.
    `labels` is the label document of SPEC-03 §4.3; `labeler` and `checker` are the two passes (§16.2), which must
    be different people.
    """

    id: Mapped[EvalPageId] = mapped_column(primary_key=True, default=uuid7)
    split: Mapped[Split] = mapped_column(Text)
    schema_id: Mapped[SchemaId] = mapped_column()
    schema_name: Mapped[str] = mapped_column(Text)
    page_kind: Mapped[PageKind] = mapped_column(Text)
    category: Mapped[EvalCategory] = mapped_column(Text)
    labels: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=empty_object_default())
    labeler: Mapped[str | None] = mapped_column(Text)
    checker: Mapped[str | None] = mapped_column(Text)
    # The active config of the page's site when it was captured, if any, to measure config fields (SPEC-03 §4.5).
    config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()


def eval_page_checks() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint(one_of("page_kind", PageKind), name="page_kind"),
        CheckConstraint(one_of("category", EvalCategory), name="category"),
        CheckConstraint("checker IS NULL OR (labeler IS NOT NULL AND checker <> labeler)", name="two_people"),
    )


class EvalRunColumns:
    """The `eval_run` columns both eval databases share (ARCHITECTURE §6). `git_sha` is plumbing for the baseline
    lookup (SPEC-03 §4.8): the latest run of a split whose commit is on `main`."""

    id: Mapped[EvalRunId] = mapped_column(primary_key=True, default=uuid7)
    split: Mapped[Split] = mapped_column(Text)
    engine_version: Mapped[str] = mapped_column(Text)
    git_sha: Mapped[str] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()


class EvalPage(EvalPageColumns, Base):
    """A labeled dev page (SPEC-03 §4.2). Hidden and fresh pages never enter this database (C1): the CHECK on
    `split` makes that structural."""

    __tablename__ = "eval_page"
    __table_args__ = (
        CheckConstraint("split = 'dev'", name="split"),
        *eval_page_checks(),
        # `schema_name` names the schema `schema_id` is.
        ForeignKeyConstraint(["schema_id", "schema_name"], [SchemaDef.id, SchemaDef.name]),
    )

    # A dev eval capture never expires (SPEC-01 §4.4); the reference keeps it from being deleted.
    capture_id: Mapped[CaptureId] = mapped_column(ForeignKey(Capture.id), index=True)


class EvalRun(EvalRunColumns, Base):
    """A dev evaluation run (SPEC-03 §4.2). Hidden and fresh runs are kept in the private database."""

    __tablename__ = "eval_run"
    __table_args__ = (CheckConstraint("split = 'dev'", name="split"),)
