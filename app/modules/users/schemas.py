"""Registration input and public user output contracts."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
)


def normalize_email(value: str) -> str:
    """Treat the entire validated email as case-insensitive account identity."""
    return value.lower()


NormalizedEmail = Annotated[EmailStr, AfterValidator(normalize_email)]
DisplayName = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100),
]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail
    password: SecretStr = Field(min_length=15, max_length=128)
    display_name: DisplayName

    @field_validator("password")
    @classmethod
    def reject_blank_password(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Password must not be blank")
        return value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    display_name: str
    created_at: datetime
    updated_at: datetime


class UserProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: DisplayName
