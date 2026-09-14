"""JSON application logs with explicit fields and safe exception context."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
logger = logging.getLogger("portfolio")
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_context.get()),
        }
        for field in (
            "method",
            "path",
            "status_code",
            "duration_ms",
            "exception_type",
            "traceback",
        ):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        # Never serialize arbitrary extras, exception messages, args, or locals.
        return json.dumps(payload, ensure_ascii=True)


def exception_context(exc: Exception) -> dict[str, object]:
    frames: list[dict[str, object]] = []
    traceback = exc.__traceback__
    while traceback is not None:
        code = traceback.tb_frame.f_code
        filename = Path(code.co_filename)
        try:
            display_path = str(filename.relative_to(_PROJECT_ROOT))
        except ValueError:
            display_path = filename.name
        frames.append(
            {
                "file": display_path,
                "line": traceback.tb_lineno,
                "function": code.co_name,
            }
        )
        traceback = traceback.tb_next
    return {
        "exception_type": f"{type(exc).__module__}.{type(exc).__qualname__}",
        "traceback": frames[-20:],
    }


def configure_logging() -> None:
    """Install one application handler without modifying the root logger."""
    if not any(handler.name == "portfolio_json" for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.name = "portfolio_json"
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # Uvicorn's access log contains raw URLs/query strings; ours replaces it.
    logging.getLogger("uvicorn.access").disabled = True
