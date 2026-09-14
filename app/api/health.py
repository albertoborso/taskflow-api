"""Process liveness endpoint."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import DatabaseSession
from app.api.schemas import ErrorResponse
from app.core.exceptions import ServiceUnavailableError

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    """Confirm that the application can serve requests."""
    return LivenessResponse()


class ReadinessResponse(BaseModel):
    status: Literal["ok"] = "ok"


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ErrorResponse, "description": "Database unavailable"}},
)
def ready(db: DatabaseSession) -> ReadinessResponse:
    """Execute a real database query before accepting traffic."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise ServiceUnavailableError from None
    return ReadinessResponse(status="ok")
