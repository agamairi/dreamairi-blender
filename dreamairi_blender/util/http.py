"""Minimal HTTP wrapper using urllib."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

from .cancel import CancellationToken


class HttpError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


def post_json(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: float,
    cancel_token: Optional[CancellationToken] = None,
) -> Tuple[int, Dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    for key, value in headers.items():
        request.add_header(key, value)
    request.add_header("Content-Type", "application/json")

    if cancel_token and cancel_token.is_cancelled():
        raise RuntimeError("Request cancelled")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.getcode()
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else str(exc)
        raise HttpError(exc.code, body) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc}") from exc

    if cancel_token and cancel_token.is_cancelled():
        raise RuntimeError("Request cancelled")

    try:
        parsed = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid JSON response") from exc

    return status, parsed


def get_json(
    url: str,
    headers: Dict[str, str],
    timeout: float,
    cancel_token: Optional[CancellationToken] = None,
) -> Tuple[int, Dict[str, Any]]:
    request = urllib.request.Request(url, method="GET")
    for key, value in headers.items():
        request.add_header(key, value)

    if cancel_token and cancel_token.is_cancelled():
        raise RuntimeError("Request cancelled")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.getcode()
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else str(exc)
        raise HttpError(exc.code, body) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc}") from exc

    if cancel_token and cancel_token.is_cancelled():
        raise RuntimeError("Request cancelled")

    try:
        parsed = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid JSON response") from exc

    return status, parsed
