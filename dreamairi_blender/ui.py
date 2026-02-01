"""User interface panels and operators."""
from __future__ import annotations

import threading
from dataclasses import dataclass
import textwrap
from typing import Optional

import bpy

from .core.generator import (
    append_log,
    execute_plan,
    format_plan,
    run_generation,
)
from .llm import prompts
from .preferences import (
    DreamAiriSettings,
    fetch_models_for_provider,
    get_preferences,
    resolve_custom_system_prompt,
    resolve_prompt_text,
    snapshot_generation_settings,
    snapshot_preferences,
)
from .providers.factory import default_base_url, requires_api_key
from .security.secrets import IN_MEMORY_SECRETS
from .tools.context import build_scene_context
from .util.cancel import CancellationToken
from .util.http import get_json
from .util.logging import LogBuffer


@dataclass
class ActiveJob:
    thread: threading.Thread
    token: CancellationToken
    mode: str
    done: bool = False
    error: Optional[str] = None
    result: Optional[object] = None


_ACTIVE_JOB: Optional[ActiveJob] = None


def _get_api_key(prefs, settings: DreamAiriSettings) -> str:
    if prefs.remember_key:
        return prefs.api_key
    return settings.session_api_key


def _ensure_text_block(existing: bpy.types.Text | None, name: str) -> bpy.types.Text:
    if existing:
        return existing
    text_block = bpy.data.texts.get(name)
    if text_block is None:
        text_block = bpy.data.texts.new(name)
    return text_block


def _get_system_prompt_text_name(prefs) -> str:
    name = prefs.custom_system_prompt_text_name.strip()
    if not name:
        name = "DreamAiri Custom System Prompt"
        prefs.custom_system_prompt_text_name = name
    return name


def _ensure_system_prompt_text_block(prefs) -> bpy.types.Text:
    name = _get_system_prompt_text_name(prefs)
    return _ensure_text_block(None, name)


def _set_text_block_contents(text_block: bpy.types.Text, content: str) -> None:
    text_block.clear()
    text_block.write(content)


def _set_log(settings: DreamAiriSettings, message: str, secrets: list[str]) -> None:
    buffer = LogBuffer(settings.log_text)
    append_log(buffer, message, secrets)
    settings.log_text = buffer.text


def _test_connection(prefs, api_key: str) -> None:
    if prefs.provider == "OLLAMA":
        url = prefs.base_url.rstrip("/") + "/api/tags"
        get_json(url, headers={}, timeout=10)
        return
    if prefs.provider == "GEMINI":
        url = f"{prefs.base_url.rstrip('/')}/models/{prefs.model_name}?key={api_key}"
        get_json(url, headers={}, timeout=10)
        return
    url = prefs.base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    get_json(url, headers=headers, timeout=10)


def _get_custom_prompt_preview(prefs, limit: int = 140) -> str:
    text_block_name = prefs.custom_system_prompt_text_name
    if text_block_name:
        text_block = bpy.data.texts.get(text_block_name)
        if text_block:
            content = text_block.as_string().strip()
            if content:
                return (content[:limit] + "...") if len(content) > limit else content
    if prefs.custom_system_prompt:
        content = prefs.custom_system_prompt.strip()
        return (content[:limit] + "...") if len(content) > limit else content
    return ""


def _format_prompt_lines(text: str, max_lines: int = 60, width: int = 110) -> list[str]:
    wrapped: list[str] = []
    for line in text.splitlines() or [""]:
        wrapped.extend(textwrap.wrap(line, width=width) or [""])
    if len(wrapped) > max_lines:
        return wrapped[:max_lines] + ["..."]
    return wrapped


def _build_effective_prompt_text(prefs, settings: DreamAiriSettings) -> str:
    prompt = prompts.build_prompt(
        scene_context={},
        user_request="",
        custom_system_prompt=resolve_custom_system_prompt(prefs),
        append_custom=prefs.append_custom_prompt,
    ).system_prompt
    summary = "\n".join(
        [
            f"Provider: {prefs.provider}",
            f"Model: {prefs.model_name}",
            f"Base URL: {prefs.base_url}",
            f"Append custom prompt: {'Yes' if prefs.append_custom_prompt else 'No'}",
        ]
    )
    return f"Settings Summary:\n{summary}\n\nSystem Prompt:\n{prompt}"


