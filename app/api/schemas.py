"""Shared list response contract."""

from pydantic import BaseModel, Field


class Page[T](BaseModel):
    items: list[T]
    limit: int
    offset: int


class ValidationDetail(BaseModel):
    type: str
    loc: list[str | int]
    msg: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ValidationDetail] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorBody
    request_id: str
