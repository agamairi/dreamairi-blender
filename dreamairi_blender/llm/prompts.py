"""Prompt templates and assembly logic."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


INTERNAL_SYSTEM_PROMPT = """You are DreamAiri, a Blender modeling assistant.
You must respond with JSON only, matching the exact schema provided.
Never output Python code. Never perform file or network operations.
Use only the whitelisted operations. Keep actions minimal and deterministic.
Do not reference file paths or system details.
Ensure outputs meet the triangle budget and low-poly style constraints.
If a request is unsafe or impossible, respond with an empty ops list and explain in summary.
"""

DEFAULT_CUSTOM_TEMPLATE = """Optional customization ideas:
- Focus on clean topology and naming.
- Prefer primitives and modifiers over destructive edits.
- Use the provided style preset palette for solid materials.
"""

ALLOWED_OPS_SNIPPET = """Allowed ops:
- ADD_PRIMITIVE: { "type": "cube"|"cylinder"|"cone"|"uv_sphere", "name": str, "location": [x,y,z], ... }
- RENAME_OBJECT: { "target": str, "new_name": str }
- SET_TRANSFORM: { "target": str, "location": [x,y,z], ... }
- MODIFIER: { "target": str, "modifier": "BEVEL"|"SUBSURF"|"DECIMATE", "params": {...} }
- APPLY_MODIFIER: { "target": str, "modifier": str }
- SET_SHADING: { "target": str, "mode": "SMOOTH"|"FLAT", "auto_smooth_angle": float }
- MATERIAL_CREATE: { "name": str, "base_color": [r,g,b,a] }
- MATERIAL_ASSIGN: { "target": str, "material": str }
- JOIN_OBJECTS: { "targets": [str,...], "name": str }
- CLEANUP: { "target": str, "apply_transforms": bool, "recalc_normals": bool, "merge_dist": float }
- VALIDATE_MESH: { "target": str, "budget": int }
"""

SCHEMA_SNIPPET = """Return JSON with this structure only:
{
  "version": "1",
  "summary": "what will be created",
  "ops": [
    {
      "op": "ADD_PRIMITIVE",
      "payload": {
        "type": "cylinder",
        "name": "Pin_Base",
        "location": [0, 0, 0],
        "params": { "radius": 0.3, "depth": 1.0 }
      }
    }
  ]
}
"""

JSON_ONLY_INSTRUCTION = """Respond with a single JSON object and no extra text.
"""


@dataclass
class PromptBundle:
    system_prompt: str
    user_prompt: str


def build_prompt(
    scene_context: Dict[str, object],
    user_request: str,
    custom_system_prompt: str,
    append_custom: bool = True,
) -> PromptBundle:
    system_parts = [INTERNAL_SYSTEM_PROMPT.strip()]
    if custom_system_prompt.strip():
        if append_custom:
            system_parts.append(custom_system_prompt.strip())
        else:
            system_parts.insert(0, custom_system_prompt.strip())
    system_parts.append(JSON_ONLY_INSTRUCTION.strip())
    system_parts.append(ALLOWED_OPS_SNIPPET.strip())
    system_parts.append(SCHEMA_SNIPPET.strip())

    system_prompt = "\n\n".join(system_parts)
    user_prompt = (
        "Scene context:\n"
        f"{scene_context}\n\n"
        "User request:\n"
        f"{user_request.strip()}"
    )
    return PromptBundle(system_prompt=system_prompt, user_prompt=user_prompt)