class DREAMAIRI_OT_TestConnection(bpy.types.Operator):
    bl_idname = "dreamairi.test_connection"
    bl_label = "Test Connection"
    bl_description = "Test provider connectivity"

    def execute(self, context: bpy.types.Context) -> set[str]:
        prefs = get_preferences(context)
        settings = context.scene.dreamairi_settings
        if prefs is None:
            self.report({'ERROR'}, "Preferences not found")
            return {'CANCELLED'}
        api_key = _get_api_key(prefs, settings)
        if requires_api_key(prefs.provider) and not api_key:
            self.report({'ERROR'}, "API key is required")
            return {'CANCELLED'}
        except Exception as exc: 
            self.report({'ERROR'}, f"Connection failed: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, "Connection successful")
        return {'FINISHED'}


class DREAMAIRI_OT_UseExample(bpy.types.Operator):
    bl_idname = "dreamairi.use_example"
    bl_label = "Use Example"
    bl_description = "Populate the prompt with the selected example"

    def execute(self, context: bpy.types.Context) -> set[str]:
        settings = context.scene.dreamairi_settings
        prompt = _ensure_text_block(settings.prompt_text_block, "DreamAiri Prompt")
        if settings.example_prompt == "BOWLING_PIN":
            prompt_text = "Create a low-poly bowling pin with a red ring."
        elif settings.example_prompt == "LOW_POLY_CRATE":
            prompt_text = "Create a low-poly wooden crate with beveled edges."
        elif settings.example_prompt == "CACTUS":
            prompt_text = "Create a low-poly cactus in a small pot."
        else:
            return {'FINISHED'}
        settings.prompt_text_block = prompt
        settings.prompt_text = prompt_text
        _set_text_block_contents(prompt, prompt_text)
        return {'FINISHED'}


class DREAMAIRI_OT_ResetCustomPrompt(bpy.types.Operator):
    bl_idname = "dreamairi.reset_custom_prompt"
    bl_label = "Reset Custom System Prompt"
    bl_description = "Clear the custom system prompt"

    def execute(self, context: bpy.types.Context) -> set[str]:
        prefs = get_preferences(context)
        if prefs:
            prompt = _ensure_system_prompt_text_block(prefs)
            prefs.custom_system_prompt = ""
            _set_text_block_contents(prompt, "")
        return {'FINISHED'}


class DREAMAIRI_OT_ResetDefaultPrompt(bpy.types.Operator):
    bl_idname = "dreamairi.reset_default_prompt"
    bl_label = "Reset to Default System Prompt"
    bl_description = "Reset the custom prompt to a recommended template"

    def execute(self, context: bpy.types.Context) -> set[str]:
        prefs = get_preferences(context)
        if prefs:
            prompt = _ensure_system_prompt_text_block(prefs)
            prefs.custom_system_prompt = prompts.DEFAULT_CUSTOM_TEMPLATE
            _set_text_block_contents(prompt, prompts.DEFAULT_CUSTOM_TEMPLATE)
        return {'FINISHED'}


class DREAMAIRI_OT_OpenSystemPromptText(bpy.types.Operator):
    bl_idname = "dreamairi.open_system_prompt_text"
    bl_label = "Open Custom System Prompt"
    bl_description = "Create or open the system prompt text block"

    def execute(self, context: bpy.types.Context) -> set[str]:
        prefs = get_preferences(context)
        if prefs is None:
            self.report({'ERROR'}, "Preferences not found")
            return {'CANCELLED'}
        text_block = _ensure_system_prompt_text_block(prefs)
        for area in context.screen.areas:
            if area.type != "TEXT_EDITOR":
                continue
            for space in area.spaces:
                if space.type == "TEXT_EDITOR":
                    space.text = text_block
                    area.tag_redraw()
                    self.report({'INFO'}, "System prompt text block opened")
                    return {'FINISHED'}
        self.report({'INFO'}, "System prompt text block ready. Open the Scripting workspace to edit.")
        return {'FINISHED'}


class DREAMAIRI_OT_ShowDefaultPrompt(bpy.types.Operator):
    bl_idname = "dreamairi.show_default_prompt"
    bl_label = "View Default System Prompt"
    bl_description = "Show the internal default system prompt"

    def invoke(self, context: bpy.types.Context, _event: bpy.types.Event) -> set[str]:
        self._lines = _format_prompt_lines(prompts.INTERNAL_SYSTEM_PROMPT)
        return context.window_manager.invoke_props_dialog(self, width=600)

    def draw(self, _context: bpy.types.Context) -> None:
        layout = self.layout
        layout.label(text="Default System Prompt")
        box = layout.box()
        for line in getattr(self, "_lines", []):
            box.label(text=line)

    def execute(self, _context: bpy.types.Context) -> set[str]:
        return {'FINISHED'}


class DREAMAIRI_OT_ShowEffectivePrompt(bpy.types.Operator):
    bl_idname = "dreamairi.show_effective_prompt"
    bl_label = "Show Effective System Prompt"
    bl_description = "Show the combined system prompt used for generation"

    def invoke(self, context: bpy.types.Context, _event: bpy.types.Event) -> set[str]:
        prefs = get_preferences(context)
        settings = context.scene.dreamairi_settings
        if prefs is None:
            self._lines = ["Preferences not found."]
        else:
            self._lines = _format_prompt_lines(_build_effective_prompt_text(prefs, settings))
        return context.window_manager.invoke_props_dialog(self, width=600)

    def draw(self, _context: bpy.types.Context) -> None:
        layout = self.layout
        layout.label(text="Effective System Prompt")
        box = layout.box()
        for line in getattr(self, "_lines", []):
            box.label(text=line)

    def execute(self, _context: bpy.types.Context) -> set[str]:
        return {'FINISHED'}


class DREAMAIRI_OT_ResetBaseURL(bpy.types.Operator):
    bl_idname = "dreamairi.reset_base_url"
    bl_label = "Reset URL"
    bl_description = "Reset the Base URL to the provider default"

    def execute(self, context: bpy.types.Context) -> set[str]:
        prefs = get_preferences(context)
        if prefs is None:
            self.report({'ERROR'}, "Preferences not found")
            return {'CANCELLED'}
        prefs.lock_url = False
        prefs._suppress_base_url_override = True
        try:
            default_url = default_base_url(prefs.provider) or ""
            prefs.base_url = default_url
        finally:
            prefs._suppress_base_url_override = False
        return {'FINISHED'}


class DREAMAIRI_OT_RefreshModels(bpy.types.Operator):
    bl_idname = "dreamairi.refresh_models"
    bl_label = "Refresh Models"
    bl_description = "Fetch available models for the current provider"

    def execute(self, context: bpy.types.Context) -> set[str]:
        prefs = get_preferences(context)
        if prefs is None:
            self.report({'ERROR'}, "Preferences not found")
            return {'CANCELLED'}
        fetch_models_for_provider(context, prefs)
        if context.window_manager.dreamairi_model_fetch_error:
            self.report({'ERROR'}, context.window_manager.dreamairi_model_fetch_error)
            return {'CANCELLED'}
        self.report({'INFO'}, "Model list refreshed")
        return {'FINISHED'}


class DREAMAIRI_OT_Stop(bpy.types.Operator):
    bl_idname = "dreamairi.stop"
    bl_label = "Stop"
    bl_description = "Cancel the active generation"

    def execute(self, context: bpy.types.Context) -> set[str]:
        global _ACTIVE_JOB
        if _ACTIVE_JOB:
            _ACTIVE_JOB.token.cancel()
            self.report({'INFO'}, "Cancellation requested")
            return {'FINISHED'}
        self.report({'INFO'}, "No active job")
        return {'CANCELLED'}


class _BaseGenerateOperator(bpy.types.Operator):
    _timer: Optional[bpy.types.Timer] = None
    mode: str = "dry"

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        global _ACTIVE_JOB
        if _ACTIVE_JOB and not _ACTIVE_JOB.done:
            self.report({'ERROR'}, "Generation already in progress")
            return {'CANCELLED'}

        settings = context.scene.dreamairi_settings
        prefs = get_preferences(context)
        if prefs is None:
            self.report({'ERROR'}, "Preferences not found")
            return {'CANCELLED'}

        prompt_text = resolve_prompt_text(settings).strip()
        if not prompt_text:
            self.report({'ERROR'}, "Prompt is empty")
            return {'CANCELLED'}

        api_key = _get_api_key(prefs, settings)
        if requires_api_key(prefs.provider) and not api_key:
            self.report({'ERROR'}, "API key is required")
            return {'CANCELLED'}

        # Snapshot everything BEFORE starting the thread (main thread)
        prefs_snap = snapshot_preferences(context)
        settings_snap = snapshot_generation_settings(settings)
        scene_ctx_snap = build_scene_context(settings_snap)
        
        token = CancellationToken()
        IN_MEMORY_SECRETS.set_api_key(api_key)

        def worker(p_snap, s_snap, c_snap) -> None:
            try:
                result = run_generation(
                    prefs=p_snap,
                    settings=s_snap,
                    scene_context=c_snap,
                    session_key=api_key,
                    cancel_token=token,
                )
                _ACTIVE_JOB.result = result
            except Exception as exc: 
                _ACTIVE_JOB.error = str(exc)
            finally:
                _ACTIVE_JOB.done = True

        _ACTIVE_JOB = ActiveJob(thread=threading.Thread(
            target=worker, 
            args=(prefs_snap, settings_snap, scene_ctx_snap), 
            daemon=True
        ), token=token, mode=self.mode)
        _ACTIVE_JOB.thread.start()
        self._timer = context.window_manager.event_timer_add(0.5, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        global _ACTIVE_JOB
        if event.type != 'TIMER' or not _ACTIVE_JOB:
            return {'RUNNING_MODAL'}
        if not _ACTIVE_JOB.done:
            return {'RUNNING_MODAL'}
        settings = context.scene.dreamairi_settings
        prefs = get_preferences(context)
        secrets = [prefs.api_key, settings.session_api_key] if prefs else []
        if _ACTIVE_JOB.error:
            _set_log(settings, f"Error: {_ACTIVE_JOB.error}", secrets)
            self._finish(context)
            return {'CANCELLED'}
        result = _ACTIVE_JOB.result
        if result is None:
            _set_log(settings, "No response received", secrets)
            self._finish(context)
            return {'CANCELLED'}

        _set_log(settings, f"request_id: {result.request_id}", secrets)
        _set_log(settings, f"provider: {prefs.provider if prefs else 'unknown'}", secrets)
        _set_log(settings, f"model: {prefs.model_name if prefs else 'unknown'}", secrets)
        _set_log(settings, f"summary: {result.plan.summary}", secrets)
        _set_log(settings, f"plan_json:\n{format_plan(result.plan)}", secrets)
        if prefs and prefs.debug_logging:
            _set_log(settings, f"raw_response:\n{result.raw_text}", secrets)
        if _ACTIVE_JOB.mode == "apply":
            try:
                execute_plan(
                    result.plan,
                    target_poly_budget=settings.triangle_budget,
                    style_preset=settings.style_preset,
                )
                _set_log(settings, "Execution completed", secrets)
            except Exception as exc: 
                _set_log(settings, f"Execution failed: {exc}", secrets)
                self._finish(context)
                return {'CANCELLED'}

        self._finish(context)
        return {'FINISHED'}

    def _finish(self, context: bpy.types.Context) -> None:
        global _ACTIVE_JOB
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        _ACTIVE_JOB = None


class DREAMAIRI_OT_GenerateApply(_BaseGenerateOperator):
    bl_idname = "dreamairi.generate_apply"
    bl_label = "Generate"
    bl_description = "Generate and apply the plan"
    bl_options = {'REGISTER', 'UNDO'}
    mode = "apply"


class DREAMAIRI_PT_Panel(bpy.types.Panel):
    bl_label = "DreamAiri-blender"
    bl_idname = "DREAMAIRI_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'DreamAiri-blender'

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        prefs = get_preferences(context)
        settings = context.scene.dreamairi_settings

        layout.label(text="Provider")
        if prefs:
            layout.prop(prefs, "provider")
            row = layout.row(align=True)
            row.prop(prefs, "model_enum", text="Model")
            row.operator("dreamairi.refresh_models", text="", icon='FILE_REFRESH')
            layout.prop(prefs, "model_name")
            row = layout.row(align=True)
            row.prop(prefs, "base_url")
            row.prop(prefs, "lock_url", text="", icon='LOCKED' if prefs.lock_url else 'UNLOCKED')
            layout.operator("dreamairi.reset_base_url", text="Reset URL")
            if context.window_manager.dreamairi_model_fetch_time:
                layout.label(text=f"Last model fetch: {context.window_manager.dreamairi_model_fetch_time}")
            if context.window_manager.dreamairi_model_fetch_info:
                layout.label(text=context.window_manager.dreamairi_model_fetch_info)
            if context.window_manager.dreamairi_model_fetch_error:
                layout.label(text=f"Model fetch error: {context.window_manager.dreamairi_model_fetch_error}")
            layout.prop(prefs, "remember_key")
            if prefs.remember_key:
                layout.prop(prefs, "api_key")
            else:
                layout.prop(settings, "session_api_key", text="API Key")
            layout.operator("dreamairi.test_connection", icon='CHECKMARK')
        else:
            layout.label(text="Preferences not found")

        layout.separator()
        layout.label(text="Prompting")
        if prefs:
            layout.label(text="Custom System Prompt Text")
            row = layout.row(align=True)
            row.prop(prefs, "custom_system_prompt_text_name", text="")
            row.operator("dreamairi.open_system_prompt_text", text="Open Custom System Prompt", icon='FILE_TEXT')
            preview = _get_custom_prompt_preview(prefs)
            if preview:
                layout.label(text=f"Preview: {preview}")
            else:
                layout.label(text="Preview: (empty)")
            layout.operator("dreamairi.show_default_prompt", text="View Default System Prompt")
            layout.operator("dreamairi.show_effective_prompt", text="Show Effective System Prompt")
            layout.prop(prefs, "append_custom_prompt")
            row = layout.row(align=True)
            row.operator("dreamairi.reset_custom_prompt", text="Reset Custom System Prompt")
            row.operator("dreamairi.reset_default_prompt", text="Reset to Default")

        layout.prop(settings, "style_preset")
        layout.prop(settings, "triangle_budget")
        layout.label(text="Prompt Input Text")
        layout.template_ID(settings, "prompt_text_block", new="text.new", open="text.open")
        if not settings.prompt_text_block:
            layout.prop(settings, "prompt_text", text="Prompt Input")
        row = layout.row(align=True)
        row.prop(settings, "example_prompt", text="")
        row.operator("dreamairi.use_example", text="Use Example")

        layout.separator()
        layout.label(text="Generation")
        layout.prop(settings, "strict_mode")
        
        global _ACTIVE_JOB
        is_busy = _ACTIVE_JOB and not _ACTIVE_JOB.done
        
        row = layout.row(align=True)
        if is_busy:
            row.operator("dreamairi.generate_apply", text="Generating...", icon='TIME', depress=True)
            row.enabled = False
        else:
            row.operator("dreamairi.generate_apply", icon='PLAY')
            
        if is_busy:
            layout.label(text="Status: AI is working...", icon='INFO')
            layout.operator("dreamairi.stop", icon='CANCEL')
        elif _ACTIVE_JOB and _ACTIVE_JOB.done and _ACTIVE_JOB.error:
            layout.label(text="Last Error: (See Logs)", icon='ERROR')

        layout.separator()
        layout.label(text="Logs")
        layout.prop(settings, "show_logs")
        if settings.show_logs:
            layout.prop(settings, "log_text", text="")


classes = (
    DREAMAIRI_OT_TestConnection,
    DREAMAIRI_OT_UseExample,
    DREAMAIRI_OT_ResetCustomPrompt,
    DREAMAIRI_OT_ResetDefaultPrompt,
    DREAMAIRI_OT_OpenSystemPromptText,
    DREAMAIRI_OT_ShowDefaultPrompt,
    DREAMAIRI_OT_ShowEffectivePrompt,
    DREAMAIRI_OT_ResetBaseURL,
    DREAMAIRI_OT_RefreshModels,
    DREAMAIRI_OT_Stop,
    DREAMAIRI_OT_GenerateApply,
    DREAMAIRI_PT_Panel,
)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
