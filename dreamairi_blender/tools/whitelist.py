"""Whitelist definitions for allowed ops."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple


@dataclass(frozen=True)
class OpSchema:
    name: str
    required: Set[str]
    optional: Set[str]

    def validate(self, payload: Dict[str, object]) -> Optional[str]:
        missing = self.required - payload.keys()
        if missing:
            return f"Missing required fields: {sorted(missing)}"
        unknown = payload.keys() - (self.required | self.optional)
        if unknown:
            return f"Unknown fields: {sorted(unknown)}"
        return None


OP_SCHEMAS: Dict[str, OpSchema] = {
    "ADD_PRIMITIVE": OpSchema("ADD_PRIMITIVE", {"type", "name"}, {"location", "rotation", "scale", "params"}),
    "RENAME_OBJECT": OpSchema("RENAME_OBJECT", {"target", "new_name"}, set()),
    "SET_TRANSFORM": OpSchema("SET_TRANSFORM", {"target"}, {"location", "rotation", "scale"}),
    "MODIFIER": OpSchema("MODIFIER", {"target", "modifier"}, {"name", "params"}),
    "APPLY_MODIFIER": OpSchema("APPLY_MODIFIER", {"target", "modifier"}, set()),
    "SET_SHADING": OpSchema("SET_SHADING", {"target", "mode"}, {"auto_smooth_angle"}),
    "MATERIAL_CREATE": OpSchema("MATERIAL_CREATE", {"name"}, {"base_color"}),
    "MATERIAL_ASSIGN": OpSchema("MATERIAL_ASSIGN", {"target", "material"}, set()),
    "JOIN_OBJECTS": OpSchema("JOIN_OBJECTS", {"targets", "name"}, set()),
    "CLEANUP": OpSchema("CLEANUP", {"target"}, {"apply_transforms", "recalc_normals", "merge_dist"}),
    "VALIDATE_MESH": OpSchema("VALIDATE_MESH", {"target"}, {"budget"}),
    "DELETE_OBJECTS": OpSchema("DELETE_OBJECTS", {"names"}, set()),
    "CLEAR_SELECTION": OpSchema("CLEAR_SELECTION", set(), set()),
    "SELECT_OBJECT": OpSchema("SELECT_OBJECT", {"name"}, {"extend"}),
    "SET_ACTIVE_OBJECT": OpSchema("SET_ACTIVE_OBJECT", {"name"}, set()),
}


def get_schema(name: str) -> Optional[OpSchema]:
    return OP_SCHEMAS.get(name)


def allowed_ops() -> Iterable[str]:
    return OP_SCHEMAS.keys()


def is_primitive(op_name: str) -> bool:
    return op_name.startswith("ADD_")


def modifier_limit(modifier: str) -> Tuple[int, str]:
    caps = {
        "SUBSURF": (2, "levels"),
        "BEVEL": (6, "segments"),
        "DECIMATE": (1, "ratio"),
        "SOLIDIFY": (1, "thickness"),
    }
    return caps.get(modifier.upper(), (0, ""))
