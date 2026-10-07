"""
Add saved_recipes table and extend customer_trials for recipe lifecycle.

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-09-22 23:50:00.000000+00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    savedrecipestatus = postgresql.ENUM(
        "ACTIVE", "EXPIRED", name="savedrecipestatus", create_type=False
    )
    savedrecipestatus.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "saved_recipes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("recipe_name", sa.String(length=255), nullable=False),
        sa.Column("recipe_data", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("target_properties", postgresql.JSON(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("competitor_properties", postgresql.JSON(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parent_recipe_id", sa.UUID(), nullable=True),
        sa.Column("revision_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("ACTIVE", "EXPIRED", name="savedrecipestatus", create_type=False),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("source_cycle_id", sa.UUID(), nullable=True),
        sa.Column("source_candidate_id", sa.UUID(), nullable=True),
        sa.Column("source_trial_id", sa.UUID(), nullable=True),
        sa.Column("source_optimized_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_recipe_id"], ["saved_recipes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_cycle_id"], ["recipe_cycles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_candidate_id"], ["recipe_candidates.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_trial_id"], ["customer_trials.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_optimized_id"], ["optimized_recipe_candidates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_saved_recipes_id", "saved_recipes", ["id"])
    op.create_index("ix_saved_recipes_recipe_name", "saved_recipes", ["recipe_name"])
    op.create_index("ix_saved_recipes_created_by", "saved_recipes", ["created_by"])
    op.create_index("ix_saved_recipes_updated_by", "saved_recipes", ["updated_by"])
    op.create_index("ix_saved_recipes_expires_at", "saved_recipes", ["expires_at"])
    op.create_index("ix_saved_recipes_parent_recipe_id", "saved_recipes", ["parent_recipe_id"])
    op.create_index("ix_saved_recipes_status", "saved_recipes", ["status"])
    op.create_index("ix_saved_recipes_source_cycle_id", "saved_recipes", ["source_cycle_id"])
    op.create_index("ix_saved_recipes_source_trial_id", "saved_recipes", ["source_trial_id"])

    # Make legacy FKs nullable; add saved-recipe link + snapshot
    op.alter_column("customer_trials", "cycle_id", existing_type=sa.UUID(), nullable=True)
    op.alter_column("customer_trials", "selected_candidate_id", existing_type=sa.UUID(), nullable=True)

    # Drop old RESTRICT/CASCADE FKs and recreate as SET NULL
    op.drop_constraint("customer_trials_cycle_id_fkey", "customer_trials", type_="foreignkey")
    op.drop_constraint("customer_trials_selected_candidate_id_fkey", "customer_trials", type_="foreignkey")
    op.create_foreign_key(
        "customer_trials_cycle_id_fkey",
        "customer_trials",
        "recipe_cycles",
        ["cycle_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "customer_trials_selected_candidate_id_fkey",
        "customer_trials",
        "recipe_candidates",
        ["selected_candidate_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("customer_trials", sa.Column("saved_recipe_id", sa.UUID(), nullable=True))
    op.add_column(
        "customer_trials",
        sa.Column("recipe_snapshot", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_customer_trials_saved_recipe_id", "customer_trials", ["saved_recipe_id"])
    op.create_foreign_key(
        "customer_trials_saved_recipe_id_fkey",
        "customer_trials",
        "saved_recipes",
        ["saved_recipe_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("customer_trials_saved_recipe_id_fkey", "customer_trials", type_="foreignkey")
    op.drop_index("ix_customer_trials_saved_recipe_id", table_name="customer_trials")
    op.drop_column("customer_trials", "recipe_snapshot")
    op.drop_column("customer_trials", "saved_recipe_id")

    op.drop_constraint("customer_trials_cycle_id_fkey", "customer_trials", type_="foreignkey")
    op.drop_constraint("customer_trials_selected_candidate_id_fkey", "customer_trials", type_="foreignkey")
    op.create_foreign_key(
        "customer_trials_cycle_id_fkey",
        "customer_trials",
        "recipe_cycles",
        ["cycle_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "customer_trials_selected_candidate_id_fkey",
        "customer_trials",
        "recipe_candidates",
        ["selected_candidate_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # Cannot easily re-nullify without data loss — leave nullable on downgrade
    op.drop_index("ix_saved_recipes_source_trial_id", table_name="saved_recipes")
    op.drop_index("ix_saved_recipes_source_cycle_id", table_name="saved_recipes")
    op.drop_index("ix_saved_recipes_status", table_name="saved_recipes")
    op.drop_index("ix_saved_recipes_parent_recipe_id", table_name="saved_recipes")
    op.drop_index("ix_saved_recipes_expires_at", table_name="saved_recipes")
    op.drop_index("ix_saved_recipes_updated_by", table_name="saved_recipes")
    op.drop_index("ix_saved_recipes_created_by", table_name="saved_recipes")
    op.drop_index("ix_saved_recipes_recipe_name", table_name="saved_recipes")
    op.drop_index("ix_saved_recipes_id", table_name="saved_recipes")
    op.drop_table("saved_recipes")
    op.execute("DROP TYPE IF EXISTS savedrecipestatus")
