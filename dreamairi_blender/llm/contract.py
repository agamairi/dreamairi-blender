"""LLM response contract and validation."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


class ContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class StyleBlock:
    poly_budget: int
    notes: str


@dataclass(frozen=True)
class Operation:
    op: str
    payload: Dict[str, Any]


@dataclass(frozen=True)
class ModelPlan:
    version: str
    summary: str
    style: StyleBlock
    ops: List[Operation]


def extract_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    if start == -1:
        raise ContractError("No JSON object found in response")

    depth = 0
    for idx in range(start, len(text)):
        char = text[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                snippet = text[start : idx + 1]
                try:
                    return json.loads(snippet)
                except json.JSONDecodeError as exc:
                    raise ContractError("Failed to parse JSON object") from exc
    raise ContractError("Incomplete JSON object in response")


def validate_plan(payload: Dict[str, Any]) -> ModelPlan:
    required_keys = {"version", "summary", "style", "ops"}
    unknown_keys = set(payload.keys()) - required_keys
    if unknown_keys:
        raise ContractError(f"Unknown top-level keys: {sorted(unknown_keys)}")
    version = payload.get("version")
    summary = payload.get("summary")
    style = payload.get("style")
    ops = payload.get("ops")

    if version != "1":
        raise ContractError("Unsupported version")
    if not isinstance(summary, str) or not summary.strip():
        raise ContractError("Summary must be a non-empty string")
    if not isinstance(ops, list):
        raise ContractError("Ops must be a list")

    # Style is optional for robustness
    if style is None:
        style = {"poly_budget": 800, "notes": "default"}
    elif not isinstance(style, dict):
        raise ContractError("Style must be an object if provided")

    style_keys = {"poly_budget", "notes"}
    unknown_style = set(style.keys()) - style_keys
    if unknown_style:
        raise ContractError(f"Unknown style keys: {sorted(unknown_style)}")
    poly_budget = style.get("poly_budget", 800)
    if not isinstance(poly_budget, int) or poly_budget <= 0:
        poly_budget = 800  # Fallback
    notes = style.get("notes", "")
    if not isinstance(notes, str):
        notes = str(notes)

    operations: List[Operation] = []
    for entry in ops:
        if not isinstance(entry, dict):
            raise ContractError("Each op must be an object")
        op_name = entry.get("op")
        if not isinstance(op_name, str):
            raise ContractError("Each op must include an 'op' string")
        payload_data = entry.get("payload")
        if not isinstance(payload_data, dict):
            # Fallback for LLMs that miss the payload key
            payload_data = {k: v for k, v in entry.items() if k != "op"}
        operations.append(Operation(op=op_name, payload=payload_data))

    return ModelPlan(
        version=version,
        summary=summary,
        style=StyleBlock(poly_budget=poly_budget, notes=notes),
        ops=operations,
    )


def parse_and_validate(text: str) -> ModelPlan:
    payload = extract_json_object(text)
    if not isinstance(payload, dict):
        raise ContractError("Response JSON must be an object")
    return validate_plan(payload)
