"""Registration integration tests against migrated PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier
from uuid import UUID

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import DuplicateEmailError
from app.core.security import hash_password
from app.modules.users import service
from app.modules.users.model import User
from app.modules.users.schemas import UserCreate

pytestmark = pytest.mark.integration
ENDPOINT = "/api/v1/users"


def test_successful_registration(
    client: TestClient, database_engine: Engine, registration_payload: dict[str, str]
) -> None:
    registration_payload.update(
        email="  ALICE@Example.COM  ", display_name="  Alice Example  "
    )
    response = client.post(ENDPOINT, json=registration_payload)
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "email", "display_name", "created_at", "updated_at"}
    assert body["email"] == "alice@example.com"
    assert body["display_name"] == "Alice Example"
    user_id = UUID(body["id"])
    assert datetime.fromisoformat(body["created_at"]).tzinfo is not None
    assert datetime.fromisoformat(body["updated_at"]).tzinfo is not None
    assert registration_payload["password"] not in response.text
    assert "password_hash" not in response.text
    # An independent connection sees the committed row.
    with Session(database_engine) as db:
        user = db.get(User, user_id)
        assert user is not None
        assert user.email == "alice@example.com"
        assert user.password_hash != registration_payload["password"]
        assert user.password_hash.startswith("$argon2id$")
        assert PasswordHasher().verify(
            user.password_hash, registration_payload["password"]
        )
        assert user.password_hash not in response.text


@pytest.mark.parametrize(
    "duplicate_email", ["alice@example.com", " ALICE@EXAMPLE.COM "]
)
def test_duplicate_email(
    client: TestClient,
    database_engine: Engine,
    registration_payload: dict[str, str],
    duplicate_email: str,
) -> None:
    assert client.post(ENDPOINT, json=registration_payload).status_code == 201
    duplicate = dict(registration_payload, email=duplicate_email)
    response = client.post(ENDPOINT, json=duplicate)
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "email_already_registered",
        "message": "Email already registered",
        "details": [],
    }
    with Session(database_engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("email", "not-an-email"),
        ("email", "alice@"),
        ("email", None),
        ("password", "too-short"),
        ("password", " " * 20),
        ("password", "p" * 129),
        ("password", 123456789012345),
        ("password", None),
        ("display_name", "  "),
        ("display_name", "n" * 101),
        ("display_name", None),
    ],
)
def test_invalid_input(
    client: TestClient,
    database_engine: Engine,
    registration_payload: dict[str, str],
    field: str,
    value: object,
) -> None:
    payload: dict[str, object] = dict(registration_payload)
    payload[field] = value
    response = client.post(ENDPOINT, json=payload)
    assert response.status_code == 422
    for error in response.json()["error"]["details"]:
        assert set(error) == {"type", "loc", "msg"}
    assert registration_payload["password"] not in response.text
    if field == "password" and isinstance(value, str) and value.strip():
        assert value not in response.text
    with Session(database_engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.parametrize("field", ["email", "password", "display_name"])
def test_required_fields(
    client: TestClient, registration_payload: dict[str, str], field: str
) -> None:
    del registration_payload[field]
    response = client.post(ENDPOINT, json=registration_payload)
    assert response.status_code == 422
    assert "input" not in response.json()["error"]["details"][0]


def test_rejects_client_supplied_hash(
    client: TestClient, registration_payload: dict[str, str]
) -> None:
    response = client.post(
        ENDPOINT, json=dict(registration_payload, password_hash="client-supplied-hash")
    )
    assert response.status_code == 422
    assert "client-supplied-hash" not in response.text
    assert registration_payload["password"] not in response.text


def test_passwords_preserve_spaces_and_use_random_salts(
    client: TestClient, database_engine: Engine, registration_payload: dict[str, str]
) -> None:
    registration_payload["password"] = "  a passphrase with spaces  "
    assert client.post(ENDPOINT, json=registration_payload).status_code == 201
    assert (
        client.post(
            ENDPOINT, json=dict(registration_payload, email="bob@example.com")
        ).status_code
        == 201
    )
    with Session(database_engine) as db:
        hashes = list(db.scalars(select(User.password_hash)))
    assert len(hashes) == 2
    assert hashes[0] != hashes[1]
    for stored_hash in hashes:
        assert PasswordHasher().verify(stored_hash, registration_payload["password"])


def test_duplicate_race(
    client: TestClient,
    database_engine: Engine,
    registration_payload: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Both requests finish hashing before either can insert. Real DB sessions
    # compete for the same unique email; no database calls are mocked.
    barrier = Barrier(2, timeout=10)

    def synchronized_hash(password: str) -> str:
        result = hash_password(password)
        barrier.wait()
        return result

    monkeypatch.setattr(service, "hash_password", synchronized_hash)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(client.post, ENDPOINT, json=registration_payload)
            for _ in range(2)
        ]
        statuses = sorted(future.result(timeout=20).status_code for future in futures)
    assert statuses == [201, 409]
    with Session(database_engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1


def test_duplicate_rolls_back_and_session_remains_usable(
    database_engine: Engine, registration_payload: dict[str, str]
) -> None:
    data = UserCreate.model_validate(registration_payload)
    with Session(database_engine, expire_on_commit=False) as db:
        service.register_user(db, data)
        with pytest.raises(DuplicateEmailError):
            service.register_user(db, data)
        assert not db.in_transaction()
        other = UserCreate.model_validate(
            dict(registration_payload, email="other@example.com")
        )
        service.register_user(db, other)
    with Session(database_engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 2
