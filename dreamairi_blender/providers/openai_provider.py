"""OpenAI provider implementation."""
from __future__ import annotations

from typing import Dict

from .base import ProviderRequest
from ..util.cancel import CancellationToken
from ..util.http import post_json


class OpenAIProvider:
    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def send_chat(self, request: ProviderRequest, cancel_token: CancellationToken) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": request.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
        }
        _, data = post_json(url, payload, headers, timeout=60.0, cancel_token=cancel_token)
        return _extract_content(data)


def _extract_content(response: Dict) -> str:
    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError("No choices returned by provider")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str):
        raise RuntimeError("Provider response missing content")
    return content
