"""Generation pipeline entrypoint for DreamAiri agent runs."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .agent import AgentController, AgentResult, AgentState
from ..llm.prompts import build_prompt
from ..preferences import GenerationSettingsSnapshot, PreferencesSnapshot
from ..providers.factory import build_provider
from ..security.sanitizer import redact
from ..security.secrets import IN_MEMORY_SECRETS, SecretsStore
from ..tools.registry import ToolExecutionContext, ensure_builtin_tools_registered
from ..util.cancel import CancellationToken
from ..util.logging import LogBuffer


def resolve_secrets(prefs: PreferencesSnapshot, session_key: str) -> SecretsStore:
    if prefs.remember_key:
        IN_MEMORY_SECRETS.set_api_key(prefs.api_key)
        return IN_MEMORY_SECRETS
    IN_MEMORY_SECRETS.set_api_key(session_key)
    return IN_MEMORY_SECRETS


def _default_workspace_root(scene_context: Dict[str, object]) -> str:
    working_directory = scene_context.get("working_directory")
    if isinstance(working_directory, str) and working_directory.strip():
        return str(Path(working_directory).resolve())
    return ""


def run_generation(
    prefs: PreferencesSnapshot,
    settings: GenerationSettingsSnapshot,
    scene_context: Dict[str, object],
    session_key: str,
    cancel_token: CancellationToken,
    log_buffer: Optional[LogBuffer] = None,
    agent_state: Optional[AgentState] = None,
    tool_executor: Optional[Any] = None,
) -> AgentResult:
    ensure_builtin_tools_registered()
    secrets = resolve_secrets(prefs, session_key)
    provider = build_provider(prefs.provider, prefs.base_url, prefs.model_name, secrets)

    prompt_bundle = build_prompt(
        scene_context=scene_context,
        user_request=settings.prompt_text,
        custom_system_prompt=prefs.custom_system_prompt,
        append_custom=prefs.append_custom_prompt,
        fast_mode=settings.fast_mode,
    )

    tool_context = ToolExecutionContext(workspace_root=_default_workspace_root(scene_context))
    agent = AgentController(
        provider=provider,
        model=prefs.model_name,
        system_prompt=prompt_bundle.system_prompt,
        cancel_token=cancel_token,
        log_buffer=log_buffer,
        tool_executor=tool_executor,
        tool_context=tool_context,
        model_timeout_seconds=float(settings.model_timeout_seconds),
        max_model_retries=int(settings.model_max_retries),
        retry_backoff_seconds=float(settings.retry_backoff_seconds),
        require_plan_first=not settings.fast_mode,
        max_tool_calls_per_turn=int(settings.max_tool_calls_per_step),
        max_noop_steps=int(settings.max_noop_steps),
    )
    if agent_state is not None:
        agent.state = agent_state

    return agent.run(prompt_bundle.user_prompt, max_iterations=int(settings.max_ops))


def append_log(buffer: LogBuffer, message: str, secrets: List[str]) -> None:
    buffer.append(redact(message, secrets))

