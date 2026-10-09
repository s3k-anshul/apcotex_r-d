"""
app/models/recipe_candidate.py

RecipeCandidate — one of the 5 LLM-generated recipe proposals within a RecipeCycle.
"""
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.recipe_cycle import RecipeCycle


class RecipeCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    One LLM-generated recipe proposal. Exactly 5 exist per RecipeCycle (generated once).

    recipe_data JSON shape (all fields from LLM):
    {
      "name": "Recipe 1",
      "bd_acn_ratio": "74/26",
      "polymerization_method": "Cold Emulsion",
      "temperature": "10°C",
      "water": "185 phr",
      "emulsifier": {"name": "...", "loading": "...", "source": "patent|inferred"},
      "initiator": {"name": "...", "loading": "...", "source": "patent|inferred"},
      "chain_transfer_agent": {"name": "...", "loading": "...", "source": "patent|inferred"},
      "coagulant": "...",
      "conversion": "88%",
      "reaction_time": "...",
      "expected_bound_acn": "24.5%",
      "expected_mooney": "47",
      "expected_properties": {...},
      "parameters": [{"name": ..., "value": ..., "unit": ..., "source": "patent|inferred", "patent_ref": "US..."}],
      "patent_references": ["US...", "EP..."],
      "rationale": "...",
      "notes": "..."
    }
    """
    __tablename__ = "recipe_candidates"

    cycle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recipe_cycles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    rank: Mapped[int] = mapped_column(Integer, nullable=False)  # 1–5
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # Recipe name or candidate title

    # Full structured recipe from LLM
    recipe_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Patent numbers referenced by this recipe
    patent_references: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")

    # Deterministic coverage: (# patent-backed params / total params) * 100
    evidence_coverage_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    # ── Relationships ─────────────────────────────────────────────────────────
    cycle: Mapped["RecipeCycle"] = relationship("RecipeCycle", back_populates="candidates")

    def __repr__(self) -> str:
        return f"<RecipeCandidate id={self.id} cycle={self.cycle_id} rank={self.rank} selected={self.is_selected}>"
