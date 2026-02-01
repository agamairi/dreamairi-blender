"""Secret handling utilities.

When remember_key is disabled, keep secrets in memory only.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SecretsStore:
    api_key: str = ""

    def set_api_key(self, value: str) -> None:
        self.api_key = value

    def get_api_key(self) -> str:
        return self.api_key


IN_MEMORY_SECRETS = SecretsStore()
