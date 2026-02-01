"""Generation pipeline for DreamAiri-blender."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Dict, List

from ..llm import parser
from ..llm.contract import ModelPlan
from ..llm.prompts import build_prompt
from ..preferences import GenerationSettingsSnapshot, PreferencesSnapshot
from ..providers.base import ProviderRequest
from ..providers.factory import build_provider
from ..security.sanitizer import redact
from ..security.secrets import IN_MEMORY_SECRETS, SecretsStore
from ..tools.context import build_scene_context
from ..tools.executor import ToolExecutor
from ..util.style_presets import get_style_preset
from ..tools.validator import ValidationSettings, validate_plan
from ..util.cancel import CancellationToken
from ..util.logging import LogBuffer


@dataclass
class GenerationResult:
    request_id: str
    plan: ModelPlan
    raw_text: str


def resolve_secrets(prefs: PreferencesSnapshot, session_key: str) -> SecretsStore:
    if prefs.remember_key:
        IN_MEMORY_SECRETS.set_api_key(prefs.api_key)
        return IN_MEMORY_SECRETS
    IN_MEMORY_SECRETS.set_api_key(session_key)
    return IN_MEMORY_SECRETS


def run_generation(
    prefs: PreferencesSnapshot,
    settings: GenerationSettingsSnapshot,
    scene_context: Dict[str, object],
    session_key: str,
    cancel_token: CancellationToken,
) -> GenerationResult:
    request_id = str(uuid.uuid4())

    if os.getenv("DREAMAIRI_MOCK_RESPONSE"):
        raw_text = os.environ["DREAMAIRI_MOCK_RESPONSE"]
    else:
        secrets = resolve_secrets(prefs, session_key)
        provider = build_provider(prefs.provider, prefs.base_url, prefs.model_name, secrets)
        bundle = build_prompt(
            scene_context=scene_context,
            user_request=settings.prompt_text,
            custom_system_prompt=prefs.custom_system_prompt,
            append_custom=prefs.append_custom_prompt,
        )
        request = ProviderRequest(
            model=prefs.model_name,
            system_prompt=bundle.system_prompt,
            user_prompt=bundle.user_prompt,
        )
        raw_text = provider.send_chat(request, cancel_token)

    plan = parser.parse_and_validate(raw_text)
    validation = ValidationSettings(
        max_ops=settings.max_ops,
        max_primitives=settings.max_primitives,
        strict_mode=settings.strict_mode,
        poly_budget=settings.triangle_budget,
    )
    validate_plan(plan, validation)
    return GenerationResult(request_id=request_id, plan=plan, raw_text=raw_text)


def execute_plan(
    plan: ModelPlan,
    target_poly_budget: int | None = None,
    style_preset: str | None = None,
) -> None:
    actions: List[Dict[str, object]] = [
        {"op": op.op, "payload": op.payload} for op in plan.ops
    ]
    executor = ToolExecutor()
    executor.execute(actions)
    if style_preset:
        preset = get_style_preset(style_preset)
        executor.apply_shading("FLAT" if preset.flat_shading else "SMOOTH")
    if target_poly_budget is not None:
        executor.apply_decimate(target_poly_budget)


def format_plan(plan: ModelPlan) -> str:
    payload = {
        "version": plan.version,
        "summary": plan.summary,
        "style": {"poly_budget": plan.style.poly_budget, "notes": plan.style.notes},
        "ops": [
            {"op": op.op, **op.payload} for op in plan.ops
        ],
    }
    return json.dumps(payload, indent=2)


def append_log(buffer: LogBuffer, message: str, secrets: List[str]) -> None:
    buffer.append(redact(message, secrets))
