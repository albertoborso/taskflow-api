"""Access-token signing and strict verification using PyJWT."""

from datetime import UTC, datetime
from uuid import UUID

import jwt

from app.core.config import Settings

ALGORITHM = "HS256"


def create_access_token(user_id: UUID, settings: Settings) -> str:
    issued_at = int(datetime.now(UTC).timestamp())
    return jwt.encode(
        {
            "sub": str(user_id),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": issued_at,
            "exp": issued_at + settings.access_token_minutes * 60,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=ALGORITHM,
    )


def decode_access_token(token: str, settings: Settings) -> UUID:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[ALGORITHM],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={
                "require": ["sub", "iss", "aud", "iat", "exp"],
                "strict_aud": True,
            },
        )
    except (TypeError, ValueError, OverflowError) as exc:
        # Malformed claim/header types may surface as Python conversion errors.
        raise jwt.InvalidTokenError("Malformed access token") from exc
    # PyJWT checks signature, issuer, audience, expiry and future issued-at values.
    # Enforce our narrower claim types and lifetime contract as well.
    issued_at, expires_at = claims["iat"], claims["exp"]
    if (
        type(issued_at) is not int
        or type(expires_at) is not int
        or not 0 < expires_at - issued_at <= settings.access_token_minutes * 60
    ):
        raise jwt.InvalidTokenError("Invalid access-token lifetime")
    try:
        return UUID(claims["sub"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise jwt.InvalidTokenError("Invalid access-token subject") from exc
