"""Credential authentication and token-to-user resolution; no resource permissions."""

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AuthenticationError
from app.core.security import DUMMY_PASSWORD_HASH, verify_password
from app.core.tokens import decode_access_token
from app.modules.auth.schemas import TokenRequest
from app.modules.users.model import User


def authenticate_credentials(db: Session, data: TokenRequest) -> User:
    # Finish the read transaction before CPU-intensive password verification.
    with db.begin():
        user = db.scalar(select(User).where(User.email == str(data.email)))
    password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    valid = verify_password(data.password.get_secret_value(), password_hash)
    if user is None or not valid:
        raise AuthenticationError
    return user


def authenticate_token(db: Session, token: str, settings: Settings) -> User:
    try:
        subject = decode_access_token(token, settings)
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError from exc
    user = db.get(User, subject)
    if user is None:
        raise AuthenticationError
    return user
