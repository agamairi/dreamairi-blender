import unittest

from dreamairi_blender.llm.contract import ModelPlan, Operation, StyleBlock
from dreamairi_blender.tools.validator import ValidationError, ValidationSettings, validate_plan


class ValidatorTests(unittest.TestCase):
    def test_op_limit(self) -> None:
        plan = ModelPlan(
            version="1.0",
            summary="Test",
            style=StyleBlock(poly_budget=100, notes=""),
            ops=[Operation(op="ADD_CUBE", payload={"name": "A"})],
        )
        settings = ValidationSettings(max_ops=0, max_primitives=10, strict_mode=False, poly_budget=100)
        with self.assertRaises(ValidationError):
            validate_plan(plan, settings)

    def test_unknown_op(self) -> None:
        plan = ModelPlan(
            version="1.0",
            summary="Test",
            style=StyleBlock(poly_budget=100, notes=""),
            ops=[Operation(op="UNKNOWN", payload={})],
        )
        settings = ValidationSettings(max_ops=10, max_primitives=10, strict_mode=False, poly_budget=100)
        with self.assertRaises(ValidationError):
            validate_plan(plan, settings)

    def test_modifier_cap(self) -> None:
        plan = ModelPlan(
            version="1.0",
            summary="Test",
            style=StyleBlock(poly_budget=100, notes=""),
            ops=[
                Operation(
                    op="MODIFIER",
                    payload={
                        "target": "A",
                        "modifier": "SUBSURF",
                        "params": {"levels": 5},
                    },
                )
            ],
        )
        settings = ValidationSettings(max_ops=10, max_primitives=10, strict_mode=False, poly_budget=100)
        with self.assertRaises(ValidationError):
            validate_plan(plan, settings)


if __name__ == "__main__":
    unittest.main()
