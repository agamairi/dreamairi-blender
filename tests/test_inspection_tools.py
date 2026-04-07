import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dreamairi_blender.core.errors import ERROR_TOOL, ERROR_VALIDATION
from dreamairi_blender.tools import implementations
from dreamairi_blender.tools.registry import AgentToolRegistry, ToolExecutionContext


def _bbox(min_pt, max_pt):
    x0, y0, z0 = min_pt
    x1, y1, z1 = max_pt
    return [
        (x0, y0, z0),
        (x0, y0, z1),
        (x0, y1, z0),
        (x0, y1, z1),
        (x1, y0, z0),
        (x1, y0, z1),
        (x1, y1, z0),
        (x1, y1, z1),
    ]


class _FakeMatrix:
    def __init__(self, translation=(0.0, 0.0, 0.0)):
        self.translation = translation

    def __matmul__(self, point):
        x, y, z = point
        tx, ty, tz = self.translation
        return (x + tx, y + ty, z + tz)


class _FakeVertex:
    def __init__(self, co):
        self.co = co


class _FakePolygon:
    def __init__(self, loop_total):
        self.loop_total = loop_total


class _FakeMesh:
    def __init__(self, vertices, edge_count, polygon_loops):
        self.vertices = [_FakeVertex(co) for co in vertices]
        self.edges = [object() for _ in range(edge_count)]
        self.polygons = [_FakePolygon(loop_total) for loop_total in polygon_loops]


class _FakeObject:
    def __init__(self, name, obj_type, *, bound_box=None, mesh=None):
        self.name = name
        self.type = obj_type
        self.bound_box = bound_box
        self.data = mesh
        self.matrix_world = _FakeMatrix((0.0, 0.0, 0.0))
        self.location = (0.0, 0.0, 0.0)
        self.rotation_euler = (0.0, 0.0, 0.0)
        self.scale = (1.0, 1.0, 1.0)
        self.dimensions = (1.0, 1.0, 1.0)
        self.material_slots = []
        self.modifiers = []


class _FakeObjectStore:
    def __init__(self, objects):
        self._objects = list(objects)
        self._by_name = {obj.name: obj for obj in objects}

    def get(self, name):
        return self._by_name.get(name)

    def __iter__(self):
        return iter(self._objects)


class _FakeData:
    def __init__(self, objects):
        self.objects = _FakeObjectStore(objects)
        self.actions = []


class _FakeScene:
    def __init__(self, objects, frame_current=1):
        self.objects = list(objects)
        self.frame_current = frame_current


class _FakeContext:
    def __init__(self, scene, selected_objects, active_object):
        self.scene = scene
        self.selected_objects = list(selected_objects)
        self.active_object = active_object


class _FakeBpy:
    def __init__(self, objects, *, selected_objects=None, active_object=None, frame_current=1):
        scene = _FakeScene(objects, frame_current=frame_current)
        self.context = _FakeContext(scene, selected_objects or [], active_object)
        self.data = _FakeData(objects)


class InspectionToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = AgentToolRegistry()
        implementations.register_default_tools(self.registry)

    def test_render_path_outside_workspace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.registry.execute(
                "render_turntable_preview",
                {"object_name": "Cube", "output_dir": "../escape"},
                context=ToolExecutionContext(workspace_root=tmpdir),
            )
        self.assertFalse(result.success)
        self.assertEqual(result.error_type, ERROR_VALIDATION)
        self.assertIn("outside workspace root", result.message.lower())

    def test_missing_object_returns_tool_error(self) -> None:
        with patch.object(implementations, "bpy", _FakeBpy([])):
            result = self.registry.execute("get_object_dimensions", {"object_name": "Missing"})
        self.assertFalse(result.success)
        self.assertEqual(result.error_type, ERROR_TOOL)
        self.assertEqual(result.data.get("object"), "Missing")

    def test_dimensions_scene_summary_and_mesh_stats_success(self) -> None:
        mesh_bbox = _bbox((-1.0, -2.0, -3.0), (1.0, 2.0, 3.0))
        mesh_data = _FakeMesh(vertices=mesh_bbox, edge_count=12, polygon_loops=[4, 4, 4, 4, 4, 4])
        mesh_obj = _FakeObject("InspectMesh", "MESH", bound_box=mesh_bbox, mesh=mesh_data)
        mesh_obj.material_slots = [object()]
        mesh_obj.modifiers = [object()]

        camera_obj = _FakeObject("SceneCam", "CAMERA")
        light_obj = _FakeObject("SceneLight", "LIGHT")
        armature_obj = _FakeObject("SceneRig", "ARMATURE")

        fake_bpy = _FakeBpy(
            [mesh_obj, camera_obj, light_obj, armature_obj],
            selected_objects=[mesh_obj],
            active_object=mesh_obj,
            frame_current=24,
        )

        with patch.object(implementations, "bpy", fake_bpy):
            dimensions = self.registry.execute(
                "get_object_dimensions",
                {"object_name": "InspectMesh", "space": "world"},
            )
            self.assertTrue(dimensions.success)
            self.assertEqual(dimensions.data["dimensions"], {"x": 2.0, "y": 4.0, "z": 6.0})

            summary = self.registry.execute("get_scene_summary", {})
            self.assertTrue(summary.success)
            self.assertEqual(summary.data["object_count"], 4)
            self.assertEqual(summary.data["selected_objects"], ["InspectMesh"])
            self.assertEqual(summary.data["camera_names"], ["SceneCam"])
            self.assertEqual(summary.data["light_names"], ["SceneLight"])
            self.assertEqual(summary.data["armature_names"], ["SceneRig"])
            self.assertEqual(summary.data["frame_current"], 24)

            stats = self.registry.execute("get_mesh_stats", {"object_name": "InspectMesh"})
            self.assertTrue(stats.success)
            self.assertEqual(stats.data["vertex_count"], 8)
            self.assertEqual(stats.data["edge_count"], 12)
            self.assertEqual(stats.data["face_count"], 6)
            self.assertEqual(stats.data["material_count"], 1)
            self.assertEqual(stats.data["modifier_count"], 1)
            self.assertFalse(stats.data["has_ngons"])


if __name__ == "__main__":
    unittest.main()
