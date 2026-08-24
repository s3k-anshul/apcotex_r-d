"""
app/models/research_run.py

Full ResearchRun ORM model with all Phase 2 fields.
Status lifecycle:
  PENDING → QUEUED → SEARCHING → FILTERING → EXTRACTING → GENERATING → COMPLETED
                                                                        → FAILED
                                                                        → CANCELLED
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.report_metadata import ReportMetadata
    from app.models.user import User
    from app.models.recipe_cycle import RecipeCycle


class RunStatus(str, Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    SEARCHING = "SEARCHING"
    FILTERING = "FILTERING"
    EXTRACTING = "EXTRACTING"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    COMPLETED_PARTIAL = "COMPLETED_PARTIAL"
    FAILED = "FAILED"
    LLM_PROVIDER_EXHAUSTED = "LLM_PROVIDER_EXHAUSTED"
    SEARCH_PROVIDER_UNAVAILABLE = "SEARCH_PROVIDER_UNAVAILABLE"
    NO_RELEVANT_PATENTS = "NO_RELEVANT_PATENTS"
    CANCELLED = "CANCELLED"
    PAUSED = "PAUSED"

    # Convenience helpers
    @classmethod
    def terminal_states(cls) -> set["RunStatus"]:
        return {cls.COMPLETED, cls.COMPLETED_PARTIAL, cls.FAILED, cls.CANCELLED, cls.LLM_PROVIDER_EXHAUSTED, cls.SEARCH_PROVIDER_UNAVAILABLE, cls.NO_RELEVANT_PATENTS}

    @classmethod
    def active_states(cls) -> set["RunStatus"]:
        return {cls.QUEUED, cls.SEARCHING, cls.FILTERING, cls.EXTRACTING, cls.GENERATING, cls.PAUSED}


class ResearchRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Represents a single patent-research / polymer-recipe research job.

    JSON fields store flexible, user-provided lists so the schema stays
    extensible without additional join tables.
    """

    __tablename__ = "research_runs"

    # ── Core fields ───────────────────────────────────────────────────────────
    compound_name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )

    # ── JSON payload fields ───────────────────────────────────────────────────
    competitors: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    mentioned_websites: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    website_evidences: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    publication_filter: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=None
    )
    selected_sources: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    jurisdictions: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )

    # ── Status & versioning ───────────────────────────────────────────────────
    status: Mapped[RunStatus] = mapped_column(
        SAEnum(RunStatus, name="runstatus", create_constraint=True),
        nullable=False,
        default=RunStatus.PENDING,
        server_default=RunStatus.PENDING.value,
        index=True,
    )
    cache_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True, unique=False
    )
    report_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    # ── Ownership ─────────────────────────────────────────────────────────────
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # ── Soft delete ───────────────────────────────────────────────────────────
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    creator: Mapped["User"] = relationship(
        "User", back_populates="research_runs"
    )
    reports: Mapped[list["ReportMetadata"]] = relationship(
        "ReportMetadata",
        back_populates="research_run",
        lazy="select",
        cascade="all, delete-orphan",
    )
    recipe_cycles: Mapped[list["RecipeCycle"]] = relationship(
        "RecipeCycle",
        back_populates="research_run",
        lazy="select",
        cascade="all, delete-orphan",
    )

    # ── Helpers ───────────────────────────────────────────────────────────────
    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def is_terminal(self) -> bool:
        return self.status in RunStatus.terminal_states()

    @property
    def is_active(self) -> bool:
        return self.status in RunStatus.active_states()

    def __repr__(self) -> str:
        return (
            f"<ResearchRun id={self.id} compound={self.compound_name!r} "
            f"status={self.status} v{self.report_version}>"
        )
