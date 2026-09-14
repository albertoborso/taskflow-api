"""Credential login and adversarial bearer-token validation on PostgreSQL."""

from datetime import UTC, datetime
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import DUMMY_PASSWORD_HASH, verify_password
from app.modules.auth import service
from app.modules.users.model import User
from app.modules.users.schemas import UserResponse

pytestmark = pytest.mark.integration
TOKEN_ENDPOINT = "/api/v1/auth/token"
PROFILE_ENDPOINT = "/api/v1/users/me"


@pytest.fixture
def claims(
    registered_user: UserResponse, database_settings: Settings
) -> dict[str, object]:
    now = int(datetime.now(UTC).timestamp())
    return {
        "sub": str(registered_user.id),
        "iss": database_settings.jwt_issuer,
        "aud": database_settings.jwt_audience,
        "iat": now,
        "exp": now + 60,
    }


def assert_rejected(client: TestClient, token: str) -> None:
    response = client.get(
        PROFILE_ENDPOINT, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert token not in response.text


def test_successful_login(
    client: TestClient,
    registered_user: UserResponse,
    registration_payload: dict[str, str],
    database_settings: Settings,
) -> None:
    response = client.post(
        TOKEN_ENDPOINT,
        json={
            "email": " ALICE@Example.COM ",
            "password": registration_payload["password"],
        },
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == database_settings.access_token_minutes * 60
    payload = jwt.decode(
        body["access_token"],
        database_settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        issuer=database_settings.jwt_issuer,
        audience=database_settings.jwt_audience,
        options={"require": ["sub", "iss", "aud", "iat", "exp"]},
    )
    assert set(payload) == {"sub", "iss", "aud", "iat", "exp"}
    assert payload["sub"] == str(registered_user.id)
    assert payload["exp"] - payload["iat"] == body["expires_in"]
    assert "password_hash" not in response.text
    assert registration_payload["password"] not in response.text
    assert (
        client.get(
            PROFILE_ENDPOINT,
            headers={"Authorization": f"Bearer {body['access_token']}"},
        ).status_code
        == 200
    )


def test_wrong_password_and_unknown_email_are_indistinguishable(
    client: TestClient,
    registered_user: UserResponse,
    registration_payload: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified_hashes: list[str] = []

    def recording_verify(password: str, password_hash: str) -> bool:
        verified_hashes.append(password_hash)
        return verify_password(password, password_hash)

    monkeypatch.setattr(service, "verify_password", recording_verify)
    responses = [
        client.post(
            TOKEN_ENDPOINT,
            json={"email": str(registered_user.email), "password": "wrong"},
        ),
        client.post(
            TOKEN_ENDPOINT,
            json={
                "email": "unknown@example.com",
                "password": registration_payload["password"],
            },
        ),
    ]
    for response in responses:
        assert response.status_code == 401
        assert response.json()["error"] == {
            "code": "unauthorized",
            "message": "Authentication required or credentials are invalid",
            "details": [],
        }
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.headers["Cache-Control"] == "no-store"
    assert len(verified_hashes) == 2
    assert verified_hashes[0].startswith("$argon2id$")
    assert verified_hashes[1] == DUMMY_PASSWORD_HASH


def test_expired_token(
    client: TestClient, claims: dict[str, object], database_settings: Settings
) -> None:
    now = int(datetime.now(UTC).timestamp())
    claims.update(iat=now - 120, exp=now - 60)
    token = jwt.encode(
        claims, database_settings.jwt_secret.get_secret_value(), algorithm="HS256"
    )
    assert_rejected(client, token)


@pytest.mark.parametrize(
    "token", ["not-a-jwt", "one.two.three", "eyJhbGciOiJIUzI1NiJ9.e30.invalid"]
)
def test_malformed_token(client: TestClient, token: str) -> None:
    assert_rejected(client, token)


def test_invalid_signature(client: TestClient, claims: dict[str, object]) -> None:
    token = jwt.encode(claims, "different-signing-key-" * 4, algorithm="HS256")
    assert_rejected(client, token)


@pytest.mark.parametrize("algorithm", ["none", "HS512"])
def test_unapproved_algorithm(
    client: TestClient,
    claims: dict[str, object],
    database_settings: Settings,
    algorithm: str,
) -> None:
    key = "" if algorithm == "none" else database_settings.jwt_secret.get_secret_value()
    token = jwt.encode(claims, key, algorithm=algorithm)
    assert_rejected(client, token)


@pytest.mark.parametrize("claim", ["sub", "iss", "aud", "iat", "exp"])
def test_missing_required_claim(
    client: TestClient,
    claims: dict[str, object],
    database_settings: Settings,
    claim: str,
) -> None:
    del claims[claim]
    token = jwt.encode(
        claims, database_settings.jwt_secret.get_secret_value(), algorithm="HS256"
    )
    assert_rejected(client, token)


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("iss", "other-issuer"),
        ("aud", "other-api"),
        ("aud", ["portfolio-api", "other-api"]),
        ("sub", "not-a-uuid"),
        ("sub", 123),
        ("iat", "invalid-time"),
        ("exp", "invalid-time"),
        ("exp", None),
        ("iat", []),
        ("exp", {}),
        ("nbf", []),
        ("exp", float("inf")),
    ],
)
def test_invalid_claim(
    client: TestClient,
    claims: dict[str, object],
    database_settings: Settings,
    claim: str,
    value: object,
) -> None:
    claims[claim] = value
    token = jwt.encode(
        claims, database_settings.jwt_secret.get_secret_value(), algorithm="HS256"
    )
    assert_rejected(client, token)


@pytest.mark.parametrize("scenario", ["future-iat", "too-long", "expiry-before-iat"])
def test_invalid_token_lifetime(
    client: TestClient,
    claims: dict[str, object],
    database_settings: Settings,
    scenario: str,
) -> None:
    now = int(datetime.now(UTC).timestamp())
    if scenario == "future-iat":
        claims.update(iat=now + 60, exp=now + 120)
    elif scenario == "too-long":
        claims.update(exp=now + database_settings.access_token_minutes * 60 + 60)
    else:
        claims.update(iat=now, exp=now - 1)
    token = jwt.encode(
        claims, database_settings.jwt_secret.get_secret_value(), algorithm="HS256"
    )
    assert_rejected(client, token)


def test_token_for_nonexistent_user(
    client: TestClient, claims: dict[str, object], database_settings: Settings
) -> None:
    claims["sub"] = str(uuid4())
    token = jwt.encode(
        claims, database_settings.jwt_secret.get_secret_value(), algorithm="HS256"
    )
    assert_rejected(client, token)


def test_deleted_user_token_is_rejected(
    client: TestClient,
    access_token: str,
    registered_user: UserResponse,
    database_engine: Engine,
) -> None:
    with Session(database_engine) as db, db.begin():
        user = db.get(User, registered_user.id)
        assert user is not None
        db.delete(user)
    assert_rejected(client, access_token)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"email": "invalid", "password": "secret-input"},
        {"email": "alice@example.com", "password": None},
    ],
)
def test_invalid_login_input(client: TestClient, payload: dict[str, object]) -> None:
    response = client.post(TOKEN_ENDPOINT, json=payload)
    assert response.status_code == 422
    assert "secret-input" not in response.text
    assert all("input" not in error for error in response.json()["error"]["details"])
