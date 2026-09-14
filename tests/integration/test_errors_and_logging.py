"""Error contracts, request correlation, and credential-safe logging."""

import json
import logging
import socket
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import text

from app.api.dependencies import DatabaseSession
from app.core.config import Settings
from app.core.logging import JsonFormatter, logger
from app.main import create_app
from app.modules.projects.schemas import ProjectResponse
from app.modules.users.schemas import UserResponse

pytestmark = pytest.mark.integration


@pytest.fixture
def log_output() -> Iterator[StringIO]:
    output = StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    try:
        yield output
    finally:
        logger.removeHandler(handler)
        handler.close()


def assert_error(response: Response, status_code: int, code: str) -> dict[str, object]:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"error", "request_id"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert isinstance(body["error"]["details"], list)
    assert UUID(body["request_id"]).version == 4
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert response.headers["Cache-Control"] == "no-store"
    if status_code == 401:
        assert response.headers["WWW-Authenticate"] == "Bearer"
    return cast(dict[str, object], body["error"])


def test_consistent_error_envelopes(
    client: TestClient,
    registered_user: UserResponse,
    registration_payload: dict[str, str],
) -> None:
    cases = [
        (client.get("/api/v1/users/me"), 401, "unauthorized"),
        (client.get("/does-not-exist"), 404, "not_found"),
        (client.post("/health/live"), 405, "method_not_allowed"),
        (
            client.post("/api/v1/users", json=registration_payload),
            409,
            "email_already_registered",
        ),
        (
            client.post(
                "/api/v1/users",
                json={"email": "invalid", "password": "short", "display_name": " "},
            ),
            422,
            "validation_error",
        ),
        (
            client.post(
                "/api/v1/auth/token",
                json={"email": str(registered_user.email), "password": "wrong"},
            ),
            401,
            "unauthorized",
        ),
        (
            client.post(
                "/api/v1/auth/token",
                json={"email": "unknown@example.com", "password": "wrong"},
            ),
            401,
            "unauthorized",
        ),
    ]
    for response, status_code, code in cases:
        assert_error(response, status_code, code)
    assert "GET" in cases[2][0].headers["Allow"]
    assert cases[-1][0].json()["error"] == cases[-2][0].json()["error"]
    ids = {response.headers["X-Request-ID"] for response, _, _ in cases}
    assert len(ids) == len(cases)


def test_foreign_and_missing_resources_match(
    client: TestClient,
    other_auth_headers: dict[str, str],
    owned_project: ProjectResponse,
) -> None:
    responses = [
        client.get(f"/api/v1/projects/{identifier}", headers=other_auth_headers)
        for identifier in [owned_project.id, uuid4()]
    ]
    errors = [assert_error(response, 404, "not_found") for response in responses]
    assert errors[0] == errors[1]
    assert str(owned_project.id) not in responses[0].text
    assert owned_project.name not in responses[0].text


def test_useful_validation_without_echoed_inputs(client: TestClient) -> None:
    secret = "sensitive-extra-field-name"
    response = client.post(
        "/api/v1/users",
        json={
            "email": "private-invalid-email",
            "password": "secret",
            "display_name": " ",
            secret: "sensitive-extra-value",
        },
    )
    assert_error(response, 422, "validation_error")
    details = response.json()["error"]["details"]
    assert {
        "type": "value_error",
        "loc": ["body", "email"],
        "msg": "Must be a valid email address",
    } in details
    assert any(
        detail["loc"] == ["body", "password"] and "15" in detail["msg"]
        for detail in details
    )
    assert any(
        detail["loc"] == ["body", "display_name"] and "1" in detail["msg"]
        for detail in details
    )
    assert all(set(detail) == {"type", "loc", "msg"} for detail in details)
    for value in [secret, "sensitive-extra-value", "private-invalid-email", "secret"]:
        assert value not in response.text


def test_malformed_json_is_sanitized(client: TestClient) -> None:
    response = client.post(
        "/api/v1/users",
        content='{"password":"private-password", BROKEN',
        headers={"Content-Type": "application/json"},
    )
    assert_error(response, 422, "validation_error")
    assert (
        response.json()["error"]["details"][0]["msg"]
        == "Request body must contain valid JSON"
    )
    assert "private-password" not in response.text
    assert "BROKEN" not in response.text


def test_request_id_unique_and_not_client_controlled(
    client: TestClient, log_output: StringIO
) -> None:
    supplied = str(uuid4())
    responses = [
        client.get("/health/live", headers={"X-Request-ID": supplied}) for _ in range(3)
    ]
    ids = {response.headers["X-Request-ID"] for response in responses}
    assert len(ids) == 3 and supplied not in ids
    assert all(UUID(request_id).version == 4 for request_id in ids)
    records = [json.loads(line) for line in log_output.getvalue().splitlines()]
    assert {record["request_id"] for record in records} == ids
    for record in records:
        assert record["event"] == "request_completed"
        assert record["level"] == "INFO"
        assert record["method"] == "GET"
        assert record["path"] == "/health/live"
        assert record["status_code"] == 200
        assert record["duration_ms"] >= 0
        assert "timestamp" in record


def test_concurrent_request_context_is_isolated(
    client: TestClient, log_output: StringIO
) -> None:
    def probe() -> dict[str, bool]:
        logger.info("request_probe")
        return {"ok": True}

    cast(FastAPI, client.app).add_api_route("/__test/probe", probe)
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(lambda _: client.get("/__test/probe"), range(8)))
    ids = {response.headers["X-Request-ID"] for response in responses}
    assert len(ids) == 8
    records = [json.loads(line) for line in log_output.getvalue().splitlines()]
    for event in ["request_probe", "request_completed"]:
        assert {
            record["request_id"] for record in records if record["event"] == event
        } == ids
        assert sum(record["event"] == event for record in records) == 8


