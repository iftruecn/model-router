"""
Structured JSON logging for Model Router v1.1.0.

Provides a zero-dependency JSON log formatter that outputs structured
log lines suitable for production log aggregation (ELK, Loki, etc.).

Usage:
    from model_router.core.logging import setup_logging
    setup_logging(level="INFO", json_format=True)

Or via environment variable:
    MODEL_ROUTER_LOG_FORMAT=json  -> JSON structured logs
    MODEL_ROUTER_LOG_FORMAT=text  -> Human-readable text (default)
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional


class JsonFormatter(logging.Formatter):
    """
    Format log records as single-line JSON objects.

    Output schema:
    {
        "ts": "2026-08-03T12:00:00.000Z",
        "level": "INFO",
        "logger": "model_router.core.router",
        "msg": "Routing request",
        "module": "router",
        "function": "route",
        "line": 42,
        // extra fields merged at top level if present
    }
    """

    # Keys from LogRecord that are internal / not useful in JSON output
    _SKIP_KEYS = {
        "name", "msg", "args", "created", "relativeCreated",
        "exc_info", "exc_text", "stack_info", "lineno", "filename",
        "module", "pathname", "funcName", "levelno", "levelname",
        "msecs", "process", "processName", "thread", "threadName",
        "message", "asctime", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON string."""
        # Timestamp in ISO 8601 UTC
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc)
        ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z"

        obj = {
            "ts": ts_str,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Merge extra fields (e.g. request_id, model, cost)
        for key, value in record.__dict__.items():
            if key not in self._SKIP_KEYS and not key.startswith("_"):
                if key not in obj:
                    obj[key] = value

        # Exception info
        if record.exc_info and record.exc_info[0] is not None:
            obj["exception"] = self.formatException(record.exc_info)

        # Stack info
        if record.stack_info:
            obj["stack"] = self.formatStack(record.stack_info)

        return json.dumps(obj, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """
    Human-readable text formatter (default for development).

    Format: [HH:MM:SS] [LEVEL] logger: message
    """

    def __init__(self) -> None:
        super().__init__(
            fmt="[%(asctime)s] [%(levelname)-5s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )


def get_log_format() -> str:
    """
    Determine log format from environment variable.

    MODEL_ROUTER_LOG_FORMAT=json -> JSON structured logs
    MODEL_ROUTER_LOG_FORMAT=text -> Human-readable text (default)
    """
    fmt = os.environ.get("MODEL_ROUTER_LOG_FORMAT", "text").lower().strip()
    if fmt in ("json", "structured"):
        return "json"
    return "text"


def setup_logging(
    level: str = "INFO",
    json_format: Optional[bool] = None,
) -> None:
    """
    Configure logging with either JSON or text format.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR).
        json_format: Force JSON (True) or text (False).
                     None = auto-detect from MODEL_ROUTER_LOG_FORMAT env var.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Determine format
    if json_format is None:
        fmt = get_log_format()
    else:
        fmt = "json" if json_format else "text"

    # Create formatter
    if fmt == "json":
        formatter = JsonFormatter()
    else:
        formatter = TextFormatter()

    # Configure root logger
    root = logging.getLogger()
    root.setLevel(log_level)

    # Replace existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Reduce noise from third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    _logger = logging.getLogger(__name__)
    _logger.info(
        "Logging configured: level=%s format=%s",
        level, fmt,
    )
