"""Tasks inherit access from their parent project."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint(
            "status IN ('todo', 'in_progress', 'done')", name="valid_status"
        ),
        CheckConstraint("priority IN (1, 2, 3)", name="valid_priority"),
        CheckConstraint(
            "(status = 'done' AND completed_at IS NOT NULL) OR "
            "(status <> 'done' AND completed_at IS NULL)",
            name="completion_matches_status",
        ),
        Index("ix_tasks_project_created_id", "project_id", "created_at", "id"),
        Index(
            "ix_tasks_project_status_created_id",
            "project_id",
            "status",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), server_default="todo", nullable=False
    )
    priority: Mapped[int] = mapped_column(
        SmallInteger, server_default=text("2"), nullable=False
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
