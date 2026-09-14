"""Project CRUD, deterministic pagination, and bidirectional ownership isolation."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.modules.projects.model import Project
from app.modules.projects.schemas import ProjectResponse
from app.modules.users.schemas import UserResponse

pytestmark = pytest.mark.integration
BASE = "/api/v1/projects"


def test_project_crud(
    client: TestClient,
    auth_headers: dict[str, str],
    registered_user: UserResponse,
    database_engine: Engine,
) -> None:
    response = client.post(
        BASE,
        headers=auth_headers,
        json={"name": "  Portfolio  ", "description": "Initial"},
    )
    assert response.status_code == 201
    project = ProjectResponse.model_validate(response.json())
    assert project.owner_id == registered_user.id
    assert project.name == "Portfolio"
    path = f"{BASE}/{project.id}"
    assert client.get(path, headers=auth_headers).json() == response.json()
    response = client.patch(path, headers=auth_headers, json={"name": "Updated"})
    assert response.status_code == 200
    assert response.json()["description"] == "Initial"
    assert response.json()["owner_id"] == str(registered_user.id)
    response = client.patch(path, headers=auth_headers, json={"description": None})
    assert response.status_code == 200
    assert response.json()["description"] is None
    assert response.json()["name"] == "Updated"
    with Session(database_engine) as db:
        stored = db.get(Project, project.id)
        assert stored is not None and stored.name == "Updated"
    response = client.delete(path, headers=auth_headers)
    assert response.status_code == 204 and response.content == b""
    assert client.get(path, headers=auth_headers).status_code == 404
    with Session(database_engine) as db:
        assert db.get(Project, project.id) is None


def test_project_pagination(
    client: TestClient,
    auth_headers: dict[str, str],
    registered_user: UserResponse,
    database_engine: Engine,
    other_auth_headers: dict[str, str],
) -> None:
    with Session(database_engine) as db, db.begin():
        for identifier, day in [(1, 1), (2, 2), (3, 2), (4, 1)]:
            db.add(
                Project(
                    id=UUID(int=identifier),
                    owner_id=registered_user.id,
                    name=f"Project {identifier}",
                    created_at=datetime(2026, 1, day, tzinfo=UTC),
                )
            )
    assert (
        client.post(
            BASE, headers=other_auth_headers, json={"name": "Foreign newest"}
        ).status_code
        == 201
    )
    response = client.get(BASE, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["limit"] == 20 and response.json()["offset"] == 0
    assert [p["id"] for p in response.json()["items"]] == [
        str(UUID(int=i)) for i in [3, 2, 4, 1]
    ]
    body = client.get(
        BASE, headers=auth_headers, params={"limit": 2, "offset": 1}
    ).json()
    assert body["limit"] == 2 and body["offset"] == 1
    assert [p["id"] for p in body["items"]] == [str(UUID(int=2)), str(UUID(int=4))]
    assert (
        client.get(BASE, headers=auth_headers, params={"offset": 99}).json()["items"]
        == []
    )
    assert len(client.get(BASE, headers=other_auth_headers).json()["items"]) == 1


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
def test_projects_are_isolated_both_directions(
    client: TestClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    owned_project: ProjectResponse,
    method: str,
) -> None:
    other = client.post(BASE, headers=other_auth_headers, json={"name": "Other"}).json()
    for headers, foreign_id in [
        (other_auth_headers, str(owned_project.id)),
        (auth_headers, other["id"]),
    ]:
        foreign = client.request(
            method, f"{BASE}/{foreign_id}", headers=headers, json={"name": "Hacked"}
        )
        missing = client.request(
            method, f"{BASE}/{uuid4()}", headers=headers, json={"name": "Hacked"}
        )
        assert foreign.status_code == missing.status_code == 404
        assert (
            foreign.json()["error"]
            == missing.json()["error"]
            == {"code": "not_found", "message": "Resource not found", "details": []}
        )
    assert (
        client.get(f"{BASE}/{owned_project.id}", headers=auth_headers).json()["name"]
        == owned_project.name
    )
    assert (
        client.get(f"{BASE}/{other['id']}", headers=other_auth_headers).json()["name"]
        == "Other"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": " "},
        {"name": "x" * 151},
        {"name": None},
        {"name": "X", "owner_id": str(uuid4())},
        {"name": "X", "id": str(uuid4())},
    ],
)
def test_invalid_project_create(
    client: TestClient, auth_headers: dict[str, str], payload: dict[str, object]
) -> None:
    assert client.post(BASE, headers=auth_headers, json=payload).status_code == 422
    assert client.get(BASE, headers=auth_headers).json()["items"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"name": None},
        {"name": " "},
        {"owner_id": str(uuid4())},
        {"created_at": "2026-01-01T00:00:00Z"},
    ],
)
def test_invalid_project_update(
    client: TestClient,
    auth_headers: dict[str, str],
    owned_project: ProjectResponse,
    payload: dict[str, object],
) -> None:
    path = f"{BASE}/{owned_project.id}"
    assert client.patch(path, headers=auth_headers, json=payload).status_code == 422
    assert client.get(path, headers=auth_headers).json()["name"] == owned_project.name


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": "invalid"}]
)
def test_invalid_project_pagination(
    client: TestClient, auth_headers: dict[str, str], params: dict[str, object]
) -> None:
    response = client.get(
        BASE,
        headers=auth_headers,
        params={key: str(value) for key, value in params.items()},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/api/v1/projects", {"name": "X"}),
        ("GET", "/api/v1/projects", {}),
        ("GET", f"/api/v1/projects/{uuid4()}", {}),
        ("PATCH", f"/api/v1/projects/{uuid4()}", {"name": "X"}),
        ("DELETE", f"/api/v1/projects/{uuid4()}", {}),
        ("POST", f"/api/v1/projects/{uuid4()}/tasks", {"title": "X"}),
        ("GET", f"/api/v1/projects/{uuid4()}/tasks", {}),
        ("GET", f"/api/v1/tasks/{uuid4()}", {}),
        ("PATCH", f"/api/v1/tasks/{uuid4()}", {"title": "X"}),
        ("DELETE", f"/api/v1/tasks/{uuid4()}", {}),
    ],
)
def test_resource_routes_require_authentication(
    client: TestClient, method: str, path: str, payload: dict[str, str]
) -> None:
    assert client.request(method, path, json=payload).status_code == 401
