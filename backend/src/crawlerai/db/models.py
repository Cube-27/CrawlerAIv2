"""SQLAlchemy models of the main database (ARCHITECTURE §6, SPEC-01 §4.2). The models and the Alembic revisions own
the DB shape; `tests/db` checks that the migrated database matches these models.

Enumerations are `text` with a CHECK constraint whose values come from the matching `Literal`.
"""

import uuid
from datetime import datetime
from typing import Any, ClassVar, Final, Literal, NewType, get_args

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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
_SET_NULL: Final = "SET NULL"

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
ScheduleId = NewType("ScheduleId", uuid.UUID)
WebhookEventId = NewType("WebhookEventId", uuid.UUID)
WebhookDeliveryId = NewType("WebhookDeliveryId", uuid.UUID)

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
# `derived`: a page-URL derivation (SPEC-05 §4.8, D-0355), which no candidate states; no candidate row carries it.
SourceKind = Literal[
    "adapter", "api", "jsonld", "microdata", "og", "js_state", "xhr", "config", "llm", "derived", "dom"
]
# `pending_approval`: a learned config waiting for a person to approve it (`project.require_config_approval`, D-1342).
ConfigStatus = Literal["draft", "active", "suspended", "pending_approval"]
ConfigOrigin = Literal["adapter", "induced", "llm_synth", "operator"]
# `extraction_config.field_status` values (ARCHITECTURE §6, §8.3 step 4).
FieldStatus = Literal["corroborated", "uncorroborated", "operator", "suspended", "absent"]
ProgressiveMode = Literal["cold", "learning", "active"]
# What `usage_event` counts (SPEC-01 §4.6), each in whole units: calls, tokens, seconds, bytes, requests.
UsageResource = Literal[
    "llm_calls", "llm_tokens_in", "llm_tokens_out", "browser_seconds", "proxy_bytes", "http_requests"
]
# The one evaluation split, the golden set (evaluation spec, "One split, grown in fresh batches"), and the
# stratification categories.
Split = Literal["dev"]
EvalCategory = Literal["platform_store", "custom_store", "api_backed", "job_board", "mixed"]
WebhookStatus = Literal["pending", "delivered", "failed"]
# What a job's webhook can be sent (`crawlerai.db.webhook_outbox`): a page its task finished, a record a task stored
# (and, for a new version, `record_changed`), a URL a recurring crawl no longer finds, and the job's end.
WebhookEventType = Literal[
    "page", "record", "record_changed", "url_gone", "job_completed", "job_failed", "job_cancelled"
]
# The job kinds a schedule submits (`crawlerai.services.schedules`): those the queue runs; a scheduled scrape is stored
# as the batch of its one URL.
ScheduledKind = Literal["batch_scrape", "crawl", "extract"]


def one_of(column: str, values: Any) -> str:
    """The CHECK expression restricting `column` to the members of a `Literal`."""
    return f"{column} IN ({', '.join(repr(value) for value in get_args(values))})"


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
        ScheduleId,
        WebhookEventId,
        WebhookDeliveryId,
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
    __table_args__ = (
        CheckConstraint("llm_call_cap >= 0", name="llm_call_cap_non_negative"),
        CheckConstraint("draft_call_cap >= 0", name="draft_call_cap_non_negative"),
    )

    id: Mapped[ProjectId] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = created_at_column()
    # The most LLM calls a job of the project may make when its request sets no `budget.llm_calls`; NULL: no cap
    # (owner, 2026-10-16).
    llm_call_cap: Mapped[int | None] = mapped_column(Integer)
    # The most uncharged role S calls (field-name drafts) one API key may make, in all; NULL: no cap (D-1282).
    draft_call_cap: Mapped[int | None] = mapped_column(Integer)
    # Whether a learned config waits for approval before it serves (D-1342); off: it activates once validated.
    require_config_approval: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class ApiKey(Base):
    __tablename__ = "api_key"
    __table_args__ = (CheckConstraint("draft_calls >= 0", name="draft_calls_non_negative"),)

    id: Mapped[ApiKeyId] = mapped_column(primary_key=True, default=uuid7)
    hashed_key: Mapped[str] = mapped_column(Text, unique=True)
    label: Mapped[str] = mapped_column(Text)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    webhook_secret: Mapped[str] = mapped_column(Text)
    # The uncharged role S calls the key has made (`llm.drafts.take_draft_call`); `project.draft_call_cap` bounds it.
    draft_calls: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))


