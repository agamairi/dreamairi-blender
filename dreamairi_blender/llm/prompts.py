"""System and user prompt builders for the strict agent loop."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict

from ..tools.registry import ensure_builtin_tools_registered, agent_registry

INTERNAL_SYSTEM_PROMPT = """You are DreamAiri, a Blender agent controller.
You are NOT allowed to execute arbitrary Python or invent tools.
You may only act by producing one of these JSON envelopes:
1) PLAN
2) TOOL_CALL
3) FINAL

Hard rules:
- Reply with JSON only (no markdown, no prose outside JSON).
- Use only tool names from the tool registry provided below.
- TOOL_CALL args must match tool schemas exactly.
- After TOOL_CALLs, wait for tool_results and iterate.
- If task is complete, return FINAL.
- If a task is unsafe or impossible, return FINAL explaining why.
"""

DEFAULT_CUSTOM_TEMPLATE = """Optional customization ideas:
- Keep plans short, concrete, and deterministic.
- Prefer diagnostics tools before mutating scene state.
- Minimize unnecessary tool calls.
"""

AGENT_ENVELOPE_SCHEMA = """Response envelope options:

PLAN:
{
  "type": "PLAN",
  "steps": ["short step 1", "short step 2", "short step 3"]
}

TOOL_CALL:
{
  "type": "TOOL_CALL",
  "calls": [
    {"tool": "tool_name", "args": {"field": "value"}}
  ]
}

FINAL:
{
  "type": "FINAL",
  "message": "what was done or why it stopped"
}
"""


@dataclass
class PromptBundle:
    system_prompt: str
    user_prompt: str


def _build_tools_snippet() -> str:
    ensure_builtin_tools_registered()
    lines = ["Tool Registry (strict whitelist):"]
    for tool in sorted(agent_registry.list_tools(), key=lambda item: item.name):
        schema_json = json.dumps(tool.args_schema, separators=(",", ":"))
        perms = ",".join(tool.permissions)
        lines.append(f"- {tool.name} | permissions=[{perms}]")
        lines.append(f"  description: {tool.description}")
        lines.append(f"  args_schema: {schema_json}")
    return "\n".join(lines)


def build_prompt(
    scene_context: Dict[str, object],
    user_request: str,
    custom_system_prompt: str,
    append_custom: bool = True,
    fast_mode: bool = False,
) -> PromptBundle:
    fast_mode_clause = (
        "Fast mode is ON. You may start directly with TOOL_CALL if it is clearly safe."
        if fast_mode
        else "Fast mode is OFF. Your first response MUST be PLAN before any TOOL_CALL."
    )

    system_parts = [INTERNAL_SYSTEM_PROMPT.strip(), fast_mode_clause, AGENT_ENVELOPE_SCHEMA.strip()]
    if custom_system_prompt.strip():
        if append_custom:
            system_parts.append(custom_system_prompt.strip())
        else:
            system_parts.insert(0, custom_system_prompt.strip())

    system_parts.append("Respond with a single JSON object only.")
    system_parts.append(_build_tools_snippet())
    system_prompt = "\n\n".join(system_parts)

    user_payload = {
        "scene_context": scene_context,
        "user_request": user_request.strip(),
        "execution_policy": {
            "require_initial_plan": not fast_mode,
            "no_arbitrary_python": True,
            "tool_registry_only": True,
        },
    }
    user_prompt = json.dumps(user_payload, ensure_ascii=True)
    return PromptBundle(system_prompt=system_prompt, user_prompt=user_prompt)

