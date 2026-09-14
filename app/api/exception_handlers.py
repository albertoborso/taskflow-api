"""One safe error envelope for application, HTTP, and request-validation errors."""

from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.api.schemas import ErrorBody, ErrorResponse, ValidationDetail
from app.core.exceptions import (
    ApplicationError,
    AuthenticationError,
    DuplicateEmailError,
    ResourceNotFoundError,
    ServiceUnavailableError,
)

PUBLIC_ERRORS = {
    400: ("bad_request", "Request could not be understood"),
    401: ("unauthorized", "Authentication required or credentials are invalid"),
    403: ("forbidden", "Access is forbidden"),
    404: ("not_found", "Resource not found"),
    405: ("method_not_allowed", "HTTP method is not allowed for this resource"),
    409: ("email_already_registered", "Email already registered"),
    422: ("validation_error", "Request validation failed"),
    500: ("internal_server_error", "An unexpected error occurred"),
    503: ("service_unavailable", "Service temporarily unavailable"),
}

# Only declared API locations are reflected. Arbitrary JSON keys can contain secrets.
SAFE_LOCATIONS = {
    "body",
    "query",
    "path",
    "header",
    "cookie",
    "email",
    "password",
    "display_name",
    "id",
    "owner_id",
    "project_id",
    "task_id",
    "name",
    "title",
    "description",
    "status",
    "priority",
    "due_at",
    "completed_at",
    "created_at",
    "updated_at",
    "limit",
    "offset",
    "due_before",
}
SAFE_MESSAGES = {
    "missing": "Field is required",
    "extra_forbidden": "Unknown field is not allowed",
    "json_invalid": "Request body must contain valid JSON",
    "model_attributes_type": "Must be a JSON object",
    "model_type": "Must be a JSON object",
    "dict_type": "Must be a JSON object",
    "string_type": "Must be a string",
    "int_type": "Must be an integer",
    "int_parsing": "Must be an integer",
    "int_from_float": "Must be an integer",
    "uuid_parsing": "Must be a valid UUID",
    "uuid_type": "Must be a valid UUID",
    "datetime_parsing": "Must be a valid datetime",
    "datetime_from_date_parsing": "Must be a valid datetime",
    "timezone_aware": "Must include a timezone",
    "literal_error": "Must be one of the allowed values",
}
NULL_MESSAGES = {
    "Value error, Name cannot be null": "Name cannot be null",
    "Value error, title cannot be null": "Title cannot be null",
    "Value error, status cannot be null": "Status cannot be null",
    "Value error, priority cannot be null": "Priority cannot be null",
}


def error_response(
    status_code: int,
    request_id: str,
    details: list[ValidationDetail] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    code, message = PUBLIC_ERRORS.get(
        status_code, ("http_error", "Request could not be completed")
    )
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details or []),
        request_id=request_id,
    )
    response_headers = {"Cache-Control": "no-store", "X-Request-ID": request_id}
    if status_code == 401:
        response_headers.update({"WWW-Authenticate": "Bearer", "Pragma": "no-cache"})
    if headers:
        response_headers.update(headers)
    return JSONResponse(
        status_code=status_code, content=body.model_dump(), headers=response_headers
    )


def request_id_for(request: Request) -> str:
    return str(getattr(request.state, "request_id", uuid4()))


async def application_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    statuses: dict[type[ApplicationError], int] = {
        AuthenticationError: 401,
        ResourceNotFoundError: 404,
        DuplicateEmailError: 409,
        ServiceUnavailableError: 503,
    }
    for error_type, status_code in statuses.items():
        if isinstance(exc, error_type):
            return error_response(status_code, request_id_for(request))
    # Unknown application failures must reach the unexpected-error logger.
    raise exc


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, HTTPException):
        raise exc
    headers: dict[str, str] = {}
    if exc.status_code == 405 and exc.headers:
        allowed = exc.headers.get("Allow", "").split(", ")
        methods = [
            method
            for method in allowed
            if method
            in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"}
        ]
        if methods:
            headers["Allow"] = ", ".join(methods)
    # HTTPException.detail may contain SQL, secrets, or arbitrary internal text.
    return error_response(exc.status_code, request_id_for(request), headers=headers)


def validation_detail(error: dict[str, object]) -> ValidationDetail:
    raw_location = error.get("loc", ())
    location = (
        [
            item if isinstance(item, int) or item in SAFE_LOCATIONS else "[field]"
            for item in raw_location
        ]
        if isinstance(raw_location, (tuple, list))
        else []
    )
    error_type = str(error.get("type", "invalid_value"))
    message = SAFE_MESSAGES.get(error_type, "Invalid value")
    context = error.get("ctx")
    if isinstance(context, dict):
        bounds = {
            "string_too_short": ("min_length", "Must contain at least {} characters"),
            "too_short": ("min_length", "Must contain at least {} characters"),
            "string_too_long": ("max_length", "Must contain at most {} characters"),
            "too_long": ("max_length", "Must contain at most {} characters"),
            "greater_than_equal": ("ge", "Must be greater than or equal to {}"),
            "less_than_equal": ("le", "Must be less than or equal to {}"),
        }
        if error_type in bounds:
            key, template = bounds[error_type]
            if type(context.get(key)) is int:
                message = template.format(context[key])
    if error_type == "value_error":
        if location and location[-1] == "email":
            message = "Must be a valid email address"
        elif location and location[-1] == "password":
            message = "Password must not be blank"
        else:
            message = NULL_MESSAGES.get(str(error.get("msg", "")), "Invalid value")
    if error_type == "literal_error" and location and location[-1] == "status":
        message = "Must be one of: todo, in_progress, done"
    return ValidationDetail(type=error_type, loc=location, msg=message)


async def validation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    return error_response(
        422,
        request_id_for(request),
        [validation_detail(error) for error in exc.errors()],
    )
