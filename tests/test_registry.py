import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dreamairi_blender.core.errors import ERROR_VALIDATION
from dreamairi_blender.tools import implementations
from dreamairi_blender.tools.registry import (
    AgentToolRegistry,
    ToolExecutionContext,
    ToolMetadata,
    ToolResult,
)


class RegistryTests(unittest.TestCase):
    def test_register_and_execute(self) -> None:
        registry = AgentToolRegistry()

        def handler(args):
            return ToolResult(True, "ok", {"echo": args["value"]})

        metadata = ToolMetadata(
            name="echo",
            description="Echo value",
            args_schema={
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
            permissions=["scene:read"],
        )
        registry.register(metadata, handler)
        result = registry.execute("echo", {"value": "hello"})
        self.assertTrue(result.success)
        self.assertEqual(result.data["echo"], "hello")

    def test_schema_validation_blocks_unknown_fields(self) -> None:
        registry = AgentToolRegistry()
        registry.register(
            ToolMetadata(
                name="strict",
                description="Strict args",
                args_schema={
                    "type": "object",
                    "required": ["name"],
                    "properties": {"name": {"type": "string"}},
                    "additionalProperties": False,
                },
                permissions=[],
            ),
            lambda _args: ToolResult(True, "ok"),
        )
        result = registry.execute("strict", {"name": "x", "extra": 1})
        self.assertFalse(result.success)
        self.assertEqual(result.error_type, ERROR_VALIDATION)
        self.assertIn("unknown field", result.message.lower())

    def test_permission_check(self) -> None:
        registry = AgentToolRegistry()
        registry.register(
            ToolMetadata(
                name="write_scene",
                description="Writes scene",
                args_schema={"type": "object", "properties": {}, "additionalProperties": False},
                permissions=["scene:write"],
            ),
            lambda _args, _ctx=None: ToolResult(True, "ok"),
        )
        denied = registry.execute(
            "write_scene",
            {},
            context=ToolExecutionContext(granted_permissions={"scene:read"}),
        )
        self.assertFalse(denied.success)
        self.assertEqual(denied.error_type, ERROR_VALIDATION)
        self.assertIn("permission denied", denied.message.lower())

    def test_default_specs_include_inspection_tools(self) -> None:
        registry = AgentToolRegistry()
        implementations.register_default_tools(registry)
        names = {tool.name for tool in registry.list_tools()}
        expected = {
            "render_viewport_snapshot",
            "render_turntable_preview",
            "get_object_dimensions",
            "get_object_profile_samples",
            "get_scene_summary",
            "measure_object_symmetry",
            "get_mesh_stats",
        }
        self.assertTrue(expected.issubset(names))

        render_meta = registry.get_tool("render_viewport_snapshot")
        self.assertIsNotNone(render_meta)
        assert render_meta is not None
        self.assertIn("render:read", render_meta.permissions)
        self.assertIn("file:write", render_meta.permissions)

    def test_schema_rejects_invalid_inspection_args(self) -> None:
        registry = AgentToolRegistry()
        implementations.register_default_tools(registry)

        invalid_view = registry.execute("render_viewport_snapshot", {"view": "rear"})
        self.assertFalse(invalid_view.success)
        self.assertEqual(invalid_view.error_type, ERROR_VALIDATION)

        invalid_axis = registry.execute("measure_object_symmetry", {"object_name": "Cube", "axis": "w"})
        self.assertFalse(invalid_axis.success)
        self.assertEqual(invalid_axis.error_type, ERROR_VALIDATION)


if __name__ == "__main__":
    unittest.main()