class Site(Base):
    __tablename__ = "site"
    __table_args__ = (
        CheckConstraint("host = lower(host)", name="host_lowercase"),
        CheckConstraint("crawl_delay_ms >= 0", name="crawl_delay_ms_non_negative"),
    )

    id: Mapped[SiteId] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[ProjectId] = mapped_column(ForeignKey(Project.id))
    host: Mapped[str] = mapped_column(Text, unique=True)
    platform: Mapped[str | None] = mapped_column(Text)
    proxy_pool: Mapped[str | None] = mapped_column(Text)
    robots_snapshot: Mapped[str | None] = mapped_column(Text)
    crawl_delay_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_column()
    # The adapters that declined the host (`adapters.registry`, SPEC-15 §4.2), each with the time (ISO 8601, UTC) until
    # which it is not asked again (D-1384).
    adapter_declined: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=empty_object_default())
    # Whether the browser rung loads the site's images, fonts and media (`FetchPolicy.block_resources`): set once a
    # render of its listing with them blocked listed fewer items than its HTTP page (master plan 2026-10-18 §3.1).
    load_all_resources: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class SiteFetchMethod(Base):
    """The fetch method a site's pages of one kind are remembered to need (SPEC-02 §4.4, D-1380): a row once a fetch of
    that kind kept a browser `ok` over HTTP; no row is `http`. `checked_at` starts the re-check's clock."""

    __tablename__ = "site_fetch_method"
    __table_args__ = (
        CheckConstraint(one_of("page_kind", PageKind), name="page_kind"),
        CheckConstraint(one_of("method", FetchMethod), name="method"),
    )

    site_id: Mapped[SiteId] = mapped_column(ForeignKey(Site.id), primary_key=True)
    page_kind: Mapped[PageKind] = mapped_column(Text, primary_key=True)
    method: Mapped[FetchMethod] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SchemaDef(Base):
    __tablename__ = "schema_def"
    __table_args__ = (
        # The target of `eval_page`'s (`schema_id`, `schema_name`) foreign key.
        UniqueConstraint("id", "name"),
        CheckConstraint(one_of("page_kind", PageKind), name="page_kind"),
        CheckConstraint(one_of("origin", SchemaOrigin), name="origin"),
        CheckConstraint(one_of("status", SchemaStatus), name="status"),
    )

    id: Mapped[SchemaId] = mapped_column(primary_key=True, default=uuid7)
    # One row per schema, edited in place (ARCHITECTURE §5.2).
    name: Mapped[str] = mapped_column(Text, unique=True)
    page_kind: Mapped[PageKind] = mapped_column(Text)
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB)
    required_groups: Mapped[list[list[str]]] = mapped_column(JSONB, server_default=empty_array_default())
    origin: Mapped[SchemaOrigin] = mapped_column(Text)
    status: Mapped[SchemaStatus] = mapped_column(Text)
    # Role S's drafted label synonyms by field (`schemas.types.SchemaDef.labels`); null until drafted.
    labels: Mapped[dict[str, list[str]] | None] = mapped_column(JSONB)


class Capture(Base):
    """A fetched page, whose bytes are the bundle at `object_key` (ARCHITECTURE §15): a production or an eval
    capture."""

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
    schema_id: Mapped[SchemaId] = mapped_column(ForeignKey(SchemaDef.id))
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
    """How far a (site, schema, page kind) is on the way to an active config (ARCHITECTURE §8.4)."""

    __tablename__ = "progressive_state"
    __table_args__ = (
        CheckConstraint(one_of("page_kind", PageKind), name="page_kind"),
        CheckConstraint(one_of("mode", ProgressiveMode), name="mode"),
        CheckConstraint("pages_extracted >= 0", name="pages_extracted_non_negative"),
        CheckConstraint("mode <> 'learning' OR learning_started_at IS NOT NULL", name="learning_has_started"),
        CheckConstraint("mode <> 'active' OR active_config_id IS NOT NULL", name="active_has_config"),
        CheckConstraint("retry_at_pages >= 0", name="retry_at_pages_non_negative"),
    )

    site_id: Mapped[SiteId] = mapped_column(ForeignKey(Site.id), primary_key=True)
    schema_id: Mapped[SchemaId] = mapped_column(ForeignKey(SchemaDef.id), primary_key=True)
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
    # The page's visible text (`recurring.simhash`): the exact digest of its words, which alone decides `unchanged`
    # (D-1340), and their SimHash as 16 hex digits, which says how far a change moved.
    content_digest: Mapped[str | None] = mapped_column(Text)
    content_fingerprint: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    missing_runs: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    gone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The crawl whose listing last held the URL (SPEC-11 §4.5); NULL while no listing has.
    last_seen_job_id: Mapped[JobId | None] = mapped_column(ForeignKey("job.id", ondelete=_SET_NULL))
    # The task whose records a listing page last stood for after extracting it (`recurring.state.standing_listing`):
    # the page's standing record, as that task's `task_record` rows. NULL for a detail page, found by its entity.
    standing_task_id: Mapped[UrlTaskId | None] = mapped_column(ForeignKey("url_task.id", ondelete=_SET_NULL))


