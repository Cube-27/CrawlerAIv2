"""SQLAlchemy models of the private eval database (ARCHITECTURE §6, SPEC-03 §4.2): hidden and fresh pages, their
captures and runs, and recorded LLM responses. Only the custodian role reaches this database (C1); its revisions are
in `migrations/private_versions` and run with `alembic -n private`.

It has no `site` or `schema_def`: hidden hosts must not enter the main database, so a capture carries its own host
and category, and a page its schema's id and name.
"""

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.db.models import (
    NAMING_CONVENTION,
    TYPE_ANNOTATION_MAP,
    CaptureId,
    EvalCategory,
    EvalPageColumns,
    EvalRunColumns,
    PrivateSplit,
    created_at_column,
    empty_object_default,
    eval_page_checks,
    one_of,
)


class PrivateBase(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = TYPE_ANNOTATION_MAP
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


_PRIVATE_SPLIT = one_of("split", PrivateSplit)


class EvalCapture(PrivateBase):
    """A hidden or fresh capture: the `capture` columns, with the site's host and category in place of `site_id`.
    The bundle is at `object_key` in the private object store. Eval captures never expire (ARCHITECTURE §15)."""

    __tablename__ = "eval_capture"
    __table_args__ = (
        CheckConstraint(_PRIVATE_SPLIT, name="split"),
        CheckConstraint("host = lower(host)", name="host_lowercase"),
        CheckConstraint(one_of("category", EvalCategory), name="category"),
        CheckConstraint(one_of("method", CaptureMethod), name="method"),
        CheckConstraint(one_of("block_class", BlockClass), name="block_class"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
        CheckConstraint("duration_ms >= 0", name="duration_ms_non_negative"),
        # The target of `eval_page`'s (`capture_id`, `split`) foreign key.
        UniqueConstraint("id", "split"),
    )

    id: Mapped[CaptureId] = mapped_column(primary_key=True)
    split: Mapped[PrivateSplit] = mapped_column(Text)
    host: Mapped[str] = mapped_column(Text)
    category: Mapped[EvalCategory] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    method: Mapped[CaptureMethod] = mapped_column(Text)
    status_code: Mapped[int] = mapped_column(Integer)
    final_url: Mapped[str] = mapped_column(Text)
    block_class: Mapped[BlockClass] = mapped_column(Text)
    object_key: Mapped[str] = mapped_column(Text, unique=True)
    html_sha256: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    duration_ms: Mapped[int] = mapped_column(Integer)
    fetch_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=empty_object_default())


class PrivateEvalPage(EvalPageColumns, PrivateBase):
    __tablename__ = "eval_page"
    __table_args__ = (
        CheckConstraint(_PRIVATE_SPLIT, name="split"),
        *eval_page_checks(),
        # A page belongs to the split of its capture.
        ForeignKeyConstraint(["capture_id", "split"], [EvalCapture.id, EvalCapture.split]),
    )

    capture_id: Mapped[CaptureId] = mapped_column(index=True)


class PrivateEvalRun(EvalRunColumns, PrivateBase):
    __tablename__ = "eval_run"
    __table_args__ = (CheckConstraint(_PRIVATE_SPLIT, name="split"),)


class EvalLlmCache(PrivateBase):
    """Recorded LLM responses of hidden and fresh replays (SPEC-03 §4.5). The response is the object at
    `object_key`; the row, written after the object, is what makes a key a hit."""

    __tablename__ = "eval_llm_cache"
    __table_args__ = (
        # sha256(role, model, prompt, schema) in hex (SPEC-03 §4.5).
        CheckConstraint("key ~ '^[0-9a-f]{64}$'", name="key_sha256"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
    )

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    object_key: Mapped[str] = mapped_column(Text, unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = created_at_column()