def test_sensitive_request_values_are_not_logged(
    client: TestClient,
    log_output: StringIO,
    access_token: str,
    registration_payload: dict[str, str],
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/api/v1/auth/token",
        json={
            "email": registration_payload["email"],
            "password": registration_payload["password"],
        },
    )
    assert response.status_code == 200
    issued_token = response.json()["access_token"]
    client.get(
        "/health/live",
        params={"password": "query-secret", "token": access_token},
        headers=auth_headers,
    )
    invalid = client.get("/api/v1/projects/private-path-secret", headers=auth_headers)
    assert_error(invalid, 422, "validation_error")
    client.get(
        "/unknown/private-path-secret",
        headers={"Authorization": "Bearer header-secret"},
    )
    client.post(
        "/api/v1/users",
        json={"email": "bad", "password": "body-secret", "display_name": "Valid"},
    )
    logs = log_output.getvalue()
    for value in [
        registration_payload["password"],
        registration_payload["email"],
        access_token,
        issued_token,
        "query-secret",
        "private-path-secret",
        "header-secret",
        "body-secret",
        "Authorization",
        "$argon2id$",
    ]:
        assert value not in logs
    paths = {json.loads(line).get("path") for line in logs.splitlines()}
    assert "/api/v1/projects/{project_id}" in paths
    assert "[unmatched]" in paths
    assert logging.getLogger("uvicorn.access").disabled


@pytest.mark.parametrize("failure_kind", ["runtime", "sql", "response_validation"])
def test_unexpected_failures_are_safe_and_correlated(
    client: TestClient, log_output: StringIO, failure_kind: str
) -> None:
    secret = "DO-NOT-EXPOSE-secret-password-or-token"
    path = f"/__test/{failure_kind}"
    application = cast(FastAPI, client.app)
    if failure_kind == "runtime":

        def runtime_failure() -> None:
            raise RuntimeError(f"internal exception {secret}")

        application.add_api_route(path, runtime_failure, methods=["POST"])
    elif failure_kind == "sql":

        def sql_failure(db: DatabaseSession) -> None:
            db.execute(text("SELECT CAST(:value AS INTEGER)"), {"value": secret})

        application.add_api_route(path, sql_failure, methods=["POST"])
    else:

        def invalid_response() -> dict[str, str]:
            return {"password": secret}

        application.add_api_route(
            path, invalid_response, methods=["POST"], response_model=UserResponse
        )
    response = client.post(
        path, json={"password": secret}, headers={"Authorization": f"Bearer {secret}"}
    )
    assert_error(response, 500, "internal_server_error")
    assert response.json()["error"]["message"] == "An unexpected error occurred"
    for value in [secret, "RuntimeError", "SELECT", "Traceback", "DataError"]:
        assert value not in response.text
    records = [json.loads(line) for line in log_output.getvalue().splitlines()]
    record = next(
        record
        for record in records
        if record["request_id"] == response.headers["X-Request-ID"]
    )
    assert record["level"] == "ERROR"
    assert record["event"] == "request_failed"
    assert record["status_code"] == 500 and record["method"] == "POST"
    assert record["path"] == path and record["duration_ms"] >= 0
    assert record["exception_type"]
    assert record["traceback"]
    assert all(
        set(frame) == {"file", "line", "function"} for frame in record["traceback"]
    )
    assert secret not in log_output.getvalue()
    assert "SELECT CAST" not in log_output.getvalue()
    # A failing request must not poison subsequent requests or database sessions.
    assert client.get("/health/ready").status_code == 200


def test_http_exception_details_and_headers_are_not_reflected(
    client: TestClient,
) -> None:
    def unsafe_detail() -> None:
        raise HTTPException(
            status_code=500,
            detail="private-sql-error",
            headers={"X-Secret": "private-token"},
        )

    cast(FastAPI, client.app).add_api_route("/__test/http-error", unsafe_detail)
    response = client.get("/__test/http-error")
    assert_error(response, 500, "internal_server_error")
    assert "private-sql-error" not in response.text
    assert "X-Secret" not in response.headers


def test_readiness_failure_uses_error_envelope(
    database_settings: Settings, log_output: StringIO
) -> None:
    # Reserve a local port without listening, ensuring the connection is refused.
    with socket.socket() as unused_port:
        unused_port.bind(("127.0.0.1", 0))
        settings = database_settings.model_copy(
            update={"db_host": "127.0.0.1", "db_port": unused_port.getsockname()[1]}
        )
        with TestClient(create_app(settings)) as client:
            assert client.get("/health/live").status_code == 200
            response = client.get("/health/ready")
            assert_error(response, 503, "service_unavailable")
    assert "connect" not in response.text
    assert "password" not in log_output.getvalue()


def test_openapi_documents_error_schema(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    for endpoint in ["/api/v1/users", "/api/v1/auth/token", "/api/v1/projects"]:
        response = document["paths"][endpoint]["post"]["responses"]["422"]
        assert (
            response["content"]["application/json"]["schema"]["$ref"]
            == "#/components/schemas/ErrorResponse"
        )
    readiness = document["paths"]["/health/ready"]["get"]["responses"]["503"]
    assert (
        readiness["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ErrorResponse"
    )


def test_unknown_http_method_is_not_logged_verbatim(
    client: TestClient, log_output: StringIO
) -> None:
    response = client.request("PRIVATE-METHOD-SECRET", "/health/live")
    assert_error(response, 405, "method_not_allowed")
    records = [json.loads(line) for line in log_output.getvalue().splitlines()]
    assert records[-1]["method"] == "[unknown]"
    assert "PRIVATE-METHOD-SECRET" not in log_output.getvalue()
