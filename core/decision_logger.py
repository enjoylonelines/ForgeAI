from __future__ import annotations

import os
import threading

from models.decision_event import DecisionEvent

_lock = threading.Lock()


def append(event: DecisionEvent) -> None:
    from core.config import get_settings
    path = get_settings().decision_log_path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    line = event.model_dump_json() + "\n"
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
