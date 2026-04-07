"""Blender smoke test for agent tool workflow.

Workflow:
1) import model (through tool)
2) create rig action
3) keyframe pose
4) export GLB
"""

import os
import sys
from pathlib import Path

import bpy

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from dreamairi_blender.tools.registry import agent_registry, ensure_builtin_tools_registered


def _assert_success(name: str, result) -> None:
    if result.success:
        return
    print(f"FAILED: {name}: {result.message} ({result.error_type})")
    if result.data:
        print(f"DETAILS: {result.data}")
    sys.exit(1)


def run_smoke_test() -> None:
    ensure_builtin_tools_registered()
    print("Running DreamAiri smoke workflow...")

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    create_res = agent_registry.execute(
        "create_primitive",
        {"type": "cube", "name": "SmokeSource", "location": [0, 0, 0], "scale": [0.4, 0.4, 0.4]},
    )
    _assert_success("create_primitive", create_res)

    dimensions_res = agent_registry.execute("get_object_dimensions", {"object_name": "SmokeSource", "space": "world"})
    _assert_success("get_object_dimensions", dimensions_res)

    mesh_stats_res = agent_registry.execute("get_mesh_stats", {"object_name": "SmokeSource"})
    _assert_success("get_mesh_stats", mesh_stats_res)

    scene_summary_res = agent_registry.execute("get_scene_summary", {})
    _assert_success("get_scene_summary", scene_summary_res)

    export_source = agent_registry.execute("export_glb", {"filename": "smoke_source.glb", "target": "SmokeSource"})
    _assert_success("export_glb(source)", export_source)
    source_path = export_source.data["path"]

    delete_res = agent_registry.execute("delete_objects", {"names": ["SmokeSource"]})
    _assert_success("delete_objects", delete_res)

    import_res = agent_registry.execute("import_asset", {"path": source_path})
    _assert_success("import_asset", import_res)
    imported_objects = import_res.data.get("imported_objects", [])
    if not imported_objects:
        print("FAILED: import_asset returned no imported objects")
        sys.exit(1)

    bpy.ops.object.armature_add(location=(0, 0, 0))
    armature = bpy.context.active_object
    armature.name = "SmokeRig"
    bone_name = armature.pose.bones[0].name

    action_res = agent_registry.execute("create_action", {"name": "SmokeRigAction"})
    _assert_success("create_action", action_res)

    active_res = agent_registry.execute("set_active_action", {"target": "SmokeRig", "action": "SmokeRigAction"})
    _assert_success("set_active_action", active_res)

    frame1 = agent_registry.execute("set_current_frame", {"frame": 1})
    _assert_success("set_current_frame(1)", frame1)
    pose1 = agent_registry.execute(
        "pose_bone_transform",
        {"armature": "SmokeRig", "bone": bone_name, "rotation_euler": [0.0, 0.0, 0.4]},
    )
    _assert_success("pose_bone_transform(1)", pose1)
    key1 = agent_registry.execute(
        "insert_keyframe",
        {"target": "SmokeRig", "data_path": f'pose.bones["{bone_name}"].rotation_euler', "frame": 1},
    )
    _assert_success("insert_keyframe(1)", key1)

    frame20 = agent_registry.execute("set_current_frame", {"frame": 20})
    _assert_success("set_current_frame(20)", frame20)
    pose2 = agent_registry.execute(
        "pose_bone_transform",
        {"armature": "SmokeRig", "bone": bone_name, "rotation_euler": [0.0, 0.0, -0.4]},
    )
    _assert_success("pose_bone_transform(20)", pose2)
    key2 = agent_registry.execute(
        "insert_keyframe",
        {"target": "SmokeRig", "data_path": f'pose.bones["{bone_name}"].rotation_euler', "frame": 20},
    )
    _assert_success("insert_keyframe(20)", key2)

    export_final = agent_registry.execute("export_glb", {"filename": "smoke_final.glb"})
    _assert_success("export_glb(final)", export_final)
    if not os.path.isfile(export_final.data["path"]):
        print(f"FAILED: exported file not found: {export_final.data['path']}")
        sys.exit(1)

    print("Smoke workflow PASSED.")
    print(f"Imported objects: {imported_objects}")
    print(f"Exported final GLB: {export_final.data['path']}")
    sys.exit(0)


if __name__ == "__main__":
    run_smoke_test()
