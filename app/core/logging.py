import json
import logging
from datetime import UTC, datetime


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }

        for field in (
            "request_id",
            "connection_id",
            "robot_id",
            "method",
            "path",
            "status_code",
        ):
            value = getattr(record, field, None)
            if value is not None:
                log_data[field] = value

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())

    logger = logging.getLogger("fleetlink")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
