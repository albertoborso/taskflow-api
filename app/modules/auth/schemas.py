"""JSON login input and bearer-token output."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.modules.users.schemas import NormalizedEmail


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail
    password: SecretStr = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
