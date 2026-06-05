from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from core.config import get_settings


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        if isinstance(msg, dict):
            payload = msg
        else:
            payload = {"message": msg}

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            **payload,
        }
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


_configured = False


def get_logger(name: str) -> logging.Logger:
    global _configured
    if not _configured:
        settings = get_settings()
        root = logging.getLogger()
        root.setLevel(settings.log_level)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
        root.handlers = [handler]
        _configured = True
    return logging.getLogger(name)
