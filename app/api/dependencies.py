"""Request-scoped database dependency."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.exceptions import AuthenticationError
from app.modules.auth.service import authenticate_token
from app.modules.users.model import User


def get_db(request: Request) -> Iterator[Session]:
    factory = cast(sessionmaker[Session], request.app.state.session_factory)
    with factory() as session:
        yield session


DatabaseSession = Annotated[Session, Depends(get_db)]


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


AppSettings = Annotated[Settings, Depends(get_settings)]
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    db: DatabaseSession,
    settings: AppSettings,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise AuthenticationError
    return authenticate_token(db, credentials.credentials, settings)


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass(frozen=True)
class Pagination:
    limit: int
    offset: int


def get_pagination(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


PaginationParams = Annotated[Pagination, Depends(get_pagination)]
