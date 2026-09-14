"""Pure ASGI request correlation, safe access logs, and unexpected-error boundary."""

import logging
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.routing import NoMatchFound
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.exception_handlers import error_response
from app.core.logging import exception_context, logger, request_id_context

HTTP_METHODS = {
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
    "TRACE",
    "CONNECT",
}


def route_template(scope: Scope) -> str:
    application = scope["app"]
    route = scope.get("route")
    if route is None and scope.get("endpoint") is not None:
        route = next(
            (
                candidate
                for candidate in application.routes
                if getattr(candidate, "endpoint", None) is scope["endpoint"]
            ),
            None,
        )
    if route is None:
        return "[unmatched]"
    placeholders = {name: "{" + name + "}" for name in route.param_convertors}
    try:
        # Reverse routing includes nested router prefixes without reading raw URLs.
        return str(application.url_path_for(route.name, **placeholders))
    except (NoMatchFound, ValueError, TypeError, AssertionError):
        return str(route.path)


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        context_token = request_id_context.set(request_id)
        started = perf_counter()
        status_code = 500
        response_started = False
        failure: dict[str, object] = {}

        async def send_with_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            failure = exception_context(exc)
            if response_started:
                # A response already on the wire cannot be replaced. Do not let
                # Uvicorn print the original exception's potentially secret text.
                raise RuntimeError("Response failed after headers were sent") from None
            response = error_response(500, request_id)
            await response(scope, receive, send_with_id)
        finally:
            try:
                # Never log raw URLs: dynamic path values and query strings may
                # contain tokens or personal data. Unknown paths are not reflected.
                path = route_template(scope)
                logger.log(
                    logging.ERROR if failure or status_code >= 500 else logging.INFO,
                    "request_failed" if failure else "request_completed",
                    extra={
                        "request_id": request_id,
                        "method": scope["method"]
                        if scope["method"] in HTTP_METHODS
                        else "[unknown]",
                        "path": path,
                        "status_code": status_code,
                        "duration_ms": round((perf_counter() - started) * 1000, 3),
                        **failure,
                    },
                )
            finally:
                request_id_context.reset(context_token)
