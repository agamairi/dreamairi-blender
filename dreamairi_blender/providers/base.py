"""Provider interface definitions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..util.cancel import CancellationToken


@dataclass
class ProviderRequest:
    model: str
    system_prompt: str
    user_prompt: str


class Provider(Protocol):
    def send_chat(self, request: ProviderRequest, cancel_token: CancellationToken) -> str:
        ...
