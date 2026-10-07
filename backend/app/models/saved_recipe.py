"""
app/models/saved_recipe.py

Persistent saved recipes / revisions with six-month retention.
Distinct from transient RecipeCandidate / OptimizedRecipeCandidate rows.
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.customer_trial import CustomerTrial


class SavedRecipeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class SavedRecipeKind(str, Enum):
    """NORMAL = simulator save. OPTIMIZED = child produced from trial feedback."""

    NORMAL = "NORMAL"
    OPTIMIZED = "OPTIMIZED"


class SavedRecipe(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    User-persisted recipe (original or revision).

    Original: parent_recipe_id=NULL, revision_number=0
    Revision: parent_recipe_id=<original.id>, revision_number>=1
    """

    __tablename__ = "saved_recipes"

    recipe_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Exact recipe payload submitted by the user (edited values must win)
    recipe_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    target_properties: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    competitor_properties: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )

    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    parent_recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("saved_recipes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    revision_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Distinguishes simulator saves from feedback-driven optimized children.
    recipe_kind: Mapped[SavedRecipeKind] = mapped_column(
        SAEnum(SavedRecipeKind, name="savedrecipekind", create_constraint=True),
        nullable=False,
        default=SavedRecipeKind.NORMAL,
        server_default=SavedRecipeKind.NORMAL.value,
        index=True,
    )

    status: Mapped[SavedRecipeStatus] = mapped_column(
        SAEnum(SavedRecipeStatus, name="savedrecipestatus", create_constraint=True),
        nullable=False,
        default=SavedRecipeStatus.ACTIVE,
        server_default=SavedRecipeStatus.ACTIVE.value,
        index=True,
    )

    # Optional provenance (generation session)
    source_cycle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recipe_cycles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recipe_candidates.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Feedback that caused this revision (NULL for originals)
    source_trial_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_trials.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_optimized_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("optimized_recipe_candidates.id", ondelete="SET NULL"),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    creator: Mapped["User"] = relationship("User", foreign_keys=[created_by])
    updater: Mapped[Optional["User"]] = relationship("User", foreign_keys=[updated_by])
    parent: Mapped[Optional["SavedRecipe"]] = relationship(
        "SavedRecipe",
        remote_side="SavedRecipe.id",
        foreign_keys=[parent_recipe_id],
        back_populates="revisions",
    )
    revisions: Mapped[list["SavedRecipe"]] = relationship(
        "SavedRecipe",
        back_populates="parent",
        foreign_keys=[parent_recipe_id],
    )
    source_trial: Mapped[Optional["CustomerTrial"]] = relationship(
        "CustomerTrial",
        foreign_keys=[source_trial_id],
    )

    def __repr__(self) -> str:
        return (
            f"<SavedRecipe id={self.id} name={self.recipe_name!r} "
            f"rev={self.revision_number} expires={self.expires_at}>"
        )
