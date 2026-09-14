"""Task lifecycle, filters, parent authorization, and database integrity."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.errors import CheckViolation
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.projects.model import Project
from app.modules.projects.schemas import ProjectResponse
from app.modules.tasks.model import Task
from app.modules.tasks.schemas import TaskResponse

pytestmark = pytest.mark.integration


def test_task_crud(
    client: TestClient,
    auth_headers: dict[str, str],
    owned_project: ProjectResponse,
    database_engine: Engine,
) -> None:
    collection = f"/api/v1/projects/{owned_project.id}/tasks"
    response = client.post(
        collection,
        headers=auth_headers,
        json={"title": "  First task  ", "description": "Details"},
    )
    assert response.status_code == 201
    task = TaskResponse.model_validate(response.json())
    assert task.title == "First task" and task.project_id == owned_project.id
    assert task.status == "todo" and task.priority == 2
    assert task.completed_at is None and task.due_at is None
    path = f"/api/v1/tasks/{task.id}"
    assert client.get(path, headers=auth_headers).json() == response.json()
    response = client.patch(
        path,
        headers=auth_headers,
        json={"title": "Updated", "priority": 3, "due_at": "2027-01-01T10:00:00+02:00"},
    )
    assert response.status_code == 200
    changed = TaskResponse.model_validate(response.json())
    assert changed.description == "Details" and changed.priority == 3
    assert changed.due_at == datetime(2027, 1, 1, 8, tzinfo=UTC)
    response = client.patch(
        path, headers=auth_headers, json={"description": None, "due_at": None}
    )
    assert response.status_code == 200
    assert response.json()["description"] is None and response.json()["due_at"] is None
    assert response.json()["title"] == "Updated"
    # Child edits do not mutate the parent's timestamp.
    parent = client.get(f"/api/v1/projects/{owned_project.id}", headers=auth_headers)
    assert (
        ProjectResponse.model_validate(parent.json()).updated_at
        == owned_project.updated_at
    )
    response = client.delete(path, headers=auth_headers)
    assert response.status_code == 204 and response.content == b""
    assert client.get(path, headers=auth_headers).status_code == 404
    with Session(database_engine) as db:
        assert db.get(Task, task.id) is None
        assert db.get(Project, owned_project.id) is not None


@pytest.mark.parametrize("initial", ["todo", "in_progress", "done"])
@pytest.mark.parametrize("target", ["todo", "in_progress", "done"])
def test_all_status_transitions(
    client: TestClient,
    auth_headers: dict[str, str],
    owned_project: ProjectResponse,
    initial: str,
    target: str,
) -> None:
    response = client.post(
        f"/api/v1/projects/{owned_project.id}/tasks",
        headers=auth_headers,
        json={"title": "Transition", "status": initial},
    )
    assert response.status_code == 201
    original = response.json()
    assert (original["completed_at"] is not None) == (initial == "done")
    response = client.patch(
        f"/api/v1/tasks/{original['id']}", headers=auth_headers, json={"status": target}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == target
    assert (body["completed_at"] is not None) == (target == "done")
    if initial == target == "done":
        assert body["completed_at"] == original["completed_at"]


def test_completion_preserved_then_reopened(
    client: TestClient, auth_headers: dict[str, str], owned_task: TaskResponse
) -> None:
    path = f"/api/v1/tasks/{owned_task.id}"
    completed = client.patch(
        path, headers=auth_headers, json={"status": "done"}
    ).json()["completed_at"]
    assert completed is not None
    edited = client.patch(
        path, headers=auth_headers, json={"title": "Edited", "priority": 1}
    ).json()
    assert edited["completed_at"] == completed
    assert (
        client.patch(path, headers=auth_headers, json={"status": "todo"}).json()[
            "completed_at"
        ]
        is None
    )
    recompleted = client.patch(
        path, headers=auth_headers, json={"status": "done"}
    ).json()["completed_at"]
    assert datetime.fromisoformat(recompleted) > datetime.fromisoformat(completed)


def test_concurrent_completion_is_not_overwritten(
    client: TestClient, auth_headers: dict[str, str], owned_task: TaskResponse
) -> None:
    barrier = Barrier(2, timeout=10)

    def complete() -> str:
        barrier.wait()
        response = client.patch(
            f"/api/v1/tasks/{owned_task.id}",
            headers=auth_headers,
            json={"status": "done"},
        )
        assert response.status_code == 200
        return str(response.json()["completed_at"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(complete) for _ in range(2)]
        completed = [f.result(timeout=15) for f in futures]
    assert completed[0] == completed[1] != "None"


def test_task_filters_and_pagination(
    client: TestClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    owned_project: ProjectResponse,
    database_engine: Engine,
) -> None:
    collection = f"/api/v1/projects/{owned_project.id}/tasks"
    payloads = [
        {"title": "Early todo", "priority": 1, "due_at": "2027-01-01T00:00:00Z"},
        {
            "title": "Early done",
            "status": "done",
            "priority": 3,
            "due_at": "2027-01-01T00:00:00Z",
        },
        {"title": "Boundary", "priority": 3, "due_at": "2027-01-02T00:00:00Z"},
        {"title": "No due date", "priority": 3},
    ]
    created = [
        client.post(collection, headers=auth_headers, json=p).json() for p in payloads
    ]
    # Tie all timestamps so the UUID tiebreaker is exercised explicitly.
    with database_engine.begin() as connection:
        connection.execute(
            text("UPDATE tasks SET created_at = :created"),
            {"created": datetime(2026, 1, 1, tzinfo=UTC)},
        )
    other_project = client.post(
        "/api/v1/projects", headers=other_auth_headers, json={"name": "Foreign"}
    ).json()
    assert (
        client.post(
            f"/api/v1/projects/{other_project['id']}/tasks",
            headers=other_auth_headers,
            json={"title": "Foreign", "priority": 3, "status": "done"},
        ).status_code
        == 201
    )
    # Another project owned by the same user must also be excluded.
    own_other = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Separate"}
    ).json()
    client.post(
        f"/api/v1/projects/{own_other['id']}/tasks",
        headers=auth_headers,
        json={"title": "Separate", "status": "done"},
    )
    expected = sorted([p["id"] for p in created], reverse=True)
    full = client.get(collection, headers=auth_headers).json()
    assert [t["id"] for t in full["items"]] == expected
    assert full["limit"] == 20 and full["offset"] == 0
    page = client.get(
        collection, headers=auth_headers, params={"limit": 2, "offset": 1}
    ).json()
    assert [t["id"] for t in page["items"]] == expected[1:3]
    assert page["limit"] == 2 and page["offset"] == 1
    assert (
        client.get(collection, headers=auth_headers, params={"offset": 99}).json()[
            "items"
        ]
        == []
    )
    for params, titles in [
        ({"status": "done"}, {"Early done"}),
        ({"priority": "3"}, {"Early done", "Boundary", "No due date"}),
        ({"due_before": "2027-01-02T00:00:00Z"}, {"Early todo", "Early done"}),
        (
            {"status": "done", "priority": "3", "due_before": "2027-01-02T00:00:00Z"},
            {"Early done"},
        ),
        ({"status": "in_progress"}, set()),
    ]:
        response = client.get(collection, headers=auth_headers, params=params)
        assert response.status_code == 200
        assert {t["title"] for t in response.json()["items"]} == titles


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
def test_task_isolation_both_directions(
    client: TestClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    owned_task: TaskResponse,
    method: str,
) -> None:
    project = client.post(
        "/api/v1/projects", headers=other_auth_headers, json={"name": "Other"}
    ).json()
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        headers=other_auth_headers,
        json={"title": "Other task"},
    ).json()
    for headers, foreign_id in [
        (auth_headers, task["id"]),
        (other_auth_headers, str(owned_task.id)),
    ]:
        foreign = client.request(
            method,
            f"/api/v1/tasks/{foreign_id}",
            headers=headers,
            json={"title": "Hacked"},
        )
        missing = client.request(
            method,
            f"/api/v1/tasks/{uuid4()}",
            headers=headers,
            json={"title": "Hacked"},
        )
        assert foreign.status_code == missing.status_code == 404
        assert (
            foreign.json()["error"]
            == missing.json()["error"]
            == {"code": "not_found", "message": "Resource not found", "details": []}
        )
    assert (
        client.get(f"/api/v1/tasks/{owned_task.id}", headers=auth_headers).json()[
            "title"
        ]
        == owned_task.title
    )
    assert (
        client.get(f"/api/v1/tasks/{task['id']}", headers=other_auth_headers).json()[
            "title"
        ]
        == "Other task"
    )


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_nested_tasks_require_owned_parent(
    client: TestClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    owned_project: ProjectResponse,
    method: str,
) -> None:
    # The foreign parent has zero tasks: listing still returns 404, not an empty page.
    foreign = client.request(
        method,
        f"/api/v1/projects/{owned_project.id}/tasks",
        headers=other_auth_headers,
        json={"title": "Hacked"},
    )
    missing = client.request(
        method,
        f"/api/v1/projects/{uuid4()}/tasks",
        headers=auth_headers,
        json={"title": "Hacked"},
    )
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"] == missing.json()["error"]
    assert (
        client.get(
            f"/api/v1/projects/{owned_project.id}/tasks", headers=auth_headers
        ).json()["items"]
        == []
    )


@pytest.mark.parametrize("mode", ["api", "sql"])
def test_project_delete_cascades_only_its_tasks(
    client: TestClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    owned_task: TaskResponse,
    database_engine: Engine,
    mode: str,
) -> None:
    other_project = client.post(
        "/api/v1/projects", headers=other_auth_headers, json={"name": "Survives"}
    ).json()
    survivor = client.post(
        f"/api/v1/projects/{other_project['id']}/tasks",
        headers=other_auth_headers,
        json={"title": "Survives"},
    ).json()
    if mode == "api":
        assert (
            client.delete(
                f"/api/v1/projects/{owned_task.project_id}", headers=auth_headers
            ).status_code
            == 204
        )
    else:
        with Session(database_engine) as db, db.begin():
            db.execute(delete(Project).where(Project.id == owned_task.project_id))
    with Session(database_engine) as db:
        assert db.get(Task, owned_task.id) is None
        assert db.get(Task, UUID(survivor["id"])) is not None
    assert (
        client.get(f"/api/v1/tasks/{owned_task.id}", headers=auth_headers).status_code
        == 404
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "invalid"},
        {"priority": 0},
        {"priority": 4},
        {"priority": True},
        {"priority": "1"},
        {"title": " "},
        {"title": "t" * 201},
        {"due_at": "2027-01-01T00:00:00"},
        {"owner_id": str(uuid4())},
        {"project_id": str(uuid4())},
        {"completed_at": "2027-01-01T00:00:00Z"},
    ],
)
@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_invalid_task_input(
    client: TestClient,
    auth_headers: dict[str, str],
    owned_task: TaskResponse,
    payload: dict[str, object],
    method: str,
) -> None:
    path = (
        f"/api/v1/projects/{owned_task.project_id}/tasks"
        if method == "POST"
        else f"/api/v1/tasks/{owned_task.id}"
    )
    assert (
        client.request(
            method, path, headers=auth_headers, json={"title": "Valid", **payload}
        ).status_code
        == 422
    )


@pytest.mark.parametrize("field", ["title", "status", "priority"])
def test_task_patch_rejects_required_nulls(
    client: TestClient,
    auth_headers: dict[str, str],
    owned_task: TaskResponse,
    field: str,
) -> None:
    assert (
        client.patch(
            f"/api/v1/tasks/{owned_task.id}", headers=auth_headers, json={field: None}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "params",
    [
        {"status": "invalid"},
        {"priority": "4"},
        {"due_before": "2027-01-01T00:00:00"},
        {"limit": "101"},
        {"offset": "-1"},
    ],
)
def test_invalid_task_filters(
    client: TestClient,
    auth_headers: dict[str, str],
    owned_project: ProjectResponse,
    params: dict[str, str],
) -> None:
    assert (
        client.get(
            f"/api/v1/projects/{owned_project.id}/tasks",
            headers=auth_headers,
            params=params,
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("status", "invalid", "ck_tasks_valid_status"),
        ("priority", 0, "ck_tasks_valid_priority"),
        ("priority", 4, "ck_tasks_valid_priority"),
        ("status", "done", "ck_tasks_completion_matches_status"),
        (
            "completed_at",
            datetime(2026, 1, 1, tzinfo=UTC),
            "ck_tasks_completion_matches_status",
        ),
    ],
)
def test_database_checks_are_authoritative(
    database_engine: Engine,
    owned_task: TaskResponse,
    field: str,
    value: object,
    constraint: str,
) -> None:
    with pytest.raises(IntegrityError) as error, database_engine.begin() as connection:
        # Column names come only from the fixed parameterization above.
        connection.execute(
            text(f"UPDATE tasks SET {field} = :value WHERE id = :id"),
            {"value": value, "id": owned_task.id},
        )
    assert isinstance(error.value.orig, CheckViolation)
    assert error.value.orig.diag.constraint_name == constraint
    with Session(database_engine) as db:
        stored = db.scalar(select(Task).where(Task.id == owned_task.id))
        assert stored is not None and stored.status == "todo"
