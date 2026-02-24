"""Gemini provider implementation."""
from __future__ import annotations

from typing import Dict

from .base import ProviderRequest
from ..util.cancel import CancellationToken
from ..util.http import post_json


class GeminiProvider:
    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/") or "https://generativelanguage.googleapis.com/v1beta"

    def send_chat(self, request: ProviderRequest, cancel_token: CancellationToken) -> str:
        url = (
            f"{self.base_url}/models/{request.model}:generateContent"
            f"?key={self.api_key}"
        )
        payload = {
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
            "contents": [
                {
                    "role": "user" if msg.role == "user" else "model",
                    "parts": [{"text": msg.content}]
                }
                for msg in request.messages
            ],
        }
        _, data = post_json(url, payload, headers={}, timeout=request.timeout_seconds, cancel_token=cancel_token)
        return _extract_content(data)


def _extract_content(response: Dict) -> str:
    candidates = response.get("candidates") or []
    if not candidates:
        raise RuntimeError("No candidates returned by provider")
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    if not parts:
        raise RuntimeError("Provider response missing content")
    text = parts[0].get("text")
    if not isinstance(text, str):
        raise RuntimeError("Provider response missing text")
    return text
