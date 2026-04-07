"""Tool registry, schema validation, permissions, and safe execution."""
from __future__ import annotations

import inspect
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set

from ..core.errors import ERROR_BLENDER, ERROR_TOOL, ERROR_VALIDATION


DEFAULT_PERMISSIONS: Set[str] = {
    "scene:read",
    "scene:write",
    "anim:read",
    "anim:write",
    "file:read",
    "file:write",
    "diagnostics:read",
    "render:read",
}


@dataclass
class ToolResult:
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error_type: str = ""
    tool_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "success": self.success,
            "message": self.message,
            "error_type": self.error_type or "",
            "data": self.data or {},
        }
        if self.tool_name:
            payload["tool"] = self.tool_name
        return payload


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    description: str
    args_schema: Dict[str, Any]
    permissions: List[str]


@dataclass
class ToolExecutionContext:
    granted_permissions: Set[str] = field(default_factory=lambda: set(DEFAULT_PERMISSIONS))
    workspace_root: str = ""

    def workspace_path(self) -> Optional[Path]:
        raw = self.workspace_root.strip()
        if not raw:
            return None
        return Path(raw).resolve()


class ToolExecutionException(RuntimeError):
    def __init__(self, message: str, error_type: str = ERROR_TOOL, data: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.data = data or {}


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _normalize_type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _validate_json_schema(schema: Dict[str, Any], value: Any, path: str = "$") -> List[str]:
    errors: List[str] = []
    if not isinstance(schema, dict):
        return [f"{path}: invalid schema definition"]

    expected = schema.get("type")
    expected_values: Sequence[str]
    if expected is None:
        expected_values = ()
    elif isinstance(expected, str):
        expected_values = (expected,)
    elif isinstance(expected, list) and all(isinstance(item, str) for item in expected):
        expected_values = tuple(expected)
    else:
        return [f"{path}: invalid schema 'type' value"]

    actual_name = _normalize_type_name(value)

    def type_match(name: str) -> bool:
        if name == "number":
            return _is_number(value)
        if name == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if name == "boolean":
            return isinstance(value, bool)
        if name == "string":
            return isinstance(value, str)
        if name == "array":
            return isinstance(value, list)
        if name == "object":
            return isinstance(value, dict)
        if name == "null":
            return value is None
        return False

    if expected_values and not any(type_match(item) for item in expected_values):
        readable = ", ".join(expected_values)
        errors.append(f"{path}: expected {readable}, got {actual_name}")
        return errors

    if "enum" in schema:
        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and value not in enum_values:
            errors.append(f"{path}: value '{value}' is not in enum {enum_values}")

    if isinstance(value, str):
        min_len = schema.get("minLength")
        if isinstance(min_len, int) and len(value) < min_len:
            errors.append(f"{path}: length must be >= {min_len}")
        max_len = schema.get("maxLength")
        if isinstance(max_len, int) and len(value) > max_len:
            errors.append(f"{path}: length must be <= {max_len}")

    if _is_number(value):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and float(value) < float(minimum):
            errors.append(f"{path}: value must be >= {minimum}")
        maximum = schema.get("maximum")
        if isinstance(maximum, (int, float)) and float(value) > float(maximum):
            errors.append(f"{path}: value must be <= {maximum}")

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"{path}: must contain at least {min_items} items")
        max_items = schema.get("maxItems")
        if isinstance(max_items, int) and len(value) > max_items:
            errors.append(f"{path}: must contain at most {max_items} items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                errors.extend(_validate_json_schema(item_schema, item, f"{path}[{idx}]"))

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            errors.append(f"{path}: schema 'properties' must be an object")
            return errors
        required = schema.get("required", [])
        if isinstance(required, list):
            missing = [item for item in required if item not in value]
            if missing:
                errors.append(f"{path}: missing required fields {missing}")
        additional = schema.get("additionalProperties", False)
        for key, child in value.items():
            if key in properties and isinstance(properties[key], dict):
                errors.extend(_validate_json_schema(properties[key], child, f"{path}.{key}"))
                continue
            if additional is False:
                errors.append(f"{path}.{key}: unknown field")
                continue
            if isinstance(additional, dict):
                errors.extend(_validate_json_schema(additional, child, f"{path}.{key}"))

    return errors


def _infer_error_type(exc: Exception) -> str:
    text = str(exc).lower()
    if "bpy" in text or "blender" in text:
        return ERROR_BLENDER
    return ERROR_TOOL


class AgentToolRegistry:
    def __init__(self, autodiscover_tools: bool = False) -> None:
        self._tools: Dict[str, ToolMetadata] = {}
        self._handlers: Dict[str, Callable[..., ToolResult]] = {}
        self._autodiscover_tools = autodiscover_tools

    def _ensure_default_tools(self) -> None:
        if self._autodiscover_tools:
            ensure_builtin_tools_registered()

    def register(self, metadata: ToolMetadata, handler: Callable[..., ToolResult], *, allow_replace: bool = True) -> None:
        if not allow_replace and metadata.name in self._tools:
            raise ValueError(f"Tool '{metadata.name}' already registered")
        self._tools[metadata.name] = metadata
        self._handlers[metadata.name] = handler

    def get_tool(self, name: str) -> Optional[ToolMetadata]:
        self._ensure_default_tools()
        return self._tools.get(name)

    def list_tools(self) -> List[ToolMetadata]:
        self._ensure_default_tools()
        return list(self._tools.values())

    def validate_args(self, name: str, args: Dict[str, Any]) -> ToolResult:
        self._ensure_default_tools()
        meta = self._tools.get(name)
        if not meta:
            return ToolResult(False, f"Tool '{name}' not found.", error_type=ERROR_VALIDATION, tool_name=name)
        if not isinstance(args, dict):
            return ToolResult(False, "Tool args must be a JSON object.", error_type=ERROR_VALIDATION, tool_name=name)
        errors = _validate_json_schema(meta.args_schema, args)
        if errors:
            return ToolResult(
                False,
                f"Invalid arguments for '{name}': {errors[0]}",
                data={"errors": errors},
                error_type=ERROR_VALIDATION,
                tool_name=name,
            )
        return ToolResult(True, "Validation passed", tool_name=name)

    def _validate_permissions(self, meta: ToolMetadata, context: Optional[ToolExecutionContext]) -> Optional[ToolResult]:
        granted = set(DEFAULT_PERMISSIONS)
        if context is not None:
            granted = set(context.granted_permissions or set())
        missing = sorted(set(meta.permissions) - granted)
        if missing:
            return ToolResult(
                False,
                f"Permission denied for '{meta.name}'. Missing: {missing}",
                data={"missing_permissions": missing},
                error_type=ERROR_VALIDATION,
                tool_name=meta.name,
            )
        return None

    def execute(self, name: str, args: Dict[str, Any], context: Optional[ToolExecutionContext] = None) -> ToolResult:
        self._ensure_default_tools()
        meta = self._tools.get(name)
        if not meta:
            return ToolResult(False, f"Tool '{name}' not found.", error_type=ERROR_VALIDATION, tool_name=name)

        permission_error = self._validate_permissions(meta, context)
        if permission_error:
            return permission_error

        validation = self.validate_args(name, args)
        if not validation.success:
            return validation

        handler = self._handlers.get(name)
        if handler is None:
            return ToolResult(False, f"Handler for '{name}' not found.", error_type=ERROR_TOOL, tool_name=name)

        try:
            signature = inspect.signature(handler)
            if len(signature.parameters) >= 2:
                result = handler(args, context)
            else:
                result = handler(args)
        except ToolExecutionException as exc:
            data = {"traceback": traceback.format_exc()}
            data.update(exc.data)
            return ToolResult(
                False,
                str(exc),
                data=data,
                error_type=exc.error_type,
                tool_name=name,
            )
        except Exception as exc:
            return ToolResult(
                False,
                f"Tool execution failed: {exc}",
                data={"traceback": traceback.format_exc()},
                error_type=_infer_error_type(exc),
                tool_name=name,
            )

        if isinstance(result, ToolResult):
            if not result.tool_name:
                result.tool_name = name
            if not result.success and not result.error_type:
                result.error_type = ERROR_TOOL
            return result

        return ToolResult(
            False,
            f"Tool '{name}' returned invalid result type {type(result).__name__}",
            error_type=ERROR_TOOL,
            tool_name=name,
        )


agent_registry = AgentToolRegistry(autodiscover_tools=True)
_DEFAULT_TOOLS_READY = False


def ensure_builtin_tools_registered() -> None:
    global _DEFAULT_TOOLS_READY
    if _DEFAULT_TOOLS_READY:
        return
    _DEFAULT_TOOLS_READY = True
    try:
        from . import implementations

        register_fn = getattr(implementations, "register_default_tools", None)
        if callable(register_fn):
            register_fn(agent_registry)
    except Exception:
        # Allow non-Blender unit tests to import the registry without bpy.
        return
