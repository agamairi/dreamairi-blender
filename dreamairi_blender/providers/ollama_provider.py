"""Ollama provider implementation."""
from __future__ import annotations

from typing import Dict

from .base import ProviderRequest
from ..util.cancel import CancellationToken
from ..util.http import post_json


class OllamaProvider:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/") or "http://localhost:11434"

    def send_chat(self, request: ProviderRequest, cancel_token: CancellationToken) -> str:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": request.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": request.system_prompt},
            ] + [{"role": msg.role, "content": msg.content} for msg in request.messages],
        }
        _, data = post_json(url, payload, headers={}, timeout=request.timeout_seconds, cancel_token=cancel_token)
        return _extract_content(data)


def _extract_content(response: Dict) -> str:
    message = response.get("message") or {}
    content = message.get("content")
    if not isinstance(content, str):
        raise RuntimeError("Provider response missing content")
    return content
