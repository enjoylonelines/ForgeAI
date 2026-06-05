from __future__ import annotations

from contextvars import ContextVar
from functools import lru_cache
from typing import Any

from core.config import get_settings

_current_trace: ContextVar[Any] = ContextVar("langfuse_trace", default=None)


@lru_cache(maxsize=1)
def get_langfuse() -> Any | None:
    settings = get_settings()
    if not settings.langfuse_enabled:
        return None
    from langfuse import Langfuse  # noqa: PLC0415
    return Langfuse(host=settings.langfuse_host)


def set_current_trace(trace: Any) -> None:
    _current_trace.set(trace)


def get_current_trace() -> Any | None:
    return _current_trace.get()
