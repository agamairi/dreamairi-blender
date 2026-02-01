"""Validated execution engine for whitelisted tool actions."""
from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

import bpy
import bmesh

from .whitelist import get_schema


class ExecutionError(RuntimeError):
    pass


class ToolExecutor:
    def __init__(self, collection_name: str = "DreamAiri_Generated") -> None:
        self.collection_name = collection_name
        self.created_objects: List[bpy.types.Object] = []
        self._ensure_collection()

    def execute(self, actions: List[Dict[str, object]]) -> None:
        for action in actions:
            op = action.get("op")
            payload = action.get("payload", {})
            if not isinstance(op, str) or not isinstance(payload, dict):
                continue
            
            schema = get_schema(op)
            if not schema:
                continue
                
            handler = getattr(self, f"_op_{op.lower()}", None)
            if handler:
                handler(payload)

    def _ensure_collection(self) -> bpy.types.Collection:
        collection = bpy.data.collections.get(self.collection_name)
        if not collection:
            collection = bpy.data.collections.new(self.collection_name)
            bpy.context.scene.collection.children.link(collection)
        return collection

    def _link_object(self, obj: bpy.types.Object) -> None:
        collection = self._ensure_collection()
        if obj.name not in collection.objects:
            collection.objects.link(obj)
        for coll in obj.users_collection:
            if coll != collection:
                coll.objects.unlink(obj)

    def _find_object(self, name: str) -> bpy.types.Object:
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ExecutionError(f"Object not found: {name}")
        return obj

    def _op_add_primitive(self, payload: Dict[str, object]) -> None:
        prim_type = str(payload["type"]).lower()
        name = str(payload["name"])
        loc = payload.get("location", (0, 0, 0))
        rot = payload.get("rotation", (0, 0, 0))
        scale = payload.get("scale", (1, 1, 1))
        params = payload.get("params", {})
        
        bpy.ops.object.select_all(action='DESELECT')
        
        if prim_type == "cube":
            bpy.ops.mesh.primitive_cube_add(location=loc, rotation=rot, scale=scale)
        elif prim_type == "cylinder":
            bpy.ops.mesh.primitive_cylinder_add(
                location=loc, rotation=rot, scale=scale,
                radius=params.get("radius", 1.0),
                depth=params.get("depth", 2.0),
                vertices=params.get("vertices", 32)
            )
        elif prim_type == "cone":
            bpy.ops.mesh.primitive_cone_add(
                location=loc, rotation=rot, scale=scale,
                radius1=params.get("radius1", 1.0),
                radius2=params.get("radius2", 0.0),
                depth=params.get("depth", 2.0)
            )
        elif prim_type == "uv_sphere":
            bpy.ops.mesh.primitive_uv_sphere_add(
                location=loc, rotation=rot, scale=scale,
                radius=params.get("radius", 1.0)
            )
        else:
            return

        obj = bpy.context.active_object
        obj.name = name
        self._link_object(obj)
        self.created_objects.append(obj)

    def _op_rename_object(self, payload: Dict[str, object]) -> None:
        obj = self._find_object(str(payload["target"]))
        obj.name = str(payload["new_name"])

    def _op_set_transform(self, payload: Dict[str, object]) -> None:
        obj = self._find_object(str(payload["target"]))
        if "location" in payload:
            obj.location = payload["location"]
        if "rotation" in payload:
            obj.rotation_euler = payload["rotation"]
        if "scale" in payload:
            obj.scale = payload["scale"]

    def _op_modifier(self, payload: Dict[str, object]) -> None:
        obj = self._find_object(str(payload["target"]))
        mod_type = str(payload["modifier"]).upper()
        name = str(payload.get("name", mod_type))
        params = payload.get("params", {})
        
        mod = obj.modifiers.new(name=name, type=mod_type)
        for k, v in params.items():
            if hasattr(mod, k):
                # Apply caps
                if mod_type == "SUBSURF" and k == "levels":
                    v = min(v, 2)
                if mod_type == "BEVEL" and k == "segments":
                    v = min(v, 3)
                setattr(mod, k, v)

    def _op_apply_modifier(self, payload: Dict[str, object]) -> None:
        obj = self._find_object(str(payload["target"]))
        mod_name = str(payload["modifier"])
        mod = obj.modifiers.get(mod_name) or next((m for m in obj.modifiers if m.type == mod_name.upper()), None)
        if mod:
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=mod.name)

    def _op_set_shading(self, payload: Dict[str, object]) -> None:
        obj = self._find_object(str(payload["target"]))
        mode = str(payload["mode"]).upper()
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        if mode == "SMOOTH":
            bpy.ops.object.shade_smooth()
            if "auto_smooth_angle" in payload:
                obj.data.use_auto_smooth = True
                obj.data.auto_smooth_angle = payload["auto_smooth_angle"]
        else:
            bpy.ops.object.shade_flat()

    def _op_material_create(self, payload: Dict[str, object]) -> None:
        name = str(payload["name"])
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name=name)
        mat.use_nodes = True
        if "base_color" in payload:
            nodes = mat.node_tree.nodes
            bsdf = nodes.get("Principled BSDF") or nodes.new('ShaderNodeBsdfPrincipled')
            bsdf.inputs['Base Color'].default_value = payload["base_color"]

    def _op_material_assign(self, payload: Dict[str, object]) -> None:
        obj = self._find_object(str(payload["target"]))
        mat = bpy.data.materials.get(str(payload["material"]))
        if mat:
            if not obj.data.materials:
                obj.data.materials.append(mat)
            else:
                obj.data.materials[0] = mat

    def _op_join_objects(self, payload: Dict[str, object]) -> None:
        targets = [self._find_object(t) for t in payload["targets"]]
        bpy.ops.object.select_all(action='DESELECT')
        for o in targets:
            o.select_set(True)
        bpy.context.view_layer.objects.active = targets[0]
        bpy.ops.object.join()
        bpy.context.active_object.name = str(payload["name"])

    def _op_cleanup(self, payload: Dict[str, object]) -> None:
        obj = self._find_object(str(payload["target"]))
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        
        if payload.get("apply_transforms", True):
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        
        bpy.ops.object.mode_set(mode='EDIT')
        if payload.get("merge_dist", 0.0) > 0:
            bpy.ops.mesh.remove_doubles(threshold=payload["merge_dist"])
        if payload.get("recalc_normals", True):
            bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode='OBJECT')

    def _op_validate_mesh(self, payload: Dict[str, object]) -> None:
        obj = self._find_object(str(payload["target"]))
        budget = int(payload.get("budget", 800))
        tris = len(obj.data.polygons) # Simplified tri count
        if tris > budget:
            mod = obj.modifiers.new(name="AutoDecimate", type='DECIMATE')
            mod.ratio = budget / tris
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=mod.name)

    def _op_clear_selection(self, _p): bpy.ops.object.select_all(action='DESELECT')
    def _op_select_object(self, p):
        obj = self._find_object(p["name"])
        if not p.get("extend"): bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
    def _op_set_active_object(self, p): bpy.context.view_layer.objects.active = self._find_object(p["name"])
    def _op_delete_objects(self, p):
        bpy.ops.object.select_all(action='DESELECT')
        for n in p["names"]: self._find_object(n).select_set(True)
        bpy.ops.object.delete()

    def apply_decimate(self, target_tris: int) -> None:
        # Compatibility with legacy code if needed
        pass

    def apply_shading(self, mode: str) -> None:
        # Compatibility with legacy code if needed
        pass
