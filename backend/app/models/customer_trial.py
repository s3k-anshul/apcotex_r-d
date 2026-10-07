"""
app/models/customer_trial.py

CustomerTrial — records feedback and actual results from a trial of a selected recipe candidate.
"""
import uuid
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Enum as SAEnum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.recipe_cycle import RecipeCycle
    from app.models.optimized_recipe_candidate import OptimizedRecipeCandidate
    from app.models.saved_recipe import SavedRecipe


class TrialStatus(str, Enum):
    PENDING = "PENDING"
    OPTIMIZING = "OPTIMIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CustomerTrial(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A customer trial record.

    Legacy path: attached to RecipeCycle + RecipeCandidate.
    New path: attached to a persistent SavedRecipe (cycle/candidate optional).
    Scientific feedback fields (feedback_text, actual_values, target_values) are unchanged.
    """
    __tablename__ = "customer_trials"

    cycle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recipe_cycles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    selected_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recipe_candidates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Persistent saved recipe this feedback was submitted against.
    # ON DELETE SET NULL — recipe expiry must not destroy historical feedback.
    saved_recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("saved_recipes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Snapshot of recipe at feedback time (survives recipe deletion)
    recipe_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    status: Mapped[TrialStatus] = mapped_column(
        SAEnum(TrialStatus, name="trialstatus", create_constraint=True),
        nullable=False,
        default=TrialStatus.PENDING,
        server_default=TrialStatus.PENDING.value,
        index=True,
    )

    feedback_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # {feature_name: actual_value}
    actual_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="'{}'")

    # {feature_name: target_value}
    target_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="'{}'")

    # Which optimized revision was chosen
    selected_optimized_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    cycle: Mapped[Optional["RecipeCycle"]] = relationship("RecipeCycle", back_populates="trials")
    creator: Mapped["User"] = relationship("User", foreign_keys=[created_by])
    saved_recipe: Mapped[Optional["SavedRecipe"]] = relationship(
        "SavedRecipe",
        foreign_keys=[saved_recipe_id],
    )
    optimized_candidates: Mapped[list["OptimizedRecipeCandidate"]] = relationship(
        "OptimizedRecipeCandidate",
        back_populates="trial",
        cascade="all, delete-orphan",
        order_by="OptimizedRecipeCandidate.revision_label",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<CustomerTrial id={self.id} cycle={self.cycle_id} status={self.status}>"
