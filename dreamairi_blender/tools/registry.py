"""Tool registry for allowed operations."""
from __future__ import annotations

from typing import Callable, Dict

from .schema import ToolSchema, get_schema


class ToolRegistry:
    def __init__(self) -> None:
        self._handlers: Dict[str, Callable[[dict], None]] = {}

    def register(self, op: str, handler: Callable[[dict], None]) -> None:
        self._handlers[op] = handler

    def handler_for(self, op: str) -> Callable[[dict], None]:
        if op not in self._handlers:
            raise RuntimeError(f"Unsupported operation: {op}")
        return self._handlers[op]

    def schema_for(self, op: str) -> ToolSchema:
        schema = get_schema(op)
        if schema is None:
            raise RuntimeError(f"Unknown operation: {op}")
        return schema
