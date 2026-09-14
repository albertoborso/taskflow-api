"""Task queries enforce ownership through the parent project."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.exceptions import ResourceNotFoundError
from app.modules.projects.model import Project
from app.modules.projects.service import get_project
from app.modules.tasks.model import Task
from app.modules.tasks.schemas import TaskCreate, TaskStatus, TaskUpdate


def get_task(
    db: Session, owner_id: UUID, task_id: UUID, *, for_update: bool = False
) -> Task:
    query = (
        select(Task)
        .join(Project, Task.project_id == Project.id)
        .where(Task.id == task_id, Project.owner_id == owner_id)
    )
    if for_update:
        query = query.with_for_update(of=Task)
    task = db.scalar(query)
    if task is None:
        raise ResourceNotFoundError
    return task


def list_tasks(
    db: Session,
    owner_id: UUID,
    project_id: UUID,
    limit: int,
    offset: int,
    status: TaskStatus | None = None,
    priority: int | None = None,
    due_before: datetime | None = None,
) -> list[Task]:
    # Missing or foreign parents return 404 even when they have no tasks.
    get_project(db, owner_id, project_id)
    query = (
        select(Task)
        .join(Project, Task.project_id == Project.id)
        .where(Task.project_id == project_id, Project.owner_id == owner_id)
    )
    if status is not None:
        query = query.where(Task.status == status)
    if priority is not None:
        query = query.where(Task.priority == priority)
    if due_before is not None:
        query = query.where(Task.due_at < due_before)
    return list(
        db.scalars(
            query.order_by(Task.created_at.desc(), Task.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def create_task(
    db: Session, owner_id: UUID, project_id: UUID, data: TaskCreate
) -> Task:
    # Lock the parent so deletion cannot race the authorization check and INSERT.
    project = get_project(db, owner_id, project_id, for_update=True)
    task = Task(
        project_id=project.id,
        **data.model_dump(),
        completed_at=datetime.now(UTC) if data.status == "done" else None,
    )
    try:
        db.add(task)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    return task


def update_task(db: Session, owner_id: UUID, task_id: UUID, data: TaskUpdate) -> Task:
    # Serialize edits to prevent concurrent status changes using stale completion state.
    task = get_task(db, owner_id, task_id, for_update=True)
    try:
        changes = data.model_dump(exclude_unset=True)
        if "status" in changes and changes["status"] != task.status:
            task.completed_at = (
                datetime.now(UTC) if changes["status"] == "done" else None
            )
        for field, value in changes.items():
            setattr(task, field, value)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    return task


def delete_task(db: Session, owner_id: UUID, task_id: UUID) -> None:
    task = get_task(db, owner_id, task_id, for_update=True)
    try:
        db.delete(task)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
