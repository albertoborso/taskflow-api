"""Project queries always constrain access by the authenticated owner's UUID."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.exceptions import ResourceNotFoundError
from app.modules.projects.model import Project
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate


def get_project(
    db: Session, owner_id: UUID, project_id: UUID, *, for_update: bool = False
) -> Project:
    query = select(Project).where(
        Project.id == project_id, Project.owner_id == owner_id
    )
    if for_update:
        query = query.with_for_update()
    project = db.scalar(query)
    if project is None:
        raise ResourceNotFoundError
    return project


def list_projects(
    db: Session, owner_id: UUID, limit: int, offset: int
) -> list[Project]:
    return list(
        db.scalars(
            select(Project)
            .where(Project.owner_id == owner_id)
            .order_by(Project.created_at.desc(), Project.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def create_project(db: Session, owner_id: UUID, data: ProjectCreate) -> Project:
    project = Project(owner_id=owner_id, **data.model_dump())
    try:
        db.add(project)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    return project


def update_project(
    db: Session, owner_id: UUID, project_id: UUID, data: ProjectUpdate
) -> Project:
    project = get_project(db, owner_id, project_id, for_update=True)
    try:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(project, field, value)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    return project


def delete_project(db: Session, owner_id: UUID, project_id: UUID) -> None:
    project = get_project(db, owner_id, project_id, for_update=True)
    try:
        db.delete(project)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
