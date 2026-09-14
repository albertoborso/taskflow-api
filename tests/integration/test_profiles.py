"""Current-user reads and display-name-only updates through real transactions."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.modules.users.model import User
from app.modules.users.schemas import UserResponse

pytestmark = pytest.mark.integration
ENDPOINT = "/api/v1/users/me"


def test_current_user_profile(
    client: TestClient, auth_headers: dict[str, str], registered_user: UserResponse
) -> None:
    response = client.get(ENDPOINT, headers=auth_headers)
    assert response.status_code == 200
    assert UserResponse.model_validate(response.json()) == registered_user
    assert set(response.json()) == {
        "id",
        "email",
        "display_name",
        "created_at",
        "updated_at",
    }


@pytest.mark.parametrize("method", ["GET", "PATCH"])
@pytest.mark.parametrize(
    "authorization",
    [None, "Basic abc", "Bearer", "Bearer invalid", "Bearer one.two.three"],
)
def test_profile_requires_valid_bearer(
    client: TestClient, method: str, authorization: str | None
) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}
    response = client.request(
        method, ENDPOINT, headers=headers, json={"display_name": "New Name"}
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_update_own_display_name_only(
    client: TestClient,
    auth_headers: dict[str, str],
    registered_user: UserResponse,
    database_engine: Engine,
    registration_payload: dict[str, str],
) -> None:
    other = client.post(
        "/api/v1/users",
        json=dict(registration_payload, email="bob@example.com", display_name="Bob"),
    )
    assert other.status_code == 201
    with Session(database_engine) as db:
        user = db.get(User, registered_user.id)
        assert user is not None
        original_hash = user.password_hash
    response = client.patch(
        ENDPOINT, headers=auth_headers, json={"display_name": "  Alice Updated  "}
    )
    assert response.status_code == 200
    profile = UserResponse.model_validate(response.json())
    assert profile.display_name == "Alice Updated"
    assert profile.id == registered_user.id
    assert profile.email == registered_user.email
    assert profile.created_at == registered_user.created_at
    assert profile.updated_at >= registered_user.updated_at
    assert "password_hash" not in response.text
    assert registration_payload["password"] not in response.text
    assert (
        client.get(ENDPOINT, headers=auth_headers).json()["display_name"]
        == "Alice Updated"
    )
    with Session(database_engine) as db:
        user = db.get(User, registered_user.id)
        other_user = db.get(User, UUID(other.json()["id"]))
        assert user is not None and other_user is not None
        assert user.display_name == "Alice Updated"
        assert user.password_hash == original_hash
        assert other_user.display_name == "Bob"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"display_name": None},
        {"display_name": "  "},
        {"display_name": "n" * 101},
        {"display_name": "New", "email": "other@example.com"},
        {"display_name": "New", "id": "00000000-0000-0000-0000-000000000000"},
        {"display_name": "New", "password": "new-password-must-not-appear"},
        {"display_name": "New", "password_hash": "injected-hash"},
    ],
)
def test_invalid_profile_update(
    client: TestClient,
    auth_headers: dict[str, str],
    registered_user: UserResponse,
    payload: dict[str, object],
) -> None:
    response = client.patch(ENDPOINT, headers=auth_headers, json=payload)
    assert response.status_code == 422
    assert "new-password-must-not-appear" not in response.text
    assert "injected-hash" not in response.text
    assert (
        client.get(ENDPOINT, headers=auth_headers).json()["display_name"]
        == registered_user.display_name
    )
