"""Default whitelisted tool implementations for agent execution."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ..core.errors import ERROR_BLENDER, ERROR_TOOL, ERROR_VALIDATION
from .registry import (
    AgentToolRegistry,
    ToolExecutionContext,
    ToolExecutionException,
    ToolMetadata,
    ToolResult,
    agent_registry,
)

try:  # pragma: no cover - exercised in Blender integration and smoke tests
    import bpy  # type: ignore
except Exception:  # pragma: no cover
    bpy = None


MAX_FILE_BYTES = 64 * 1024
MAX_FILE_LINES = 1000
DEFAULT_PREVIEW_WIDTH = 512
DEFAULT_PREVIEW_HEIGHT = 512
MIN_PREVIEW_SIZE = 64
MAX_PREVIEW_SIZE = 2048
DEFAULT_PROFILE_SAMPLE_COUNT = 5
MAX_PROFILE_SAMPLE_COUNT = 64
DEFAULT_TURNTABLE_VIEWS = ("front", "side", "perspective")

_REGISTERED_REGISTRIES: Set[int] = set()


def _require_bpy() -> Any:
    if bpy is None:
        raise ToolExecutionException("Blender bpy module is unavailable.", error_type=ERROR_BLENDER)
    return bpy


def _vector(value: Optional[Sequence[Any]], size: int, fallback: Sequence[float]) -> Tuple[float, ...]:
    if value is None:
        return tuple(float(v) for v in fallback)
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ToolExecutionException(
            f"Expected a list of {size} numbers.",
            error_type=ERROR_VALIDATION,
        )
    result: List[float] = []
    for item in value:
        if not isinstance(item, (int, float)):
            raise ToolExecutionException("Vector items must be numbers.", error_type=ERROR_VALIDATION)
        result.append(float(item))
    return tuple(result)


def _color_rgba(value: Optional[Sequence[Any]]) -> Optional[Tuple[float, float, float, float]]:
    if value is None:
        return None
    rgba = _vector(value, 4, (1.0, 1.0, 1.0, 1.0))
    return tuple(min(1.0, max(0.0, c)) for c in rgba)  # type: ignore[return-value]


def _workspace_root(exec_ctx: Optional[ToolExecutionContext]) -> Path:
    if exec_ctx is not None:
        explicit = exec_ctx.workspace_path()
        if explicit is not None:
            explicit.mkdir(parents=True, exist_ok=True)
            return explicit

    blender = _require_bpy()
    blend_root = blender.path.abspath("//")
    if blend_root:
        root = Path(blend_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    temp_root = Path(getattr(blender.app, "tempdir", "") or tempfile.gettempdir()).resolve()
    workspace = temp_root / "dreamairi_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _resolve_workspace_path(
    raw_path: str,
    exec_ctx: Optional[ToolExecutionContext],
    *,
    must_exist: bool = False,
    allow_parent_create: bool = False,
) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ToolExecutionException("Path is required.", error_type=ERROR_VALIDATION)
    root = _workspace_root(exec_ctx)
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ToolExecutionException(
            "Path is outside workspace root.",
            error_type=ERROR_VALIDATION,
            data={"workspace_root": str(root), "path": str(candidate)},
        ) from exc
    if must_exist and not candidate.exists():
        raise ToolExecutionException(
            "Path does not exist.",
            error_type=ERROR_TOOL,
            data={"path": str(candidate)},
        )
    if allow_parent_create:
        candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def _safe_export_filename(filename: str, extension: str) -> str:
    name = os.path.basename(filename.strip())
    if not name:
        raise ToolExecutionException("Filename is required.", error_type=ERROR_VALIDATION)
    ext = extension.lower().lstrip(".")
    if not name.lower().endswith(f".{ext}"):
        name = f"{name}.{ext}"
    return name


def _require_object(name: str) -> Any:
    blender = _require_bpy()
    obj = blender.data.objects.get(name)
    if obj is None:
        raise ToolExecutionException(
            f"Object '{name}' not found.",
            error_type=ERROR_TOOL,
            data={"object": name},
        )
    return obj


def _as_data(result_message: str, **data: Any) -> ToolResult:
    return ToolResult(True, result_message, data=data, error_type="", tool_name="")


SNAPSHOT_VIEW_OPTIONS = ("front", "side", "top", "perspective")
AXIS_OPTIONS = ("x", "y", "z")


def _round_float(value: Any) -> float:
    return round(float(value), 6)


def _coerce_xyz(value: Any, fallback: Optional[Tuple[float, float, float]] = None) -> Tuple[float, float, float]:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "z"):
        return (float(value.x), float(value.y), float(value.z))
    if fallback is not None:
        return (float(fallback[0]), float(fallback[1]), float(fallback[2]))
    raise ValueError("Expected a 3D coordinate.")


def _vector_list(value: Any, fallback: Tuple[float, float, float] = (0.0, 0.0, 0.0)) -> List[float]:
    return [_round_float(item) for item in _coerce_xyz(value, fallback)]


def _vector_dict(value: Any, fallback: Tuple[float, float, float] = (0.0, 0.0, 0.0)) -> Dict[str, float]:
    x, y, z = _coerce_xyz(value, fallback)
    return {"x": _round_float(x), "y": _round_float(y), "z": _round_float(z)}


def _normalize_snapshot_view(value: Any) -> str:
    view = str(value or "perspective").strip().lower()
    if view not in SNAPSHOT_VIEW_OPTIONS:
        raise ToolExecutionException(
            f"Invalid view '{view}'. Expected one of {list(SNAPSHOT_VIEW_OPTIONS)}.",
            error_type=ERROR_VALIDATION,
        )
    return view


def _axis_index(value: Any) -> int:
    axis = str(value or "z").strip().lower()
    if axis not in AXIS_OPTIONS:
        raise ToolExecutionException(
            f"Invalid axis '{axis}'. Expected one of {list(AXIS_OPTIONS)}.",
            error_type=ERROR_VALIDATION,
        )
    return AXIS_OPTIONS.index(axis)


def _clamp_preview_size(value: Any, default: int) -> int:
    size = default if value is None else int(value)
    return min(MAX_PREVIEW_SIZE, max(MIN_PREVIEW_SIZE, size))


def _sanitize_name_fragment(value: str, fallback: str) -> str:
    raw = value.strip()
    if not raw:
        return fallback
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
    if not slug:
        return fallback
    return slug[:64]


def _matrix_transform_point(matrix: Any, point: Tuple[float, float, float]) -> Tuple[float, float, float]:
    if matrix is None:
        return point
    try:
        return _coerce_xyz(matrix @ point, point)
    except Exception:
        return point


def _object_bbox_points(obj: Any, *, world: bool) -> List[Tuple[float, float, float]]:
    raw_bbox = getattr(obj, "bound_box", None)
    if raw_bbox is None:
        return []
    matrix = getattr(obj, "matrix_world", None) if world else None
    points: List[Tuple[float, float, float]] = []
    for corner in raw_bbox:
        try:
            point = _coerce_xyz(corner)
        except Exception:
            continue
        points.append(_matrix_transform_point(matrix, point))
    return points


def _mesh_vertex_points(obj: Any, *, world: bool) -> List[Tuple[float, float, float]]:
    mesh = getattr(obj, "data", None)
    vertices = getattr(mesh, "vertices", None)
    if vertices is None:
        return []
    matrix = getattr(obj, "matrix_world", None) if world else None
    points: List[Tuple[float, float, float]] = []
    for vert in vertices:
        co = getattr(vert, "co", vert)
        try:
            point = _coerce_xyz(co)
        except Exception:
            continue
        points.append(_matrix_transform_point(matrix, point))
    return points


def _bounds_from_points(points: Sequence[Tuple[float, float, float]]) -> Optional[Dict[str, Tuple[float, float, float]]]:
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    min_pt = (min(xs), min(ys), min(zs))
    max_pt = (max(xs), max(ys), max(zs))
    center = (
        (min_pt[0] + max_pt[0]) * 0.5,
        (min_pt[1] + max_pt[1]) * 0.5,
        (min_pt[2] + max_pt[2]) * 0.5,
    )
    dimensions = (max_pt[0] - min_pt[0], max_pt[1] - min_pt[1], max_pt[2] - min_pt[2])
    return {"min": min_pt, "max": max_pt, "center": center, "dimensions": dimensions}


def _object_bounds(obj: Any, *, world: bool) -> Dict[str, Tuple[float, float, float]]:
    points = _object_bbox_points(obj, world=world)
    if not points and getattr(obj, "type", "") == "MESH":
        points = _mesh_vertex_points(obj, world=world)
    bounds = _bounds_from_points(points)
    if bounds is not None:
        return bounds

    translation = getattr(getattr(obj, "matrix_world", None), "translation", getattr(obj, "location", (0.0, 0.0, 0.0)))
    location = _coerce_xyz(translation, (0.0, 0.0, 0.0))
    dimensions = _coerce_xyz(getattr(obj, "dimensions", (1.0, 1.0, 1.0)), (1.0, 1.0, 1.0))
    half = tuple(max(abs(item) * 0.5, 0.001) for item in dimensions)
    fallback_points = [
        (location[0] - half[0], location[1] - half[1], location[2] - half[2]),
        (location[0] + half[0], location[1] + half[1], location[2] + half[2]),
    ]
    fallback = _bounds_from_points(fallback_points)
    if fallback is None:
        raise ToolExecutionException("Unable to compute object bounds.", error_type=ERROR_TOOL)
    return fallback


def _scene_objects(blender: Any) -> List[Any]:
    scene = getattr(getattr(blender, "context", None), "scene", None)
    scene_objects = getattr(scene, "objects", None)
    if scene_objects is None:
        scene_objects = getattr(getattr(blender, "data", None), "objects", [])
    return list(scene_objects)


def _combined_bounds(objects: Sequence[Any]) -> Dict[str, Tuple[float, float, float]]:
    points: List[Tuple[float, float, float]] = []
    for obj in objects:
        points.extend(_object_bbox_points(obj, world=True))
    bounds = _bounds_from_points(points)
    if bounds is not None:
        return bounds
    fallback = _bounds_from_points([(-0.5, -0.5, -0.5), (0.5, 0.5, 0.5)])
    if fallback is None:
        raise ToolExecutionException("Unable to compute scene bounds.", error_type=ERROR_TOOL)
    return fallback


def _downsample_points(points: Sequence[Tuple[float, float, float]], limit: int) -> List[Tuple[float, float, float]]:
    if len(points) <= limit:
        return list(points)
    stride = max(1, len(points) // limit)
    return [points[idx] for idx in range(0, len(points), stride)][:limit]


def _prepare_output_dir(
    exec_ctx: Optional[ToolExecutionContext],
    output_dir: Optional[str],
    *,
    default_subdir: str,
) -> Path:
    raw = (output_dir or "").strip()
    target_dir = _resolve_workspace_path(raw if raw else default_subdir, exec_ctx, allow_parent_create=True)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise ToolExecutionException(
            "Unable to prepare output directory.",
            error_type=ERROR_TOOL,
            data={"path": str(target_dir)},
        ) from exc
    if not target_dir.is_dir():
        raise ToolExecutionException(
            "Output path is not a directory.",
            error_type=ERROR_VALIDATION,
            data={"path": str(target_dir)},
        )
    return target_dir


def _build_snapshot_path(
    exec_ctx: Optional[ToolExecutionContext],
    *,
    object_name: str,
    view: str,
    output_dir: Optional[str],
    file_name: Optional[str],
) -> Path:
    target_dir = _prepare_output_dir(exec_ctx, output_dir, default_subdir="previews")
    default_stem = f"{_sanitize_name_fragment(object_name or 'scene', 'scene')}_{view}"
    raw_stem = default_stem
    if isinstance(file_name, str) and file_name.strip():
        raw_stem = Path(os.path.basename(file_name.strip())).stem or default_stem
    safe_stem = _sanitize_name_fragment(raw_stem, default_stem)
    filename = _safe_export_filename(safe_stem, "png")
    return _resolve_workspace_path(str(target_dir / filename), exec_ctx, allow_parent_create=True)


def _create_preview_camera(scene: Any, bounds: Dict[str, Tuple[float, float, float]], view: str) -> Tuple[Any, Any]:
    blender = _require_bpy()
    from mathutils import Vector  # type: ignore

    direction_map = {
        "front": Vector((0.0, -1.0, 0.0)),
        "side": Vector((1.0, 0.0, 0.0)),
        "top": Vector((0.0, 0.0, 1.0)),
        "perspective": Vector((1.0, -1.0, 0.75)),
    }
    center = Vector(bounds["center"])
    dims = bounds["dimensions"]
    max_dim = max(max(dims), 0.1)
    radius = max_dim * 0.5
    direction = direction_map[view].normalized()
    distance = max(radius * (3.2 if view == "perspective" else 2.2), 1.0)
    location = center + direction * distance

    cam_data = blender.data.cameras.new(name="DA_PreviewCamera")
    cam_obj = blender.data.objects.new(name="DA_PreviewCamera", object_data=cam_data)
    collection = getattr(scene, "collection", None)
    if collection is None or not hasattr(collection, "objects"):
        raise ToolExecutionException("Unable to link preview camera to scene.", error_type=ERROR_BLENDER)
    collection.objects.link(cam_obj)

    look_dir = center - location
    if look_dir.length < 1e-6:
        look_dir = Vector((0.0, 0.0, -1.0))
    cam_obj.location = location
    cam_obj.rotation_euler = look_dir.to_track_quat("-Z", "Y").to_euler()
    cam_data.clip_start = 0.01
    cam_data.clip_end = max(distance * 10.0, 100.0)
    if view in {"front", "side", "top"}:
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = max(max_dim * 1.4, 0.5)
    else:
        cam_data.type = "PERSP"
        cam_data.lens = 50.0
    return cam_obj, cam_data


def _render_snapshot_image(
    view: str,
    width: int,
    height: int,
    output_path: Path,
    *,
    target_object: Optional[Any],
) -> None:
    blender = _require_bpy()
    scene = getattr(getattr(blender, "context", None), "scene", None)
    if scene is None:
        raise ToolExecutionException("No active scene found.", error_type=ERROR_BLENDER)

    if target_object is not None:
        bounds = _object_bounds(target_object, world=True)
    else:
        bounds = _combined_bounds(_scene_objects(blender))

    cam_obj, cam_data = _create_preview_camera(scene, bounds, view)
    render = scene.render
    image_settings = render.image_settings
    original = {
        "camera": scene.camera,
        "engine": render.engine,
        "resolution_x": render.resolution_x,
        "resolution_y": render.resolution_y,
        "resolution_percentage": render.resolution_percentage,
        "filepath": render.filepath,
        "file_format": image_settings.file_format,
    }

    try:
        scene.camera = cam_obj
        render.resolution_x = int(width)
        render.resolution_y = int(height)
        render.resolution_percentage = 100
        render.filepath = str(output_path)
        image_settings.file_format = "PNG"
        try:
            render.engine = "BLENDER_WORKBENCH"
        except Exception:
            render.engine = original["engine"]

        try:
            blender.ops.render.render(write_still=True, use_viewport=False)
        except TypeError:
            blender.ops.render.render(write_still=True)
        except Exception as exc:
            raise ToolExecutionException(
                f"Snapshot render failed: {exc}",
                error_type=ERROR_TOOL,
                data={"path": str(output_path), "view": view},
            ) from exc
        if not output_path.exists():
            raise ToolExecutionException(
                "Snapshot render did not produce output.",
                error_type=ERROR_TOOL,
                data={"path": str(output_path), "view": view},
            )
    finally:
        scene.camera = original["camera"]
        render.engine = original["engine"]
        render.resolution_x = int(original["resolution_x"])
        render.resolution_y = int(original["resolution_y"])
        render.resolution_percentage = int(original["resolution_percentage"])
        render.filepath = str(original["filepath"])
        image_settings.file_format = str(original["file_format"])
        try:
            blender.data.objects.remove(cam_obj, do_unlink=True)
        except Exception:
            pass
        try:
            blender.data.cameras.remove(cam_data, do_unlink=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Scene tools
# ---------------------------------------------------------------------------


def create_primitive(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    prim_type = str(args.get("type", "cube")).lower()
    name = args.get("name")
    location = _vector(args.get("location"), 3, (0.0, 0.0, 0.0))
    rotation = _vector(args.get("rotation"), 3, (0.0, 0.0, 0.0))
    scale = _vector(args.get("scale"), 3, (1.0, 1.0, 1.0))

    blender.ops.object.select_all(action="DESELECT")
    if prim_type == "cube":
        blender.ops.mesh.primitive_cube_add(location=location, rotation=rotation, scale=scale)
    elif prim_type == "cylinder":
        blender.ops.mesh.primitive_cylinder_add(location=location, rotation=rotation, scale=scale)
    elif prim_type == "cone":
        blender.ops.mesh.primitive_cone_add(location=location, rotation=rotation, scale=scale)
    elif prim_type == "uv_sphere":
        blender.ops.mesh.primitive_uv_sphere_add(location=location, rotation=rotation, scale=scale)
    elif prim_type == "plane":
        blender.ops.mesh.primitive_plane_add(location=location, rotation=rotation, scale=scale)
    else:
        raise ToolExecutionException(
            f"Unsupported primitive type '{prim_type}'.",
            error_type=ERROR_VALIDATION,
        )

    obj = blender.context.active_object
    if obj is None:
        raise ToolExecutionException("Failed to create primitive.", error_type=ERROR_BLENDER)
    if isinstance(name, str) and name.strip():
        obj.name = name.strip()
    return _as_data(
        f"Created primitive '{obj.name}'.",
        object={"name": obj.name, "type": obj.type},
    )


def delete_objects(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    names = list(args.get("names", []))
    if not names:
        raise ToolExecutionException("No object names were provided.", error_type=ERROR_VALIDATION)
    ignore_missing = bool(args.get("ignore_missing", True))

    blender.ops.object.select_all(action="DESELECT")
    deleted: List[str] = []
    missing: List[str] = []
    for name in names:
        obj = blender.data.objects.get(str(name))
        if obj is None:
            missing.append(str(name))
            continue
        obj.select_set(True)
        deleted.append(obj.name)
    if deleted:
        blender.ops.object.delete()
    if missing and not ignore_missing:
        raise ToolExecutionException(
            "Some objects were missing.",
            error_type=ERROR_TOOL,
            data={"deleted": deleted, "missing": missing},
        )
    return _as_data("Object deletion complete.", deleted=deleted, missing=missing)


def select_objects(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    names = [str(name) for name in args.get("names", [])]
    if not names:
        raise ToolExecutionException("No object names were provided.", error_type=ERROR_VALIDATION)
    extend = bool(args.get("extend", False))
    set_active = bool(args.get("set_active", True))

    if not extend:
        blender.ops.object.select_all(action="DESELECT")

    selected: List[str] = []
    missing: List[str] = []
    for name in names:
        obj = blender.data.objects.get(name)
        if obj is None:
            missing.append(name)
            continue
        obj.select_set(True)
        selected.append(name)
        if set_active:
            blender.context.view_layer.objects.active = obj
    return _as_data("Selection updated.", selected=selected, missing=missing)


def transform_object(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    obj = _require_object(str(args.get("name", "")))
    if "location" in args:
        obj.location = _vector(args.get("location"), 3, tuple(obj.location))
    if "rotation" in args:
        obj.rotation_euler = _vector(args.get("rotation"), 3, tuple(obj.rotation_euler))
    if "scale" in args:
        obj.scale = _vector(args.get("scale"), 3, tuple(obj.scale))
    return _as_data(
        f"Transformed '{obj.name}'.",
        transform={
            "location": list(obj.location),
            "rotation": list(obj.rotation_euler),
            "scale": list(obj.scale),
        },
    )


def assign_material(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    target_name = str(args.get("target", ""))
    material_name = str(args.get("material", ""))
    if not target_name or not material_name:
        raise ToolExecutionException("Both target and material are required.", error_type=ERROR_VALIDATION)
    obj = _require_object(target_name)
    if obj.type != "MESH":
        raise ToolExecutionException(
            f"Object '{obj.name}' is not a mesh.",
            error_type=ERROR_TOOL,
            data={"object": obj.name, "type": obj.type},
        )

    mat = blender.data.materials.get(material_name)
    if mat is None:
        mat = blender.data.materials.new(name=material_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF") or nodes.new("ShaderNodeBsdfPrincipled")
    base_color = _color_rgba(args.get("base_color"))
    if base_color:
        bsdf.inputs["Base Color"].default_value = base_color
    roughness = args.get("roughness")
    if isinstance(roughness, (int, float)):
        bsdf.inputs["Roughness"].default_value = min(1.0, max(0.0, float(roughness)))
    metallic = args.get("metallic")
    if isinstance(metallic, (int, float)):
        bsdf.inputs["Metallic"].default_value = min(1.0, max(0.0, float(metallic)))

    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    return _as_data("Material assigned.", target=obj.name, material=mat.name)


def import_asset(args: Dict[str, Any], exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    src = _resolve_workspace_path(str(args.get("path", "")), exec_ctx, must_exist=True)
    ext = src.suffix.lower()
    before = {obj.name for obj in blender.data.objects}
    if ext in {".glb", ".gltf"}:
        blender.ops.import_scene.gltf(filepath=str(src))
    elif ext == ".fbx":
        blender.ops.import_scene.fbx(filepath=str(src))
    elif ext == ".obj":
        blender.ops.import_scene.obj(filepath=str(src))
    else:
        raise ToolExecutionException(
            f"Unsupported import extension '{ext}'.",
            error_type=ERROR_VALIDATION,
        )
    after = {obj.name for obj in blender.data.objects}
    imported = sorted(after - before)
    return _as_data("Import complete.", path=str(src), imported_objects=imported)


def export_asset(args: Dict[str, Any], exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    fmt = str(args.get("format", "GLB")).upper()
    target = str(args.get("target", "")).strip()
    use_selection = False
    if target:
        blender.ops.object.select_all(action="DESELECT")
        obj = _require_object(target)
        obj.select_set(True)
        blender.context.view_layer.objects.active = obj
        use_selection = True

    if "path" in args:
        filepath = _resolve_workspace_path(str(args.get("path")), exec_ctx, allow_parent_create=True)
    else:
        filename = _safe_export_filename(str(args.get("filename", "export")), fmt.lower())
        filepath = _resolve_workspace_path(filename, exec_ctx, allow_parent_create=True)

    if fmt == "GLB":
        blender.ops.export_scene.gltf(filepath=str(filepath), use_selection=use_selection, export_format="GLB")
    elif fmt == "FBX":
        blender.ops.export_scene.fbx(filepath=str(filepath), use_selection=use_selection)
    elif fmt == "OBJ":
        blender.ops.export_scene.obj(filepath=str(filepath), use_selection=use_selection)
    else:
        raise ToolExecutionException(
            f"Unsupported export format '{fmt}'.",
            error_type=ERROR_VALIDATION,
        )
    return _as_data("Export complete.", path=str(filepath), format=fmt, use_selection=use_selection)


def export_glb(args: Dict[str, Any], exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    args = dict(args)
    args["format"] = "GLB"
    return export_asset(args, exec_ctx)


# ---------------------------------------------------------------------------
# Rig / animation tools
# ---------------------------------------------------------------------------


def create_action(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    name = str(args.get("name", "")).strip()
    if not name:
        raise ToolExecutionException("Action name is required.", error_type=ERROR_VALIDATION)
    action = blender.data.actions.new(name=name)
    action.use_fake_user = bool(args.get("use_fake_user", True))
    return _as_data("Action created.", action=action.name, use_fake_user=bool(action.use_fake_user))


def set_active_action(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    target = _require_object(str(args.get("target", "")))
    action_name = str(args.get("action", "")).strip()
    action = blender.data.actions.get(action_name)
    if action is None:
        raise ToolExecutionException(
            f"Action '{action_name}' not found.",
            error_type=ERROR_TOOL,
            data={"action": action_name},
        )
    if target.animation_data is None:
        target.animation_data_create()
    target.animation_data.action = action
    return _as_data("Active action set.", target=target.name, action=action.name)


def pose_bone_transform(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    armature_obj = _require_object(str(args.get("armature", "")))
    if armature_obj.type != "ARMATURE":
        raise ToolExecutionException(
            f"Object '{armature_obj.name}' is not an armature.",
            error_type=ERROR_TOOL,
        )
    bone_name = str(args.get("bone", "")).strip()
    bone = armature_obj.pose.bones.get(bone_name)
    if bone is None:
        raise ToolExecutionException(
            f"Pose bone '{bone_name}' not found.",
            error_type=ERROR_TOOL,
            data={"armature": armature_obj.name, "bone": bone_name},
        )
    if "location" in args:
        bone.location = _vector(args.get("location"), 3, tuple(bone.location))
    if "rotation_euler" in args:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = _vector(args.get("rotation_euler"), 3, tuple(bone.rotation_euler))
    if "rotation_quaternion" in args:
        bone.rotation_mode = "QUATERNION"
        bone.rotation_quaternion = _vector(args.get("rotation_quaternion"), 4, tuple(bone.rotation_quaternion))
    if "scale" in args:
        bone.scale = _vector(args.get("scale"), 3, tuple(bone.scale))
    return _as_data(
        "Pose bone transformed.",
        armature=armature_obj.name,
        bone=bone.name,
        location=list(bone.location),
        scale=list(bone.scale),
    )


def insert_keyframe(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    target = _require_object(str(args.get("target", "")))
    data_path = str(args.get("data_path", "")).strip()
    frame = int(args.get("frame", 0))
    index = int(args.get("index", -1))
    if not data_path:
        raise ToolExecutionException("data_path is required.", error_type=ERROR_VALIDATION)
    if index >= 0:
        success = target.keyframe_insert(data_path=data_path, frame=frame, index=index)
    else:
        success = target.keyframe_insert(data_path=data_path, frame=frame)
    if not success:
        raise ToolExecutionException(
            "Keyframe insert returned False.",
            error_type=ERROR_TOOL,
            data={"target": target.name, "data_path": data_path, "frame": frame},
        )
    return _as_data("Keyframe inserted.", target=target.name, data_path=data_path, frame=frame, index=index)


def duplicate_action(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    source_name = str(args.get("source", "")).strip()
    new_name = str(args.get("new_name", "")).strip()
    source = blender.data.actions.get(source_name)
    if source is None:
        raise ToolExecutionException(f"Action '{source_name}' not found.", error_type=ERROR_TOOL)
    if not new_name:
        raise ToolExecutionException("new_name is required.", error_type=ERROR_VALIDATION)
    copied = source.copy()
    copied.name = new_name
    return _as_data("Action duplicated.", source=source.name, action=copied.name)


def _swap_lr_name(data_path: str) -> str:
    if ".L" not in data_path and ".R" not in data_path:
        return data_path
    placeholder = "__LR_SWAP__"
    return data_path.replace(".L", placeholder).replace(".R", ".L").replace(placeholder, ".R")


def _mirror_curve_value(data_path: str, array_index: int, axis: str, value: float) -> float:
    axis = axis.upper()
    if data_path.endswith("location"):
        axis_map = {"X": 0, "Y": 1, "Z": 2}
        if array_index == axis_map.get(axis, -1):
            return -value
    if data_path.endswith("rotation_euler"):
        if axis == "X" and array_index in (1, 2):
            return -value
        if axis == "Y" and array_index in (0, 2):
            return -value
        if axis == "Z" and array_index in (0, 1):
            return -value
    if data_path.endswith("rotation_quaternion"):
        if axis == "X" and array_index in (2, 3):
            return -value
        if axis == "Y" and array_index in (1, 3):
            return -value
        if axis == "Z" and array_index in (1, 2):
            return -value
    return value


def mirror_action(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    source_name = str(args.get("source", "")).strip()
    new_name = str(args.get("new_name", "")).strip()
    axis = str(args.get("axis", "X")).upper()
    swap_lr = bool(args.get("swap_lr", True))
    source = blender.data.actions.get(source_name)
    if source is None:
        raise ToolExecutionException(f"Action '{source_name}' not found.", error_type=ERROR_TOOL)
    if axis not in {"X", "Y", "Z"}:
        raise ToolExecutionException("axis must be one of X, Y, Z.", error_type=ERROR_VALIDATION)
    if not new_name:
        raise ToolExecutionException("new_name is required.", error_type=ERROR_VALIDATION)

    mirrored = source.copy()
    mirrored.name = new_name
    for fcurve in mirrored.fcurves:
        if swap_lr:
            fcurve.data_path = _swap_lr_name(fcurve.data_path)
        for point in fcurve.keyframe_points:
            point.co[1] = _mirror_curve_value(fcurve.data_path, fcurve.array_index, axis, point.co[1])
            point.handle_left[1] = _mirror_curve_value(fcurve.data_path, fcurve.array_index, axis, point.handle_left[1])
            point.handle_right[1] = _mirror_curve_value(fcurve.data_path, fcurve.array_index, axis, point.handle_right[1])
    return _as_data(
        "Action mirrored.",
        source=source.name,
        action=mirrored.name,
        axis=axis,
        swap_lr=swap_lr,
    )


def bake_action(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    armature = _require_object(str(args.get("armature", "")))
    if armature.type != "ARMATURE":
        raise ToolExecutionException(f"Object '{armature.name}' is not an armature.", error_type=ERROR_TOOL)
    frame_start = int(args.get("frame_start", blender.context.scene.frame_start))
    frame_end = int(args.get("frame_end", blender.context.scene.frame_end))
    step = int(args.get("step", 1))
    if frame_end < frame_start:
        raise ToolExecutionException("frame_end must be >= frame_start.", error_type=ERROR_VALIDATION)

    blender.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    blender.context.view_layer.objects.active = armature

    blender.ops.nla.bake(
        frame_start=frame_start,
        frame_end=frame_end,
        step=max(1, step),
        only_selected=bool(args.get("only_selected", False)),
        visual_keying=bool(args.get("visual_keying", True)),
        clear_constraints=bool(args.get("clear_constraints", False)),
        use_current_action=True,
        bake_types={"POSE"},
    )

    new_action_name = str(args.get("new_action", "")).strip()
    baked = armature.animation_data.action if armature.animation_data else None
    if baked is None:
        raise ToolExecutionException("Bake completed but no action was active.", error_type=ERROR_TOOL)
    if new_action_name:
        baked.name = new_action_name
    return _as_data(
        "Action baked.",
        armature=armature.name,
        action=baked.name,
        frame_start=frame_start,
        frame_end=frame_end,
    )


# ---------------------------------------------------------------------------
# Workspace file tools
# ---------------------------------------------------------------------------


def list_project_files(args: Dict[str, Any], exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    root = _workspace_root(exec_ctx)
    subdir = str(args.get("subdir", "")).strip()
    recursive = bool(args.get("recursive", False))
    limit = int(args.get("limit", 200))
    limit = min(max(1, limit), 1000)

    target = root if not subdir else _resolve_workspace_path(subdir, exec_ctx, must_exist=True)
    if not target.is_dir():
        raise ToolExecutionException("Target path is not a directory.", error_type=ERROR_VALIDATION)

    files: List[str] = []
    iterator: Iterable[Path] = target.rglob("*") if recursive else target.glob("*")
    for entry in iterator:
        if not entry.is_file():
            continue
        try:
            relative = str(entry.resolve().relative_to(root))
        except ValueError:
            continue
        files.append(relative)
        if len(files) >= limit:
            break
    return _as_data("Project files listed.", workspace_root=str(root), files=sorted(files), count=len(files))


def read_project_file(args: Dict[str, Any], exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    file_path = _resolve_workspace_path(str(args.get("path", "")), exec_ctx, must_exist=True)
    if file_path.is_dir():
        raise ToolExecutionException("Requested path is a directory.", error_type=ERROR_VALIDATION)
    max_bytes = int(args.get("max_bytes", MAX_FILE_BYTES))
    max_bytes = min(max(128, max_bytes), MAX_FILE_BYTES)
    data = file_path.read_bytes()
    if len(data) > max_bytes:
        raise ToolExecutionException(
            "File exceeds max_bytes limit.",
            error_type=ERROR_VALIDATION,
            data={"size": len(data), "max_bytes": max_bytes},
        )
    text = data.decode("utf-8")
    lines = text.splitlines()
    if len(lines) > MAX_FILE_LINES:
        text = "\n".join(lines[:MAX_FILE_LINES])
    return _as_data("File read.", path=str(file_path), content=text, size=len(data))


def write_project_file(args: Dict[str, Any], exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    file_path = _resolve_workspace_path(str(args.get("path", "")), exec_ctx, allow_parent_create=True)
    content = args.get("content", "")
    if not isinstance(content, str):
        raise ToolExecutionException("content must be a string.", error_type=ERROR_VALIDATION)
    overwrite = bool(args.get("overwrite", False))
    encoding = str(args.get("encoding", "utf-8"))
    payload = content.encode(encoding, errors="strict")
    if len(payload) > MAX_FILE_BYTES:
        raise ToolExecutionException(
            "Content exceeds max writable size.",
            error_type=ERROR_VALIDATION,
            data={"size": len(payload), "max_bytes": MAX_FILE_BYTES},
        )
    if file_path.exists() and not overwrite:
        raise ToolExecutionException(
            "File exists and overwrite is false.",
            error_type=ERROR_VALIDATION,
            data={"path": str(file_path)},
        )
    file_path.write_bytes(payload)
    return _as_data("File written.", path=str(file_path), bytes_written=len(payload), overwrite=overwrite)


# ---------------------------------------------------------------------------
# Diagnostics tools
# ---------------------------------------------------------------------------


def get_selection(_args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    selected = [obj.name for obj in blender.context.selected_objects]
    active = blender.context.active_object.name if blender.context.active_object else ""
    return _as_data("Selection inspected.", selected=selected, active=active)


def list_actions(_args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    actions = sorted(action.name for action in blender.data.actions)
    return _as_data("Actions listed.", actions=actions, count=len(actions))


def list_armatures(_args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    armatures = sorted(obj.name for obj in blender.data.objects if obj.type == "ARMATURE")
    return _as_data("Armatures listed.", armatures=armatures, count=len(armatures))


def get_current_frame(_args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    return _as_data("Current frame inspected.", frame=int(blender.context.scene.frame_current))


def set_current_frame(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    frame = int(args.get("frame", blender.context.scene.frame_current))
    blender.context.scene.frame_set(frame)
    return _as_data("Current frame updated.", frame=frame)


def get_diagnostics(_args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    scene = blender.context.scene
    active = blender.context.active_object.name if blender.context.active_object else ""
    selected = [obj.name for obj in blender.context.selected_objects]
    actions = [a.name for a in blender.data.actions]
    armatures = [o.name for o in blender.data.objects if o.type == "ARMATURE"]
    meshes = [o.name for o in blender.data.objects if o.type == "MESH"]
    return _as_data(
        "Diagnostics gathered.",
        diagnostics={
            "active_object": active,
            "selected_objects": selected,
            "current_frame": int(scene.frame_current),
            "frame_range": [int(scene.frame_start), int(scene.frame_end)],
            "actions": actions,
            "armatures": armatures,
            "meshes": meshes,
        },
    )


def render_viewport_snapshot(args: Dict[str, Any], exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    object_name = str(args.get("object_name", "")).strip()
    view = _normalize_snapshot_view(args.get("view", "perspective"))
    width = _clamp_preview_size(args.get("width"), DEFAULT_PREVIEW_WIDTH)
    height = _clamp_preview_size(args.get("height"), DEFAULT_PREVIEW_HEIGHT)
    file_name = str(args.get("file_name", "")).strip() or None
    output_path = _build_snapshot_path(
        exec_ctx,
        object_name=object_name or "scene",
        view=view,
        output_dir=None,
        file_name=file_name,
    )

    target_object = _require_object(object_name) if object_name else None
    _render_snapshot_image(view, width, height, output_path, target_object=target_object)

    payload: Dict[str, Any] = {
        "image_path": str(output_path),
        "view": view,
        "width": width,
        "height": height,
    }
    if target_object is not None:
        payload["object_name"] = target_object.name
    return _as_data("Viewport snapshot rendered.", **payload)


def render_turntable_preview(args: Dict[str, Any], exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    object_name = str(args.get("object_name", "")).strip()
    if not object_name:
        raise ToolExecutionException("object_name is required.", error_type=ERROR_VALIDATION)
    views_raw = args.get("views", list(DEFAULT_TURNTABLE_VIEWS))
    if views_raw is None:
        views_raw = list(DEFAULT_TURNTABLE_VIEWS)
    if not isinstance(views_raw, list) or not views_raw:
        raise ToolExecutionException("views must be a non-empty array.", error_type=ERROR_VALIDATION)
    views = [_normalize_snapshot_view(item) for item in views_raw]
    width = _clamp_preview_size(args.get("width"), DEFAULT_PREVIEW_WIDTH)
    height = _clamp_preview_size(args.get("height"), DEFAULT_PREVIEW_HEIGHT)

    default_dir = f"previews/turntable_{_sanitize_name_fragment(object_name, 'object')}"
    requested_dir = str(args.get("output_dir", "")).strip() or default_dir
    target_dir = _prepare_output_dir(exec_ctx, requested_dir, default_subdir=default_dir)

    target_object = _require_object(object_name)
    safe_name = _sanitize_name_fragment(target_object.name, "object")
    images: List[Dict[str, str]] = []
    for view in views:
        output_path = _build_snapshot_path(
            exec_ctx,
            object_name=target_object.name,
            view=view,
            output_dir=str(target_dir),
            file_name=f"{safe_name}_{view}.png",
        )
        _render_snapshot_image(view, width, height, output_path, target_object=target_object)
        images.append({"view": view, "image_path": str(output_path)})

    return _as_data(
        "Turntable preview rendered.",
        object_name=target_object.name,
        images=images,
        count=len(images),
    )


def get_object_dimensions(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    object_name = str(args.get("object_name", "")).strip()
    if not object_name:
        raise ToolExecutionException("object_name is required.", error_type=ERROR_VALIDATION)
    space = str(args.get("space", "world")).strip().lower()
    if space not in {"local", "world"}:
        raise ToolExecutionException("space must be 'local' or 'world'.", error_type=ERROR_VALIDATION)

    obj = _require_object(object_name)
    bounds = _object_bounds(obj, world=(space == "world"))
    location_value = getattr(obj, "location", (0.0, 0.0, 0.0))
    if space == "world":
        location_value = getattr(getattr(obj, "matrix_world", None), "translation", location_value)

    return _as_data(
        "Object dimensions gathered.",
        object_name=obj.name,
        space=space,
        dimensions=_vector_dict(bounds["dimensions"]),
        location=_vector_list(location_value),
        rotation=_vector_list(getattr(obj, "rotation_euler", (0.0, 0.0, 0.0))),
        scale=_vector_list(getattr(obj, "scale", (1.0, 1.0, 1.0))),
        bounding_box_min=_vector_dict(bounds["min"]),
        bounding_box_max=_vector_dict(bounds["max"]),
    )


def get_object_profile_samples(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    object_name = str(args.get("object_name", "")).strip()
    if not object_name:
        raise ToolExecutionException("object_name is required.", error_type=ERROR_VALIDATION)
    sample_count = int(args.get("sample_count", DEFAULT_PROFILE_SAMPLE_COUNT))
    sample_count = min(MAX_PROFILE_SAMPLE_COUNT, max(1, sample_count))
    axis_idx = _axis_index(args.get("axis", "z"))
    axis_name = AXIS_OPTIONS[axis_idx]

    obj = _require_object(object_name)
    if obj.type != "MESH":
        raise ToolExecutionException(
            f"Object '{obj.name}' is not a mesh.",
            error_type=ERROR_TOOL,
            data={"object": obj.name, "type": obj.type},
        )
    points = _mesh_vertex_points(obj, world=True)
    if not points:
        raise ToolExecutionException(
            f"Object '{obj.name}' has no mesh vertices.",
            error_type=ERROR_TOOL,
            data={"object": obj.name},
        )

    axis_values = [point[axis_idx] for point in points]
    axis_min = min(axis_values)
    axis_max = max(axis_values)
    axis_span = max(axis_max - axis_min, 1e-6)
    window = max(axis_span / max(sample_count * 3, 3), 1e-5)

    other_axes = [idx for idx in range(3) if idx != axis_idx]
    width_idx, depth_idx = other_axes[0], other_axes[1]
    samples: List[Dict[str, float]] = []
    nearest_limit = max(8, min(32, len(points)))
    for idx in range(sample_count):
        t = 0.0 if sample_count == 1 else idx / float(sample_count - 1)
        axis_value = axis_min + axis_span * t
        band = [point for point in points if abs(point[axis_idx] - axis_value) <= window]
        if len(band) < 4:
            band = sorted(points, key=lambda point: abs(point[axis_idx] - axis_value))[:nearest_limit]
        width = max(point[width_idx] for point in band) - min(point[width_idx] for point in band)
        depth = max(point[depth_idx] for point in band) - min(point[depth_idx] for point in band)
        samples.append({"t": _round_float(t), "width": _round_float(width), "depth": _round_float(depth)})

    return _as_data(
        "Object profile sampled.",
        object_name=obj.name,
        axis=axis_name,
        sample_count=sample_count,
        samples=samples,
    )


def get_scene_summary(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    blender = _require_bpy()
    selected_only = bool(args.get("selected_only", False))
    selected_objects = list(getattr(blender.context, "selected_objects", []) or [])
    objects = selected_objects if selected_only else _scene_objects(blender)
    active = getattr(blender.context, "active_object", None)
    scene = blender.context.scene

    camera_names = sorted(obj.name for obj in objects if getattr(obj, "type", "") == "CAMERA")
    light_names = sorted(obj.name for obj in objects if getattr(obj, "type", "") == "LIGHT")
    mesh_names = sorted(obj.name for obj in objects if getattr(obj, "type", "") == "MESH")
    armature_names = sorted(obj.name for obj in objects if getattr(obj, "type", "") == "ARMATURE")

    scene_bounds: Dict[str, Any] = {}
    if objects:
        bounds = _combined_bounds(objects)
        scene_bounds = {
            "min": _vector_dict(bounds["min"]),
            "max": _vector_dict(bounds["max"]),
            "dimensions": _vector_dict(bounds["dimensions"]),
        }

    return _as_data(
        "Scene summary gathered.",
        selected_only=selected_only,
        object_count=len(objects),
        selected_objects=sorted(obj.name for obj in selected_objects),
        camera_names=camera_names,
        light_names=light_names,
        mesh_object_names=mesh_names,
        armature_names=armature_names,
        active_object=active.name if active else "",
        frame_current=int(scene.frame_current),
        scene_bounds=scene_bounds,
    )


def measure_object_symmetry(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    object_name = str(args.get("object_name", "")).strip()
    if not object_name:
        raise ToolExecutionException("object_name is required.", error_type=ERROR_VALIDATION)
    axis_idx = _axis_index(args.get("axis", "x"))
    axis_name = AXIS_OPTIONS[axis_idx]

    obj = _require_object(object_name)
    if obj.type != "MESH":
        bounds = _object_bounds(obj, world=False)
        axis_center = abs((bounds["min"][axis_idx] + bounds["max"][axis_idx]) * 0.5)
        span = max(max(bounds["dimensions"]), 1e-6)
        approximate = axis_center <= span * 0.02
        return _as_data(
            "Object symmetry measured with bounding-box heuristic.",
            object_name=obj.name,
            axis=axis_name,
            center_offset=_round_float(axis_center),
            approximate_symmetric=approximate,
            method_used="bounding_box_center",
            note="Non-mesh object; mirror sampling was skipped.",
        )

    points = _mesh_vertex_points(obj, world=False)
    if not points:
        raise ToolExecutionException(
            f"Object '{obj.name}' has no mesh vertices.",
            error_type=ERROR_TOOL,
            data={"object": obj.name},
        )
    bounds = _bounds_from_points(points)
    if bounds is None:
        raise ToolExecutionException("Unable to compute mesh bounds.", error_type=ERROR_TOOL)
    span = max(max(bounds["dimensions"]), 1e-6)
    center_offset = abs((bounds["min"][axis_idx] + bounds["max"][axis_idx]) * 0.5)

    search_points = _downsample_points(points, 600)
    query_points = _downsample_points(points, 240)
    total_error = 0.0
    max_error = 0.0
    for point in query_points:
        mirrored = list(point)
        mirrored[axis_idx] *= -1.0
        nearest_sq = min(
            (candidate[0] - mirrored[0]) ** 2
            + (candidate[1] - mirrored[1]) ** 2
            + (candidate[2] - mirrored[2]) ** 2
            for candidate in search_points
        )
        distance = nearest_sq ** 0.5
        total_error += distance
        if distance > max_error:
            max_error = distance
    mean_error = total_error / float(max(1, len(query_points)))

    approximate = center_offset <= span * 0.02 and mean_error <= span * 0.03 and max_error <= span * 0.08
    return _as_data(
        "Object symmetry measured.",
        object_name=obj.name,
        axis=axis_name,
        center_offset=_round_float(center_offset),
        mirror_mean_error=_round_float(mean_error),
        mirror_max_error=_round_float(max_error),
        approximate_symmetric=approximate,
        method_used="local_mesh_mirror_nearest_vertex",
        note="Nearest-vertex mirror heuristic on downsampled local mesh vertices.",
    )


def get_mesh_stats(args: Dict[str, Any], _exec_ctx: Optional[ToolExecutionContext] = None) -> ToolResult:
    object_name = str(args.get("object_name", "")).strip()
    if not object_name:
        raise ToolExecutionException("object_name is required.", error_type=ERROR_VALIDATION)
    obj = _require_object(object_name)
    if obj.type != "MESH":
        raise ToolExecutionException(
            f"Object '{obj.name}' is not a mesh.",
            error_type=ERROR_TOOL,
            data={"object": obj.name, "type": obj.type},
        )
    mesh = getattr(obj, "data", None)
    vertices = getattr(mesh, "vertices", [])
    edges = getattr(mesh, "edges", [])
    polygons = getattr(mesh, "polygons", [])
    has_ngons = any(int(getattr(poly, "loop_total", 0)) > 4 for poly in polygons)

    payload: Dict[str, Any] = {
        "object_name": obj.name,
        "vertex_count": int(len(vertices)),
        "edge_count": int(len(edges)),
        "face_count": int(len(polygons)),
        "material_count": int(len(getattr(obj, "material_slots", []))),
        "modifier_count": int(len(getattr(obj, "modifiers", []))),
        "has_ngons": bool(has_ngons),
    }

    manifold_status: Optional[bool] = None
    try:
        import bmesh  # type: ignore

        bm = bmesh.new()
        bm.from_mesh(mesh)
        manifold_status = all(edge.is_manifold for edge in bm.edges)
        bm.free()
    except Exception:
        manifold_status = None
    if manifold_status is not None:
        payload["manifold_status"] = bool(manifold_status)

    return _as_data("Mesh stats gathered.", **payload)


def _schema_object(properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


VECTOR3_SCHEMA = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
VECTOR4_SCHEMA = {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}


def _tool_specs() -> List[Tuple[ToolMetadata, Any]]:
    return [
        (
            ToolMetadata(
                name="create_primitive",
                description="Create a primitive mesh object.",
                args_schema=_schema_object(
                    {
                        "type": {"type": "string", "enum": ["cube", "cylinder", "cone", "uv_sphere", "plane"]},
                        "name": {"type": "string", "minLength": 1, "maxLength": 128},
                        "location": VECTOR3_SCHEMA,
                        "rotation": VECTOR3_SCHEMA,
                        "scale": VECTOR3_SCHEMA,
                    },
                    required=["type"],
                ),
                permissions=["scene:write"],
            ),
            create_primitive,
        ),
        (
            ToolMetadata(
                name="delete_objects",
                description="Delete one or more objects by name.",
                args_schema=_schema_object(
                    {
                        "names": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
                        "ignore_missing": {"type": "boolean"},
                    },
                    required=["names"],
                ),
                permissions=["scene:write"],
            ),
            delete_objects,
        ),
        (
            ToolMetadata(
                name="select_objects",
                description="Select one or more objects by name.",
                args_schema=_schema_object(
                    {
                        "names": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
                        "extend": {"type": "boolean"},
                        "set_active": {"type": "boolean"},
                    },
                    required=["names"],
                ),
                permissions=["scene:read"],
            ),
            select_objects,
        ),
        (
            ToolMetadata(
                name="transform_object",
                description="Set object location, rotation, and/or scale.",
                args_schema=_schema_object(
                    {
                        "name": {"type": "string", "minLength": 1},
                        "location": VECTOR3_SCHEMA,
                        "rotation": VECTOR3_SCHEMA,
                        "scale": VECTOR3_SCHEMA,
                    },
                    required=["name"],
                ),
                permissions=["scene:write"],
            ),
            transform_object,
        ),
        (
            ToolMetadata(
                name="assign_material",
                description="Assign or create a material on a mesh object.",
                args_schema=_schema_object(
                    {
                        "target": {"type": "string", "minLength": 1},
                        "material": {"type": "string", "minLength": 1},
                        "base_color": VECTOR4_SCHEMA,
                        "roughness": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "metallic": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    },
                    required=["target", "material"],
                ),
                permissions=["scene:write"],
            ),
            assign_material,
        ),
        (
            ToolMetadata(
                name="import_asset",
                description="Import GLB/GLTF/FBX/OBJ from workspace.",
                args_schema=_schema_object(
                    {"path": {"type": "string", "minLength": 1}},
                    required=["path"],
                ),
                permissions=["file:read", "scene:write"],
            ),
            import_asset,
        ),
        (
            ToolMetadata(
                name="export_asset",
                description="Export scene or selected object to GLB/FBX/OBJ in workspace.",
                args_schema=_schema_object(
                    {
                        "format": {"type": "string", "enum": ["GLB", "FBX", "OBJ"]},
                        "filename": {"type": "string", "minLength": 1},
                        "path": {"type": "string", "minLength": 1},
                        "target": {"type": "string", "minLength": 1},
                    },
                ),
                permissions=["scene:read", "file:write"],
            ),
            export_asset,
        ),
        (
            ToolMetadata(
                name="export_glb",
                description="Export GLB to workspace.",
                args_schema=_schema_object(
                    {
                        "filename": {"type": "string", "minLength": 1},
                        "path": {"type": "string", "minLength": 1},
                        "target": {"type": "string", "minLength": 1},
                    },
                ),
                permissions=["scene:read", "file:write"],
            ),
            export_glb,
        ),
        (
            ToolMetadata(
                name="create_action",
                description="Create a new action data-block.",
                args_schema=_schema_object(
                    {
                        "name": {"type": "string", "minLength": 1},
                        "use_fake_user": {"type": "boolean"},
                    },
                    required=["name"],
                ),
                permissions=["anim:write"],
            ),
            create_action,
        ),
        (
            ToolMetadata(
                name="set_active_action",
                description="Set an object's active action.",
                args_schema=_schema_object(
                    {
                        "target": {"type": "string", "minLength": 1},
                        "action": {"type": "string", "minLength": 1},
                    },
                    required=["target", "action"],
                ),
                permissions=["anim:write"],
            ),
            set_active_action,
        ),
        (
            ToolMetadata(
                name="pose_bone_transform",
                description="Apply pose transform to a bone on an armature.",
                args_schema=_schema_object(
                    {
                        "armature": {"type": "string", "minLength": 1},
                        "bone": {"type": "string", "minLength": 1},
                        "location": VECTOR3_SCHEMA,
                        "rotation_euler": VECTOR3_SCHEMA,
                        "rotation_quaternion": VECTOR4_SCHEMA,
                        "scale": VECTOR3_SCHEMA,
                    },
                    required=["armature", "bone"],
                ),
                permissions=["anim:write"],
            ),
            pose_bone_transform,
        ),
        (
            ToolMetadata(
                name="insert_keyframe",
                description="Insert a keyframe on an object data path.",
                args_schema=_schema_object(
                    {
                        "target": {"type": "string", "minLength": 1},
                        "data_path": {"type": "string", "minLength": 1},
                        "frame": {"type": "integer"},
                        "index": {"type": "integer", "minimum": -1},
                    },
                    required=["target", "data_path", "frame"],
                ),
                permissions=["anim:write"],
            ),
            insert_keyframe,
        ),
        (
            ToolMetadata(
                name="duplicate_action",
                description="Duplicate an existing action.",
                args_schema=_schema_object(
                    {
                        "source": {"type": "string", "minLength": 1},
                        "new_name": {"type": "string", "minLength": 1},
                    },
                    required=["source", "new_name"],
                ),
                permissions=["anim:write"],
            ),
            duplicate_action,
        ),
        (
            ToolMetadata(
                name="mirror_action",
                description="Mirror an action (supports L/R swap and axis mirroring).",
                args_schema=_schema_object(
                    {
                        "source": {"type": "string", "minLength": 1},
                        "new_name": {"type": "string", "minLength": 1},
                        "axis": {"type": "string", "enum": ["X", "Y", "Z"]},
                        "swap_lr": {"type": "boolean"},
                    },
                    required=["source", "new_name"],
                ),
                permissions=["anim:write"],
            ),
            mirror_action,
        ),
        (
            ToolMetadata(
                name="bake_action",
                description="Bake pose animation on an armature.",
                args_schema=_schema_object(
                    {
                        "armature": {"type": "string", "minLength": 1},
                        "frame_start": {"type": "integer"},
                        "frame_end": {"type": "integer"},
                        "step": {"type": "integer", "minimum": 1, "maximum": 10},
                        "only_selected": {"type": "boolean"},
                        "visual_keying": {"type": "boolean"},
                        "clear_constraints": {"type": "boolean"},
                        "new_action": {"type": "string", "minLength": 1},
                    },
                    required=["armature", "frame_start", "frame_end"],
                ),
                permissions=["anim:write"],
            ),
            bake_action,
        ),
        (
            ToolMetadata(
                name="list_project_files",
                description="List files inside workspace root.",
                args_schema=_schema_object(
                    {
                        "subdir": {"type": "string"},
                        "recursive": {"type": "boolean"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                    },
                ),
                permissions=["file:read"],
            ),
            list_project_files,
        ),
        (
            ToolMetadata(
                name="read_project_file",
                description="Read a small UTF-8 text file from workspace root.",
                args_schema=_schema_object(
                    {
                        "path": {"type": "string", "minLength": 1},
                        "max_bytes": {"type": "integer", "minimum": 128, "maximum": MAX_FILE_BYTES},
                    },
                    required=["path"],
                ),
                permissions=["file:read"],
            ),
            read_project_file,
        ),
        (
            ToolMetadata(
                name="write_project_file",
                description="Write a small UTF-8 text file inside workspace root.",
                args_schema=_schema_object(
                    {
                        "path": {"type": "string", "minLength": 1},
                        "content": {"type": "string", "maxLength": MAX_FILE_BYTES},
                        "overwrite": {"type": "boolean"},
                        "encoding": {"type": "string", "enum": ["utf-8"]},
                    },
                    required=["path", "content"],
                ),
                permissions=["file:write"],
            ),
            write_project_file,
        ),
        (
            ToolMetadata(
                name="get_selection",
                description="Get active and selected objects.",
                args_schema=_schema_object({}),
                permissions=["diagnostics:read"],
            ),
            get_selection,
        ),
        (
            ToolMetadata(
                name="list_actions",
                description="List action data-blocks.",
                args_schema=_schema_object({}),
                permissions=["diagnostics:read"],
            ),
            list_actions,
        ),
        (
            ToolMetadata(
                name="list_armatures",
                description="List armature objects in the scene.",
                args_schema=_schema_object({}),
                permissions=["diagnostics:read"],
            ),
            list_armatures,
        ),
        (
            ToolMetadata(
                name="get_current_frame",
                description="Get current scene frame.",
                args_schema=_schema_object({}),
                permissions=["diagnostics:read"],
            ),
            get_current_frame,
        ),
        (
            ToolMetadata(
                name="set_current_frame",
                description="Set current scene frame.",
                args_schema=_schema_object(
                    {"frame": {"type": "integer"}},
                    required=["frame"],
                ),
                permissions=["anim:write"],
            ),
            set_current_frame,
        ),
        (
            ToolMetadata(
                name="get_diagnostics",
                description="Get high-level scene diagnostics.",
                args_schema=_schema_object({}),
                permissions=["diagnostics:read"],
            ),
            get_diagnostics,
        ),
        (
            ToolMetadata(
                name="render_viewport_snapshot",
                description="Render a quick preview image from a standard viewport angle.",
                args_schema=_schema_object(
                    {
                        "object_name": {"type": "string", "minLength": 1},
                        "view": {"type": "string", "enum": list(SNAPSHOT_VIEW_OPTIONS)},
                        "width": {"type": "integer", "minimum": MIN_PREVIEW_SIZE, "maximum": MAX_PREVIEW_SIZE},
                        "height": {"type": "integer", "minimum": MIN_PREVIEW_SIZE, "maximum": MAX_PREVIEW_SIZE},
                        "file_name": {"type": "string", "minLength": 1, "maxLength": 256},
                    },
                    required=["view"],
                ),
                permissions=["render:read", "file:write"],
            ),
            render_viewport_snapshot,
        ),
        (
            ToolMetadata(
                name="render_turntable_preview",
                description="Render multiple preview images of one object from standard angles.",
                args_schema=_schema_object(
                    {
                        "object_name": {"type": "string", "minLength": 1},
                        "views": {
                            "type": "array",
                            "items": {"type": "string", "enum": list(SNAPSHOT_VIEW_OPTIONS)},
                            "minItems": 1,
                            "maxItems": 8,
                        },
                        "width": {"type": "integer", "minimum": MIN_PREVIEW_SIZE, "maximum": MAX_PREVIEW_SIZE},
                        "height": {"type": "integer", "minimum": MIN_PREVIEW_SIZE, "maximum": MAX_PREVIEW_SIZE},
                        "output_dir": {"type": "string", "minLength": 1},
                    },
                    required=["object_name"],
                ),
                permissions=["render:read", "file:write"],
            ),
            render_turntable_preview,
        ),
        (
            ToolMetadata(
                name="get_object_dimensions",
                description="Get dimensions, transform, and bounds for an object.",
                args_schema=_schema_object(
                    {
                        "object_name": {"type": "string", "minLength": 1},
                        "space": {"type": "string", "enum": ["local", "world"]},
                    },
                    required=["object_name"],
                ),
                permissions=["scene:read"],
            ),
            get_object_dimensions,
        ),
        (
            ToolMetadata(
                name="get_object_profile_samples",
                description="Sample approximate width/depth profile along an axis.",
                args_schema=_schema_object(
                    {
                        "object_name": {"type": "string", "minLength": 1},
                        "axis": {"type": "string", "enum": list(AXIS_OPTIONS)},
                        "sample_count": {"type": "integer", "minimum": 1, "maximum": MAX_PROFILE_SAMPLE_COUNT},
                    },
                    required=["object_name"],
                ),
                permissions=["scene:read"],
            ),
            get_object_profile_samples,
        ),
        (
            ToolMetadata(
                name="get_scene_summary",
                description="Get object lists, selection, frame, and rough scene bounds.",
                args_schema=_schema_object(
                    {
                        "selected_only": {"type": "boolean"},
                    }
                ),
                permissions=["diagnostics:read"],
            ),
            get_scene_summary,
        ),
        (
            ToolMetadata(
                name="measure_object_symmetry",
                description="Estimate whether an object is centered and symmetric around an axis.",
                args_schema=_schema_object(
                    {
                        "object_name": {"type": "string", "minLength": 1},
                        "axis": {"type": "string", "enum": list(AXIS_OPTIONS)},
                    },
                    required=["object_name"],
                ),
                permissions=["scene:read"],
            ),
            measure_object_symmetry,
        ),
        (
            ToolMetadata(
                name="get_mesh_stats",
                description="Get mesh density and topology summary for one object.",
                args_schema=_schema_object(
                    {
                        "object_name": {"type": "string", "minLength": 1},
                    },
                    required=["object_name"],
                ),
                permissions=["scene:read"],
            ),
            get_mesh_stats,
        ),
    ]


def register_default_tools(registry: AgentToolRegistry = agent_registry) -> None:
    registry_id = id(registry)
    if registry_id in _REGISTERED_REGISTRIES and bool(getattr(registry, "_tools", {})):
        return
    for metadata, handler in _tool_specs():
        registry.register(metadata, handler, allow_replace=True)
    _REGISTERED_REGISTRIES.add(registry_id)
