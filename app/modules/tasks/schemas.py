"""Task input contracts never accept ownership or completion timestamps."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

TaskStatus = Literal["todo", "in_progress", "done"]
TaskPriority = Annotated[int, Field(strict=True, ge=1, le=3)]
TaskTitle = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200),
]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: TaskTitle
    description: str | None = None
    status: TaskStatus = "todo"
    priority: TaskPriority = 2
    due_at: AwareDatetime | None = None


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: TaskTitle | None = None
    description: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def reject_required_nulls(self) -> Self:
        for field in self.model_fields_set & {"title", "status", "priority"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    due_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
