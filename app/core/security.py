"""Argon2id password hashing and verification."""

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

_password_hasher = PasswordHasher(type=Type.ID)


def hash_password(password: str) -> str:
    """Generate an Argon2id hash with a fresh library-generated random salt."""
    return _password_hasher.hash(password)


# A real Argon2id verification also runs when an email does not exist.
# This value is not an account credential and cannot authenticate a user.
DUMMY_PASSWORD_HASH = hash_password("dummy password for unknown-account verification")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False
