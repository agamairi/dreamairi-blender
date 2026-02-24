"""Lightweight non-Blender harness for registry schema behavior."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dreamairi_blender.core.errors import ERROR_VALIDATION
from dreamairi_blender.tools.registry import AgentToolRegistry, ToolMetadata, ToolResult


class ToolValidationHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = AgentToolRegistry()
        self.registry.register(
            ToolMetadata(
                name="transform",
                description="Transform object",
                args_schema={
                    "type": "object",
                    "required": ["name", "location"],
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "location": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "enabled": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
                permissions=[],
            ),
            lambda args: ToolResult(True, "ok", {"args": args}),
        )

    def test_valid_payload(self) -> None:
        result = self.registry.execute("transform", {"name": "Cube", "location": [0, 1, 2], "enabled": True})
        self.assertTrue(result.success)

    def test_rejects_bad_vector_length(self) -> None:
        result = self.registry.execute("transform", {"name": "Cube", "location": [0, 1]})
        self.assertFalse(result.success)
        self.assertEqual(result.error_type, ERROR_VALIDATION)
        self.assertIn("at least 3 items", result.message)

    def test_rejects_bad_type(self) -> None:
        result = self.registry.execute("transform", {"name": "Cube", "location": [0, 1, "x"]})
        self.assertFalse(result.success)
        self.assertEqual(result.error_type, ERROR_VALIDATION)
        self.assertIn("expected number", result.message)


if __name__ == "__main__":
    unittest.main()

