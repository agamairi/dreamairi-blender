"""Shared error taxonomy for agent and tool execution."""
from __future__ import annotations

ERROR_VALIDATION = "validation_error"
ERROR_TOOL = "tool_error"
ERROR_BLENDER = "blender_error"
ERROR_MODEL = "model_error"

KNOWN_ERROR_TYPES = {
    ERROR_VALIDATION,
    ERROR_TOOL,
    ERROR_BLENDER,
    ERROR_MODEL,
}

