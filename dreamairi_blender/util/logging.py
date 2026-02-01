"""Logging helpers for DreamAiri-blender."""
from __future__ import annotations

from dataclasses import dataclass


MAX_LOG_CHARS = 8000


@dataclass
class LogBuffer:
    text: str = ""

    def append(self, message: str) -> None:
        cleaned = message.strip()
        if not cleaned:
            return
        if self.text:
            self.text += "\n"
        self.text += cleaned
        if len(self.text) > MAX_LOG_CHARS:
            self.text = self.text[-MAX_LOG_CHARS:]
