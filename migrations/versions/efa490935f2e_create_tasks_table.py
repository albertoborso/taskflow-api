"""create tasks table

Revision ID: efa490935f2e
Revises: eb637f338f74
Create Date: 2026-09-13 15:38:00.233573

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "efa490935f2e"
down_revision: str | Sequence[str] | None = "eb637f338f74"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="todo", nullable=False
        ),
        sa.Column(
            "priority", sa.SmallInteger(), server_default=sa.text("2"), nullable=False
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'done' AND completed_at IS NOT NULL) OR "
            "(status <> 'done' AND completed_at IS NULL)",
            name=op.f("ck_tasks_completion_matches_status"),
        ),
        sa.CheckConstraint(
            "status IN ('todo', 'in_progress', 'done')",
            name=op.f("ck_tasks_valid_status"),
        ),
        sa.CheckConstraint(
            "length(btrim(title)) > 0", name=op.f("ck_tasks_title_not_blank")
        ),
        sa.CheckConstraint(
            "priority IN (1, 2, 3)", name=op.f("ck_tasks_valid_priority")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_tasks_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(
        "ix_tasks_project_created_id",
        "tasks",
        ["project_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_tasks_project_status_created_id",
        "tasks",
        ["project_id", "status", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_tasks_project_status_created_id", table_name="tasks")
    op.drop_index("ix_tasks_project_created_id", table_name="tasks")
    op.drop_table("tasks")
