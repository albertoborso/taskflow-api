"""Task collection routes under projects and individual task routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from pydantic import AwareDatetime

from app.api.dependencies import CurrentUser, DatabaseSession, PaginationParams
from app.api.schemas import Page
from app.modules.tasks import service
from app.modules.tasks.schemas import TaskCreate, TaskResponse, TaskStatus, TaskUpdate

router = APIRouter(tags=["tasks"])


@router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    project_id: UUID, data: TaskCreate, user: CurrentUser, db: DatabaseSession
) -> TaskResponse:
    return TaskResponse.model_validate(
        service.create_task(db, user.id, project_id, data)
    )


@router.get("/projects/{project_id}/tasks", response_model=Page[TaskResponse])
def list_tasks(
    project_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
    page: PaginationParams,
    status: Annotated[TaskStatus | None, Query()] = None,
    priority: Annotated[int | None, Query(ge=1, le=3)] = None,
    due_before: Annotated[AwareDatetime | None, Query()] = None,
) -> Page[TaskResponse]:
    tasks = service.list_tasks(
        db, user.id, project_id, page.limit, page.offset, status, priority, due_before
    )
    return Page(
        items=[TaskResponse.model_validate(t) for t in tasks],
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def read_task(task_id: UUID, user: CurrentUser, db: DatabaseSession) -> TaskResponse:
    return TaskResponse.model_validate(service.get_task(db, user.id, task_id))


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: UUID, data: TaskUpdate, user: CurrentUser, db: DatabaseSession
) -> TaskResponse:
    return TaskResponse.model_validate(service.update_task(db, user.id, task_id, data))


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: UUID, user: CurrentUser, db: DatabaseSession) -> Response:
    service.delete_task(db, user.id, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
