"""
Add attribute_constraint and polymerization_medium to research_runs

Revision ID: a1b2c3d4e5f6
Revises: 63a11035b031
Create Date: 2026-09-03 16:35:00.000000+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "63a11035b031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "research_runs",
        sa.Column("attribute_constraint", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "research_runs",
        sa.Column(
            "polymerization_medium",
            sa.String(length=32),
            server_default="any",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("research_runs", "polymerization_medium")
    op.drop_column("research_runs", "attribute_constraint")
