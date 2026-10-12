"""SQLAlchemy models of the main database (ARCHITECTURE §6, SPEC-01 §4.2). The models and the Alembic revisions own
the DB shape; `tests/db` checks that the migrated database matches these models.

Enumerations are `text` with a CHECK constraint whose values come from the matching `Literal`.
"""

import uuid
from datetime import datetime
from typing import Any, ClassVar, Literal, NewType, get_args

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from crawlerai.core.ids import uuid7

ProjectId = NewType("ProjectId", uuid.UUID)
ApiKeyId = NewType("ApiKeyId", uuid.UUID)
SiteId = NewType("SiteId", uuid.UUID)
SchemaId = NewType("SchemaId", uuid.UUID)

FetchMethod = Literal["http", "browser"]
PageKind = Literal["detail", "listing"]
SchemaOrigin = Literal["preset", "user", "prompt_draft"]
SchemaStatus = Literal["active", "retired"]


def _one_of(column: str, values: Any) -> str:
    """The CHECK expression restricting `column` to the members of a `Literal`."""
    return f"{column} IN ({', '.join(repr(value) for value in get_args(values))})"


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {ProjectId: Uuid, ApiKeyId: Uuid, SiteId: Uuid, SchemaId: Uuid}
    metadata = MetaData(
        naming_convention={
            "pk": "pk_%(table_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        }
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    __tablename__ = "project"

    id: Mapped[ProjectId] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = _created_at()


class ApiKey(Base):
    __tablename__ = "api_key"

    id: Mapped[ApiKeyId] = mapped_column(primary_key=True, default=uuid7)
    hashed_key: Mapped[str] = mapped_column(Text, unique=True)
    label: Mapped[str] = mapped_column(Text)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    webhook_secret: Mapped[str] = mapped_column(Text)


class Site(Base):
    __tablename__ = "site"
    __table_args__ = (
        CheckConstraint("host = lower(host)", name="host_lowercase"),
        CheckConstraint(_one_of("fetch_method", FetchMethod), name="fetch_method"),
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
    created_at: Mapped[datetime] = _created_at()
    fetch_method_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SchemaDef(Base):
    __tablename__ = "schema_def"
    __table_args__ = (
        UniqueConstraint("name", "version"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(_one_of("page_kind", PageKind), name="page_kind"),
        CheckConstraint(_one_of("origin", SchemaOrigin), name="origin"),
        CheckConstraint(_one_of("status", SchemaStatus), name="status"),
    )

    id: Mapped[SchemaId] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    page_kind: Mapped[PageKind] = mapped_column(Text)
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB)
    required_groups: Mapped[list[list[str]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    origin: Mapped[SchemaOrigin] = mapped_column(Text)
    status: Mapped[SchemaStatus] = mapped_column(Text)
