"""Real PostgreSQL fixtures with committed requests and disposable test data."""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from secrets import token_hex
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.session import create_db_engine, get_database_url
from app.main import create_app
from app.modules.projects.schemas import ProjectResponse
from app.modules.tasks.schemas import TaskResponse
from app.modules.users.schemas import UserResponse

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def database_settings() -> Iterator[Settings]:
    """Create and migrate a unique database; never migrate or clear the app DB."""
    settings = Settings()
    name = f"portfolio_test_{uuid4().hex}"
    test_settings = settings.model_copy(
        update={
            "db_name": name,
            "environment": "test",
            "jwt_secret": SecretStr(token_hex(32)),
        }
    )
    admin = create_engine(
        get_database_url(settings).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
        connect_args={"connect_timeout": 3},
    )
    created = False
    try:
        with admin.connect() as connection:
            # The identifier contains only a fixed prefix and generated hex digits.
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=PROJECT_ROOT,
            env=dict(os.environ, APP_DB_NAME=name, APP_ENVIRONMENT="test"),
            check=True,
            capture_output=True,
            text=True,
        )
        yield test_settings
    finally:
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


@pytest.fixture(scope="session")
def database_engine(database_settings: Settings) -> Iterator[Engine]:
    engine = create_db_engine(database_settings)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_database(database_engine: Engine) -> Iterator[None]:
    """Each test gets empty tables, including after real service commits."""
    with database_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE tasks, projects, users"))
    try:
        yield
    finally:
        with database_engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE tasks, projects, users"))


@pytest.fixture
def client(database_settings: Settings) -> Iterator[TestClient]:
    # Exercise the real request dependency, engine, and transaction lifecycle.
    with TestClient(create_app(database_settings)) as test_client:
        yield test_client


@pytest.fixture
def registration_payload() -> dict[str, str]:
    return {
        "email": "alice@example.com",
        "password": "a long registration passphrase",
        "display_name": "Alice Example",
    }


@pytest.fixture
def registered_user(
    client: TestClient, registration_payload: dict[str, str]
) -> UserResponse:
    response = client.post("/api/v1/users", json=registration_payload)
    assert response.status_code == 201
    return UserResponse.model_validate(response.json())


@pytest.fixture
def access_token(
    client: TestClient,
    registered_user: UserResponse,
    registration_payload: dict[str, str],
) -> str:
    response = client.post(
        "/api/v1/auth/token",
        json={
            "email": str(registered_user.email),
            "password": registration_payload["password"],
        },
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


@pytest.fixture
def auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def other_auth_headers(
    client: TestClient, registration_payload: dict[str, str]
) -> dict[str, str]:
    payload = dict(registration_payload, email="other-owner@example.com")
    assert client.post("/api/v1/users", json=payload).status_code == 201
    response = client.post(
        "/api/v1/auth/token",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def owned_project(client: TestClient, auth_headers: dict[str, str]) -> ProjectResponse:
    response = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "Portfolio", "description": "A project"},
    )
    assert response.status_code == 201
    return ProjectResponse.model_validate(response.json())


@pytest.fixture
def owned_task(
    client: TestClient, auth_headers: dict[str, str], owned_project: ProjectResponse
) -> TaskResponse:
    response = client.post(
        f"/api/v1/projects/{owned_project.id}/tasks",
        headers=auth_headers,
        json={"title": "First task"},
    )
    assert response.status_code == 201
    return TaskResponse.model_validate(response.json())
