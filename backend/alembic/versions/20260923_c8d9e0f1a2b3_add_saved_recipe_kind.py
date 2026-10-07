"""Add saved_recipes.recipe_kind (NORMAL vs OPTIMIZED).

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8d9e0f1a2b3"
down_revision: str | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    kind = postgresql.ENUM("NORMAL", "OPTIMIZED", name="savedrecipekind", create_type=False)
    kind.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "saved_recipes",
        sa.Column(
            "recipe_kind",
            kind,
            nullable=False,
            server_default="NORMAL",
        ),
    )
    op.create_index("ix_saved_recipes_recipe_kind", "saved_recipes", ["recipe_kind"])
    # Existing feedback-driven revisions are optimized recipes.
    op.execute(
        """
        UPDATE saved_recipes
        SET recipe_kind = 'OPTIMIZED'
        WHERE source_trial_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_saved_recipes_recipe_kind", table_name="saved_recipes")
    op.drop_column("saved_recipes", "recipe_kind")
    postgresql.ENUM(name="savedrecipekind").drop(op.get_bind(), checkfirst=True)
