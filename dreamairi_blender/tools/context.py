"""Scene context extraction."""
from __future__ import annotations

from typing import Dict

import bpy

from ..util.style_presets import get_style_preset


def _object_tri_count(obj: bpy.types.Object) -> int:
    if obj.type != 'MESH':
        return 0
    return len(obj.data.polygons)


def build_scene_context(settings: object) -> Dict[str, object]:
    context = bpy.context
    selected = context.selected_objects or []
    collections = [col.name for col in bpy.data.collections]
    active = context.active_object.name if context.active_object else None
    style = get_style_preset(settings.style_preset)
    return {
        "blender_version": bpy.app.version_string,
        "units": {
            "system": context.scene.unit_settings.system,
            "scale_length": context.scene.unit_settings.scale_length,
        },
        "selected_objects": [
            {
                "name": obj.name,
                "type": obj.type,
                "triangles": _object_tri_count(obj),
            }
            for obj in selected
        ],
        "collections": collections,
        "active_object": active,
        "style_preset": {
            "name": style.name,
            "poly_budget": style.poly_budget,
            "bevel_range": style.bevel_range,
            "flat_shading": style.flat_shading,
        },
        "target_poly_budget": settings.triangle_budget,
    }
