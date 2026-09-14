"""Versioned application API routes."""

from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.projects.router import router as projects_router
from app.modules.tasks.router import router as tasks_router
from app.modules.users.router import router as users_router

router = APIRouter(prefix="/api/v1")
router.include_router(users_router)
router.include_router(auth_router)

router.include_router(projects_router)
router.include_router(tasks_router)
