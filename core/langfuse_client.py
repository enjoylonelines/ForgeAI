from __future__ import annotations

from functools import lru_cache
from typing import Any

from core.config import get_settings


@lru_cache(maxsize=1)
def get_langfuse() -> Any | None:
    settings = get_settings()
    if not settings.langfuse_enabled:
        return None
    from langfuse import Langfuse  # noqa: PLC0415
    return Langfuse(host=settings.langfuse_host)


def set_current_trace(trace: Any) -> None:
    # no-op: v4 uses OTEL context propagation automatically
    pass


def get_current_trace() -> Any | None:
    # Deprecated: returns the Langfuse client for backwards compatibility.
    # v4 uses OTEL context propagation; use get_langfuse() directly.
    return get_langfuse()
