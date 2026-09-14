"""Project request validation and public responses."""

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

ProjectName = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=150),
]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProjectName
    description: str | None = None


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProjectName | None = None
    description: str | None = None

    @model_validator(mode="after")
    def reject_null_name(self) -> Self:
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Name cannot be null")
        return self


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
