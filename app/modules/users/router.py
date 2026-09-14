"""User registration and authenticated current-user profile endpoints."""

from fastapi import APIRouter, status

from app.api.dependencies import CurrentUser, DatabaseSession
from app.api.schemas import ErrorResponse
from app.modules.users.schemas import UserCreate, UserProfileUpdate, UserResponse
from app.modules.users.service import register_user, update_profile

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponse, "description": "Email already registered"}
    },
)
def create_user(data: UserCreate, db: DatabaseSession) -> UserResponse:
    user = register_user(db, data)
    return UserResponse.model_validate(user)


@router.get("/me", response_model=UserResponse)
def read_profile(current_user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse)
def patch_profile(
    data: UserProfileUpdate, current_user: CurrentUser, db: DatabaseSession
) -> UserResponse:
    # The target comes from the authenticated identity, never a client-supplied ID.
    user = update_profile(db, current_user, data)
    return UserResponse.model_validate(user)
