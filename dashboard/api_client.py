from __future__ import annotations

import os
from typing import Any

import requests

_BASE_URL = os.getenv("FORGEAI_API_URL", "http://localhost:8000").rstrip("/")
_TIMEOUT = 180


def health() -> dict[str, Any]:
    resp = requests.get(f"{_BASE_URL}/api/v1/health", timeout=10)
    resp.raise_for_status()
    return resp.json()


def analyze(log_dict: dict[str, Any]) -> dict[str, Any]:
    resp = requests.post(f"{_BASE_URL}/api/v1/analyze", json=log_dict, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def analyze_csv(file_bytes: bytes, filename: str) -> dict[str, Any]:
    resp = requests.post(
        f"{_BASE_URL}/api/v1/analyze/csv",
        files={"file": (filename, file_bytes, "text/csv")},
        timeout=_TIMEOUT * 10,
    )
    resp.raise_for_status()
    return resp.json()


def get_base_url() -> str:
    return _BASE_URL
