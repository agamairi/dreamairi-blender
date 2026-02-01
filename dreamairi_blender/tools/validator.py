"""Validation for LLM operations against whitelist and limits."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ..llm.contract import ModelPlan
from .whitelist import get_schema, is_primitive, modifier_limit


class ValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ValidationSettings:
    max_ops: int
    max_primitives: int
    strict_mode: bool
    poly_budget: int


def validate_plan(plan: ModelPlan, settings: ValidationSettings) -> None:
    if len(plan.ops) > settings.max_ops:
        raise ValidationError(f"Too many ops: {len(plan.ops)} > {settings.max_ops}")

    primitive_count = 0
    for operation in plan.ops:
        schema = get_schema(operation.op)
        if schema is None:
            raise ValidationError(f"Unsupported op: {operation.op}")
        error = schema.validate(operation.payload)
        if error:
            raise ValidationError(f"{operation.op}: {error}")

        if is_primitive(operation.op):
            primitive_count += 1
        if operation.op == "MODIFIER":
            modifier = str(operation.payload.get("modifier", "")).upper()
            cap, key = modifier_limit(modifier)
            if cap and key:
                params = operation.payload.get("params", {}) or {}
                value = params.get(key)
                if isinstance(value, (int, float)):
                    if modifier == "DECIMATE" and not (0.0 < float(value) <= 1.0):
                        raise ValidationError("DECIMATE ratio must be 0-1")
                    if modifier != "DECIMATE" and float(value) > cap:
                        raise ValidationError(f"{modifier} {key} exceeds cap {cap}")

    if primitive_count > settings.max_primitives:
        raise ValidationError(
            f"Too many primitives: {primitive_count} > {settings.max_primitives}"
        )

    if settings.strict_mode and plan.style.poly_budget > settings.poly_budget:
        raise ValidationError("Plan poly budget exceeds target budget")
