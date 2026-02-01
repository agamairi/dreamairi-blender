"""Schema definitions for tool actions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Set


@dataclass(frozen=True)
class ToolSchema:
    name: str
    required_args: Set[str]
    optional_args: Set[str]

    def validate(self, args: Dict[str, object]) -> Optional[str]:
        missing = self.required_args.difference(args.keys())
        if missing:
            return f"Missing required args: {sorted(missing)}"
        unknown = set(args.keys()).difference(self.required_args | self.optional_args)
        if unknown:
            return f"Unknown args: {sorted(unknown)}"
        return None


TOOL_SCHEMAS = {
    "CREATE_COLLECTION": ToolSchema("CREATE_COLLECTION", {"name"}, set()),
    "ADD_PRIMITIVE": ToolSchema(
        "ADD_PRIMITIVE",
        {"type"},
        {"location", "rotation", "scale", "params"},
    ),
    "TRANSFORM_OBJECT": ToolSchema(
        "TRANSFORM_OBJECT",
        {"target"},
        {"location", "rotation", "scale"},
    ),
    "RENAME_OBJECT": ToolSchema("RENAME_OBJECT", {"old", "new"}, set()),
    "DUPLICATE_OBJECT": ToolSchema("DUPLICATE_OBJECT", {"target"}, {"linked"}),
    "JOIN_OBJECTS": ToolSchema("JOIN_OBJECTS", {"targets", "new_name"}, set()),
    "APPLY_MODIFIER": ToolSchema(
        "APPLY_MODIFIER",
        {"target", "type"},
        {"params"},
    ),
    "SET_SHADING": ToolSchema(
        "SET_SHADING",
        {"target", "mode"},
        {"autosmooth_angle"},
    ),
    "SET_MATERIAL_SOLID": ToolSchema(
        "SET_MATERIAL_SOLID",
        {"target", "material_name", "rgba"},
        set(),
    ),
    "ASSIGN_MATERIAL": ToolSchema(
        "ASSIGN_MATERIAL",
        {"target", "material_name"},
        set(),
    ),
    "CLEANUP": ToolSchema("CLEANUP", {"target"}, set()),
}


def get_schema(op: str) -> Optional[ToolSchema]:
    return TOOL_SCHEMAS.get(op)


def allowed_ops() -> Iterable[str]:
    return TOOL_SCHEMAS.keys()