class Schedule(Base):
    """A recurring run (§22 "Recurring schedule storage", admitted 2026-10-17): the request of a queued job kind,
    submitted by the scheduler at each due time of its 5-field cron expression in `timezone`, or every `interval_s`.
    Its jobs point back at it (`job.schedule_id`); the last one is its newest."""

    __tablename__ = "schedule"
    __table_args__ = (
        CheckConstraint(one_of("kind", ScheduledKind), name="kind"),
        CheckConstraint("(cron IS NULL) <> (interval_s IS NULL)", name="one_cadence"),
        CheckConstraint("interval_s >= 60", name="interval_at_least_a_minute"),
        # The scheduler reads the due schedules that are not paused.
        Index(None, "next_run_at", postgresql_where=text("NOT paused")),
    )

    id: Mapped[ScheduleId] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[ProjectId] = mapped_column(ForeignKey(Project.id))
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[ScheduledKind] = mapped_column(Text)
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)
    cron: Mapped[str | None] = mapped_column(Text)
    interval_s: Mapped[int | None] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(Text)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paused: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Why its last due run submitted no job (a refused target, globs that matched nothing); NULL once one is submitted.
    last_error: Mapped[str | None] = mapped_column(Text)
    # The key that created it: its jobs are submitted as that key's, which signs their webhooks.
    api_key_id: Mapped[ApiKeyId | None] = mapped_column(ForeignKey(ApiKey.id))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = created_at_column()


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (
        CheckConstraint(one_of("kind", JobKind), name="kind"),
        CheckConstraint(one_of("status", JobStatus), name="status"),
        # The scheduler's reapers look only at running jobs, oldest start first (`db.queue.reap_stuck_jobs`).
        Index(None, "started_at", postgresql_where=text("status = 'running'")),
        # A schedule's jobs, newest first (its history and its last job).
        Index(None, "schedule_id", "id"),
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
    # A crawl: where its start page is, canonical, after the site's own redirects (`crawl.rules.located`). The start
    # task writes it: it gives the scope's host and the one URL already fetched. NULL before then, and for other kinds.
    start_location: Mapped[str | None] = mapped_column(Text)
    # The events its webhook is sent (`WebhookEventType`) and how they are grouped into deliveries
    # (`crawlerai.db.webhook_outbox.WebhookBatch`, NULL: one event a delivery), from the request.
    webhook_events: Mapped[list[str]] = mapped_column(JSONB, server_default=empty_array_default())
    webhook_batch: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # The schedule that submitted it; NULL for a job a caller submitted, and once its schedule is deleted.
    schedule_id: Mapped[ScheduleId | None] = mapped_column(ForeignKey(Schedule.id, ondelete=_SET_NULL))


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
        # A job's settled tasks by outcome, for the listing of a large crawl (`services.jobs`).
        Index(None, "job_id", "status", "outcome"),
        # A job's tasks in id order, which its results and its records page by (keyset, `db.paging`).
        Index(None, "job_id", "id"),
        # A crawl takes no URL a task of the job was already fetched at (`crawl.frontier`, D-1382).
        Index(None, "job_id", "final_url", postgresql_where=text("final_url IS NOT NULL")),
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
    # Where the task's page was fetched, after its redirects, in canonical form (`normalize.url_key`); NULL until then.
    final_url: Mapped[str | None] = mapped_column(Text)
    # A crawl's lease order within its priority, higher first (`crawl.scoring`); NULL (breadth first) leases after it.
    score: Mapped[float | None] = mapped_column(Float)


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
    """One POST of a job's webhook (SPEC-10 §4.2): the events assigned to it, `pending` until the target accepts it or
    its attempts run out (`crawlerai.api.webhooks`)."""

    __tablename__ = "webhook_delivery"
    __table_args__ = (
        CheckConstraint(one_of("status", WebhookStatus), name="status"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        # The scheduler reads the pending deliveries that are due.
        Index(None, "next_attempt_at", postgresql_where=text("status = 'pending'")),
        Index(None, "job_id"),
        # Retention reads the ended deliveries, oldest first (`scheduler.retention.expire_webhooks`).
        Index(None, "created_at", postgresql_where=text("status <> 'pending'")),
    )

    id: Mapped[WebhookDeliveryId] = mapped_column(primary_key=True, default=uuid7)
    job_id: Mapped[JobId] = mapped_column(ForeignKey(Job.id))
    status: Mapped[WebhookStatus] = mapped_column(Text, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    # The HTTP status the target answered the last attempt with; NULL before one, or when it gave no response.
    response_code: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_column()


class WebhookEvent(Base):
    """An event a job's webhook is owed, written in the transaction that makes it happen (the outbox): it waits
    unassigned until the scheduler groups it into a delivery (`crawlerai.db.webhook_outbox`)."""

    __tablename__ = "webhook_event"
    __table_args__ = (
        CheckConstraint(one_of("event", WebhookEventType), name="event"),
        # The scheduler groups each job's unassigned events, oldest first.
        Index(None, "job_id", "id", postgresql_where=text("delivery_id IS NULL")),
        # A delivery's events, in order, for its body.
        Index(None, "delivery_id", "id"),
    )

    id: Mapped[WebhookEventId] = mapped_column(primary_key=True, default=uuid7)
    job_id: Mapped[JobId] = mapped_column(ForeignKey(Job.id))
    event: Mapped[WebhookEventType] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=empty_object_default())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    delivery_id: Mapped[WebhookDeliveryId | None] = mapped_column(ForeignKey(WebhookDelivery.id))


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
        CheckConstraint(one_of("mode", ExtractionMode), name="mode"),
        version_positive(),
        # Recurring runs compare fingerprints per (site, entity, schema) (SPEC-11 §4.4), and find the newest record that
        # stands for a page, by id (`recurring.state.standing_record`).
        Index(None, "site_id", "entity_key", "schema_id", "id"),
        # The change feed (`changed_since`), and the commit stamp of the baseline migration's trigger.
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
    schema_id: Mapped[SchemaId] = mapped_column(ForeignKey(SchemaDef.id))
    entity_key: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    field_meta: Mapped[dict[str, Any]] = mapped_column(JSONB)
    complete: Mapped[bool] = mapped_column(Boolean)
    changed_fields: Mapped[list[str]] = mapped_column(JSONB, server_default=empty_array_default())
    mode: Mapped[ExtractionMode] = mapped_column(Text)
    fingerprint: Mapped[str | None] = mapped_column(Text)
    # The digest of the schema document the record was extracted with (`schemas.types.document_digest`): a
    # schema is edited in place (ARCHITECTURE §5.2), so a record follows the current document only when it is equal.
    schema_digest: Mapped[str] = mapped_column(Text)
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
    # When the task stood for the record (`recurring.state.standing_record`).
    created_at: Mapped[datetime] = created_at_column()


class EvalPage(Base):
    """A page of the golden set (ARCHITECTURE §6). `labels` is the label document (`crawlerai.eval.labels`); `labeler`
    and `checker` are the two passes, which must be different people. `schema_name` names the schema `schema_id` is,
    so pages are listed by schema name."""

    __tablename__ = "eval_page"
    __table_args__ = (
        CheckConstraint("split = 'dev'", name="split"),
        CheckConstraint(one_of("page_kind", PageKind), name="page_kind"),
        CheckConstraint(one_of("category", EvalCategory), name="category"),
        CheckConstraint("checker IS NULL OR (labeler IS NOT NULL AND checker <> labeler)", name="two_people"),
        ForeignKeyConstraint(["schema_id", "schema_name"], [SchemaDef.id, SchemaDef.name]),
    )

    id: Mapped[EvalPageId] = mapped_column(primary_key=True, default=uuid7)
    split: Mapped[Split] = mapped_column(Text)
    schema_id: Mapped[SchemaId] = mapped_column()
    schema_name: Mapped[str] = mapped_column(Text)
    page_kind: Mapped[PageKind] = mapped_column(Text)
    category: Mapped[EvalCategory] = mapped_column(Text)
    labels: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=empty_object_default())
    labeler: Mapped[str | None] = mapped_column(Text)
    checker: Mapped[str | None] = mapped_column(Text)
    # The active config of the page's site when it was captured, if any, to measure config fields.
    config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()
    # An eval capture never expires (SPEC-01 §4.4); the reference keeps it from being deleted.
    capture_id: Mapped[CaptureId] = mapped_column(ForeignKey(Capture.id), index=True)


class EvalRun(Base):
    """A stored evaluation run (ARCHITECTURE §6): the report of checked pages that calibration fits on."""

    __tablename__ = "eval_run"
    __table_args__ = (CheckConstraint("split = 'dev'", name="split"),)

    id: Mapped[EvalRunId] = mapped_column(primary_key=True, default=uuid7)
    split: Mapped[Split] = mapped_column(Text)
    engine_version: Mapped[str] = mapped_column(Text)
    git_sha: Mapped[str] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()
