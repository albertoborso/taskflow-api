"""Import all mapped models so Alembic can discover their table metadata."""

from app.modules.projects.model import Project
from app.modules.tasks.model import Task
from app.modules.users.model import User

__all__ = ["Project", "Task", "User"]
