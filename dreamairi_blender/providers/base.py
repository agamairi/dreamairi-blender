"""Provider interface definitions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..util.cancel import CancellationToken


@dataclass
class ProviderMessage:
    role: str
    content: str


@dataclass
class ProviderRequest:
    model: str
    system_prompt: str
    messages: list[ProviderMessage]
    timeout_seconds: float = 60.0


class Provider(Protocol):
    def send_chat(self, request: ProviderRequest, cancel_token: CancellationToken) -> str:
        ...
