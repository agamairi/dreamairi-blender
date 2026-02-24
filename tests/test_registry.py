import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dreamairi_blender.core.errors import ERROR_VALIDATION
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


if __name__ == "__main__":
    unittest.main()

