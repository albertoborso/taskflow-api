"""Application composition and ASGI entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from app.api.exception_handlers import (
    application_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.api.health import router as health_router
from app.api.middleware import RequestLoggingMiddleware
from app.api.router import router as api_router
from app.api.schemas import ErrorResponse
from app.core.config import Settings
from app.core.exceptions import ApplicationError
from app.core.logging import configure_logging
from app.db.session import create_db_engine, create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = create_db_engine(settings)
        application.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            engine.dispose()

    application = FastAPI(
        title=settings.name,
        lifespan=lifespan,
        responses={422: {"model": ErrorResponse}, "default": {"model": ErrorResponse}},
    )
    application.add_middleware(RequestLoggingMiddleware)
    application.state.settings = settings
    application.include_router(health_router)
    application.include_router(api_router)
    application.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )
    application.add_exception_handler(ApplicationError, application_exception_handler)
    application.add_exception_handler(HTTPException, http_exception_handler)
    return application


app = create_app()
