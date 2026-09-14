"""User registration, profile updates, and transaction ownership."""

from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.exceptions import DuplicateEmailError
from app.core.security import hash_password
from app.modules.users.model import User
from app.modules.users.schemas import UserCreate, UserProfileUpdate


def register_user(db: Session, data: UserCreate) -> User:
    # Hash before acquiring a connection or opening a transaction.
    user = User(
        email=str(data.email),
        password_hash=hash_password(data.password.get_secret_value()),
        display_name=data.display_name,
    )
    try:
        with db.begin():
            db.add(user)
            db.flush()
    except IntegrityError as exc:
        # The transaction context has rolled back before translating this error.
        if (
            isinstance(exc.orig, UniqueViolation)
            and exc.orig.diag.constraint_name == "uq_users_email"
        ):
            raise DuplicateEmailError from exc
        raise
    return user


def update_profile(db: Session, user: User, data: UserProfileUpdate) -> User:
    # The identity lookup has already opened this request session's transaction.
    # The service owns its commit/rollback; the dependency never commits.
    try:
        user.display_name = data.display_name
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    return user
