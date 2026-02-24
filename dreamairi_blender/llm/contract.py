"""LLM response contracts for the agent loop."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List


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


@dataclass(frozen=True)
class AgentToolCall:
    tool: str
    args: Dict[str, Any]


@dataclass(frozen=True)
class AgentEnvelope:
    response_type: str
    plan_steps: List[str] = field(default_factory=list)
    tool_calls: List[AgentToolCall] = field(default_factory=list)
    final_message: str = ""


def extract_json_object(text: str) -> Dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    start = stripped.find("{")
    if start == -1:
        raise ContractError("No JSON object found in response")

    depth = 0
    for idx in range(start, len(stripped)):
        char = stripped[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                snippet = stripped[start : idx + 1]
                try:
                    return json.loads(snippet)
                except json.JSONDecodeError as exc:
                    raise ContractError("Failed to parse JSON object") from exc
    raise ContractError("Incomplete JSON object in response")


def _parse_plan_steps(raw_steps: Any) -> List[str]:
    if isinstance(raw_steps, str):
        steps = [line.strip("- ").strip() for line in raw_steps.splitlines() if line.strip()]
    elif isinstance(raw_steps, list):
        steps = [str(item).strip() for item in raw_steps if str(item).strip()]
    else:
        raise ContractError("PLAN requires 'steps' as a list of strings")
    if not steps:
        raise ContractError("PLAN must include at least one step")
    return steps


def _parse_tool_calls(raw_calls: Any) -> List[AgentToolCall]:
    if not isinstance(raw_calls, list) or not raw_calls:
        raise ContractError("TOOL_CALL requires non-empty 'calls' array")
    calls: List[AgentToolCall] = []
    for idx, entry in enumerate(raw_calls):
        if not isinstance(entry, dict):
            raise ContractError(f"Tool call at index {idx} must be an object")
        name = entry.get("tool") or entry.get("name") or entry.get("op")
        if not isinstance(name, str) or not name.strip():
            raise ContractError(f"Tool call at index {idx} missing tool name")
        args = entry.get("args")
        if args is None:
            args = entry.get("payload")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise ContractError(f"Tool call '{name}' args must be an object")
        calls.append(AgentToolCall(tool=name.strip(), args=args))
    return calls


def parse_agent_response(text: str) -> AgentEnvelope:
    payload = extract_json_object(text)
    response_type_raw = payload.get("type") or payload.get("response_type")
    if not isinstance(response_type_raw, str):
        # Legacy fallback: treat old ops format as TOOL_CALL
        if isinstance(payload.get("ops"), list):
            calls = _parse_tool_calls(payload.get("ops"))
            return AgentEnvelope(response_type="TOOL_CALL", tool_calls=calls)
        raise ContractError("Missing required string field 'type'")

    response_type = response_type_raw.strip().upper()
    if response_type == "PLAN":
        return AgentEnvelope(response_type="PLAN", plan_steps=_parse_plan_steps(payload.get("steps")))

    if response_type in {"TOOL_CALL", "TOOL_CALLS"}:
        calls = _parse_tool_calls(payload.get("calls") or payload.get("tool_calls"))
        return AgentEnvelope(response_type="TOOL_CALL", tool_calls=calls)

    if response_type == "FINAL":
        message = payload.get("message", payload.get("final", ""))
        if not isinstance(message, str) or not message.strip():
            raise ContractError("FINAL requires a non-empty 'message' string")
        return AgentEnvelope(response_type="FINAL", final_message=message.strip())

    raise ContractError(f"Unsupported response type '{response_type_raw}'")


def validate_plan(payload: Dict[str, Any]) -> ModelPlan:
    allowed = {"version", "summary", "style", "ops"}
    unknown = set(payload.keys()) - allowed
    if unknown:
        raise ContractError(f"Unknown keys: {sorted(unknown)}")
    if "ops" not in payload:
        raise ContractError("Missing required key: ops")

    version = str(payload.get("version", "2"))
    summary = payload.get("summary", "Executing operations.")
    style = payload.get("style") or {"poly_budget": 800, "notes": ""}
    ops = payload.get("ops")

    if not isinstance(summary, str) or not summary.strip():
        raise ContractError("summary must be a non-empty string")
    if not isinstance(style, dict):
        raise ContractError("style must be an object")
    if not isinstance(ops, list):
        raise ContractError("ops must be a list")

    poly_budget = style.get("poly_budget", 800)
    notes = style.get("notes", "")
    if not isinstance(poly_budget, int):
        raise ContractError("style.poly_budget must be an integer")
    if not isinstance(notes, str):
        raise ContractError("style.notes must be a string")

    operations: List[Operation] = []
    for entry in ops:
        if not isinstance(entry, dict):
            raise ContractError("each op must be an object")
        op_name = entry.get("op")
        payload_data = entry.get("payload")
        if not isinstance(op_name, str) or not op_name.strip():
            raise ContractError("each op requires non-empty 'op'")
        if payload_data is None:
            payload_data = {k: v for k, v in entry.items() if k != "op"}
        if not isinstance(payload_data, dict):
            raise ContractError("op payload must be an object")
        operations.append(Operation(op=op_name.strip(), payload=payload_data))

    return ModelPlan(
        version=version,
        summary=summary.strip(),
        style=StyleBlock(poly_budget=poly_budget, notes=notes),
        ops=operations,
    )


def parse_and_validate(text: str) -> ModelPlan:
    payload = extract_json_object(text)
    if not isinstance(payload, dict):
        raise ContractError("Response JSON must be an object")
    # Legacy fallback: allow new envelope by converting tool calls into ops.
    if "type" in payload and "ops" not in payload:
        envelope = parse_agent_response(text)
        if envelope.response_type == "TOOL_CALL":
            payload = {
                "version": "2",
                "summary": "Tool call response",
                "style": {"poly_budget": 800, "notes": "agent-envelope"},
                "ops": [{"op": call.tool, "payload": call.args} for call in envelope.tool_calls],
            }
        elif envelope.response_type == "FINAL":
            payload = {
                "version": "2",
                "summary": envelope.final_message,
                "style": {"poly_budget": 800, "notes": "agent-envelope"},
                "ops": [],
            }
        elif envelope.response_type == "PLAN":
            payload = {
                "version": "2",
                "summary": "Plan provided",
                "style": {"poly_budget": 800, "notes": "agent-envelope"},
                "ops": [],
            }
    return validate_plan(payload)

