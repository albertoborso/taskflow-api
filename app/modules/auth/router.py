"""Email/password exchange for a short-lived bearer access token."""

from fastapi import APIRouter, Response

from app.api.dependencies import AppSettings, DatabaseSession
from app.core.tokens import create_access_token
from app.modules.auth.schemas import TokenRequest, TokenResponse
from app.modules.auth.service import authenticate_credentials

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
def issue_token(
    data: TokenRequest, db: DatabaseSession, settings: AppSettings, response: Response
) -> TokenResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    user = authenticate_credentials(db, data)
    return TokenResponse(
        access_token=create_access_token(user.id, settings),
        expires_in=settings.access_token_minutes * 60,
    )
