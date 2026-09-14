"""Authenticated project CRUD."""

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.dependencies import CurrentUser, DatabaseSession, PaginationParams
from app.api.schemas import Page
from app.modules.projects import service
from app.modules.projects.schemas import ProjectCreate, ProjectResponse, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    data: ProjectCreate, user: CurrentUser, db: DatabaseSession
) -> ProjectResponse:
    return ProjectResponse.model_validate(service.create_project(db, user.id, data))


@router.get("", response_model=Page[ProjectResponse])
def list_projects(
    user: CurrentUser, db: DatabaseSession, page: PaginationParams
) -> Page[ProjectResponse]:
    projects = service.list_projects(db, user.id, page.limit, page.offset)
    return Page(
        items=[ProjectResponse.model_validate(p) for p in projects],
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
def read_project(
    project_id: UUID, user: CurrentUser, db: DatabaseSession
) -> ProjectResponse:
    return ProjectResponse.model_validate(service.get_project(db, user.id, project_id))


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: UUID, data: ProjectUpdate, user: CurrentUser, db: DatabaseSession
) -> ProjectResponse:
    return ProjectResponse.model_validate(
        service.update_project(db, user.id, project_id, data)
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: UUID, user: CurrentUser, db: DatabaseSession
) -> Response:
    service.delete_project(db, user.id, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
