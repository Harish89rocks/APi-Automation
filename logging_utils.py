import json
import logging
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Format log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for field in (
            "correlation_id",
            "attempt",
            "method",
            "endpoint",
            "duration_ms",
            "status_code",
            "outcome",
            "error_type",
        ):
            value = getattr(record, field, None)
            if value is not None:
                event[field] = value

        return json.dumps(event)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure JSON logging once for the application."""
    root_logger = logging.getLogger()

    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        root_logger.addHandler(handler)

    root_logger.setLevel(level)
