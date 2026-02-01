"""Addon preferences and shared settings."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from .providers.factory import default_base_url
from .util.http import get_json
from .util.style_presets import STYLE_PRESET_ITEMS, get_style_preset


def _update_remember_key(self: "DreamAiriPreferences", _context: bpy.types.Context) -> None:
    if not self.remember_key:
        self.api_key = ""


OPENAI_FALLBACK_MODELS = ("gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo")
GEMINI_FALLBACK_MODELS = ("gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro")


class DreamAiriModelItem(bpy.types.PropertyGroup):
    name: StringProperty(name="Model Name")


def _get_cached_models(context: bpy.types.Context) -> list[str]:
    return [item.name for item in context.window_manager.dreamairi_model_cache]


def _set_cached_models(context: bpy.types.Context, models: Iterable[str]) -> None:
    cache = context.window_manager.dreamairi_model_cache
    cache.clear()
    for name in models:
        if not name:
            continue
        item = cache.add()
        item.name = name


def _model_enum_items(self: "DreamAiriPreferences", context: Optional[bpy.types.Context]) -> list[tuple[str, str, str]]:
    models = _get_cached_models(context) if context else []
    items = [("manual", "Manual Entry", "Enter model manually")]
    items.extend((name, name, "") for name in models)
    current = self.model_name.strip()
    if current and current not in models and current != "manual":
        items.append((current, f"{current} (custom)", "Current custom model"))
    return items


def _update_model_enum(self: "DreamAiriPreferences", _context: bpy.types.Context) -> None:
    if getattr(self, "_suppress_model_enum_update", False):
        return
    selection = self.model_enum
    if selection == "manual":
        if self.model_name:
            self._suppress_model_name_update = True
            try:
                self.model_name = ""
            finally:
                self._suppress_model_name_update = False
        return
    if selection and selection != self.model_name:
        self._suppress_model_name_update = True
        try:
            self.model_name = selection
        finally:
            self._suppress_model_name_update = False


def _update_model_name(self: "DreamAiriPreferences", _context: bpy.types.Context) -> None:
    if getattr(self, "_suppress_model_name_update", False):
        return
    self._suppress_model_enum_update = True
    try:
        if self.model_name:
            self.model_enum = self.model_name
        else:
            self.model_enum = "manual"
    finally:
        self._suppress_model_enum_update = False


def _update_base_url(self: "DreamAiriPreferences", _context: bpy.types.Context) -> None:
    if getattr(self, "_suppress_base_url_override", False):
        return
    self.lock_url = True


def _apply_default_base_url(prefs: "DreamAiriPreferences", provider: str) -> None:
    url = default_base_url(provider) or ""
    prefs._suppress_base_url_override = True
    try:
        prefs.base_url = url
        prefs.lock_url = False
    finally:
        prefs._suppress_base_url_override = False


def _get_api_key_for_fetch(context: bpy.types.Context, prefs: "DreamAiriPreferences") -> str:
    if prefs.remember_key:
        return prefs.api_key
    settings = getattr(context.scene, "dreamairi_settings", None)
    if settings:
        return settings.session_api_key
    return ""


def _fetch_models_from_provider(prefs: "DreamAiriPreferences", api_key: str) -> tuple[list[str], str]:
    provider = prefs.provider
    base_url = prefs.base_url.rstrip("/")
    if provider == "OLLAMA":
        _, payload = get_json(f"{base_url}/api/tags", headers={}, timeout=10)
        models = [item.get("name") for item in payload.get("models", []) if isinstance(item, dict)]
        return [name for name in models if name], ""
    if provider == "OPENROUTER":
        if not api_key:
            raise RuntimeError("API key required to fetch OpenRouter models")
        _, payload = get_json(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        entries = payload.get("data") or payload.get("models") or []
        models: list[str] = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            name = item.get("id") or item.get("name")
            if name:
                models.append(name)
        return models, ""
    if provider == "OPENAI":
        return list(OPENAI_FALLBACK_MODELS), "Model listing not supported; enter model manually."
    if provider == "GEMINI":
        return list(GEMINI_FALLBACK_MODELS), "Model listing not supported; enter model manually."
    return [], "Model listing not supported; enter model manually."


def fetch_models_for_provider(context: bpy.types.Context, prefs: "DreamAiriPreferences") -> None:
    window_manager = context.window_manager
    api_key = _get_api_key_for_fetch(context, prefs)
    try:
        models, info = _fetch_models_from_provider(prefs, api_key)
        _set_cached_models(context, models)
        if info:
            window_manager.dreamairi_model_fetch_info = info
        else:
            window_manager.dreamairi_model_fetch_info = ""
        window_manager.dreamairi_model_fetch_error = ""
        window_manager.dreamairi_model_fetch_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _apply_model_selection(context, prefs, models, info)
    except Exception as exc: 
        window_manager.dreamairi_model_fetch_error = str(exc)
        window_manager.dreamairi_model_fetch_info = ""


def _apply_model_selection(
    _context: bpy.types.Context,
    prefs: "DreamAiriPreferences",
    models: list[str],
    info: str,
) -> None:
    if not models:
        return
    current = prefs.model_name
    if current and current in models:
        return
    prefs._suppress_model_name_update = True
    prefs._suppress_model_enum_update = True
    try:
        prefs.model_name = models[0]
        prefs.model_enum = models[0]
    finally:
        prefs._suppress_model_name_update = False
        prefs._suppress_model_enum_update = False


def _update_provider(self: "DreamAiriPreferences", context: Optional[bpy.types.Context]) -> None:
    if context is None:
        return
    if not self.lock_url:
        _apply_default_base_url(self, self.provider)
    fetch_models_for_provider(context, self)


class DreamAiriPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    provider: EnumProperty(
        name="Provider",
        items=[
            ("OPENROUTER", "OpenRouter", "OpenRouter OpenAI-compatible"),
            ("OPENAI", "OpenAI", "OpenAI official API"),
            ("GEMINI", "Gemini", "Google Gemini"),
            ("OLLAMA", "Ollama", "Local Ollama"),
        ],
        default="OPENROUTER",
        update=_update_provider,
    )
    model_enum: EnumProperty(
        name="Model",
        description="Select a model from the cached list",
        items=_model_enum_items,
        update=_update_model_enum,
    )
    model_name: StringProperty(
        name="Model",
        description="Model identifier",
        default="openrouter/auto",
        update=_update_model_name,
    )
    base_url: StringProperty(
        name="Base URL",
        description="Override base URL for OpenRouter/OpenAI/Ollama",
        default="https://openrouter.ai/api/v1",
        update=_update_base_url,
    )
    lock_url: BoolProperty(
        name="Lock URL",
        description="Do not overwrite the Base URL when switching providers",
        default=False,
    )
    api_key: StringProperty(
        name="API Key",
        subtype="PASSWORD",
        description="API key for the selected provider",
        default="",
    )
    remember_key: BoolProperty(
        name="Remember key on this machine",
        description="Store API key in Blender preferences",
        default=False,
        update=_update_remember_key,
    )

    custom_system_prompt: StringProperty(
        name="Custom System Prompt",
        description="Optional user prompt appended after the internal prompt",
        default="",
    )
    custom_system_prompt_text_name: StringProperty(
        name="System Prompt Text Block",
        default="DreamAiri Custom System Prompt",
        description="Name of the Text datablock used for the custom system prompt",
    )
    append_custom_prompt: BoolProperty(
        name="Append custom system prompt after internal prompt",
        default=True,
    )

    debug_logging: BoolProperty(
        name="Enable debug logging",
        description="Include extra debug details in logs",
        default=False,
    )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.label(text="DreamAiri-blender Preferences")
        layout.prop(self, "provider")
        row = layout.row(align=True)
        row.prop(self, "model_enum", text="Model")
        row.operator("dreamairi.refresh_models", text="Refresh Models")
        layout.prop(self, "model_name")
        row = layout.row(align=True)
        row.prop(self, "base_url")
        row.operator("dreamairi.reset_base_url", text="Reset URL")
        if context.window_manager.dreamairi_model_fetch_time:
            layout.label(text=f"Last model fetch: {context.window_manager.dreamairi_model_fetch_time}")
        if context.window_manager.dreamairi_model_fetch_info:
            layout.label(text=context.window_manager.dreamairi_model_fetch_info)
        if context.window_manager.dreamairi_model_fetch_error:
            layout.label(text=f"Model fetch error: {context.window_manager.dreamairi_model_fetch_error}")
        layout.prop(self, "api_key")
        layout.prop(self, "remember_key")
        layout.separator()
        layout.label(text="Custom System Prompt")
        row = layout.row(align=True)
        row.prop(self, "custom_system_prompt_text_name", text="")
        row.operator("dreamairi.open_system_prompt_text", text="Open Custom System Prompt")
        preview = _get_custom_prompt_preview(self)
        if preview:
            layout.label(text=f"Preview: {preview}")
        else:
            layout.label(text="Preview: (empty)")
        layout.operator("dreamairi.show_default_prompt", text="View Default System Prompt")
        layout.operator("dreamairi.show_effective_prompt", text="Show Effective System Prompt")
        layout.prop(self, "append_custom_prompt")
        layout.prop(self, "debug_logging")


def _update_style_preset(self: "DreamAiriSettings", _context: bpy.types.Context) -> None:
    preset = get_style_preset(self.style_preset)
    self.triangle_budget = preset.poly_budget
    self.bevel_default = preset.bevel_range[0]


class DreamAiriSettings(bpy.types.PropertyGroup):
    style_preset: EnumProperty(
        name="Style Preset",
        items=STYLE_PRESET_ITEMS,
        default="LOW_POLY_CLEAN",
        update=_update_style_preset,
    )
    triangle_budget: IntProperty(
        name="Target Poly Budget",
        min=50,
        default=800,
    )
    prompt_text: StringProperty(
        name="Prompt",
        default="",
    )
    prompt_text_block: PointerProperty(
        name="Prompt Text",
        type=bpy.types.Text,
    )
    session_api_key: StringProperty(
        name="API Key",
        subtype="PASSWORD",
        default="",
    )
    example_prompt: EnumProperty(
        name="Examples",
        items=[
            ("NONE", "Select Example", ""),
            ("BOWLING_PIN", "Bowling Pin", "Create a bowling pin"),
            ("LOW_POLY_CRATE", "Low-Poly Crate", "Create a low-poly crate"),
            ("CACTUS", "Cactus in Pot", "Create a low-poly cactus"),
        ],
        default="NONE",
    )
    show_logs: BoolProperty(
        name="Show Logs",
        default=True,
    )
    log_text: StringProperty(
        name="Logs",
        default="",
    )

    max_ops: IntProperty(
        name="Max Ops",
        default=80,
        min=1,
        max=200,
    )
    max_primitives: IntProperty(
        name="Max Primitives",
        default=40,
        min=1,
        max=200,
    )
    strict_mode: BoolProperty(
        name="Paranoid Mode",
        default=True,
    )

    bevel_default: FloatProperty(
        name="Bevel Default",
        default=0.02,
        min=0.0,
        max=1.0,
    )


@dataclass
class PreferencesSnapshot:
    provider: str
    model_name: str
    base_url: str
    api_key: str
    remember_key: bool
    custom_system_prompt: str
    append_custom_prompt: bool
    debug_logging: bool


@dataclass
class GenerationSettingsSnapshot:
    style_preset: str
    triangle_budget: int
    prompt_text: str
    max_ops: int
    max_primitives: int
    strict_mode: bool


def get_preferences(context: bpy.types.Context) -> Optional[DreamAiriPreferences]:
    addon_prefs = context.preferences.addons.get(__package__)
    if addon_prefs is None:
        return None
    return addon_prefs.preferences


def snapshot_preferences(context: bpy.types.Context) -> PreferencesSnapshot:
    prefs = get_preferences(context)
    if prefs is None:
        raise RuntimeError("DreamAiri preferences not found")
    return PreferencesSnapshot(
        provider=prefs.provider,
        model_name=prefs.model_name,
        base_url=prefs.base_url,
        api_key=prefs.api_key,
        remember_key=prefs.remember_key,
        custom_system_prompt=resolve_custom_system_prompt(prefs),
        append_custom_prompt=prefs.append_custom_prompt,
        debug_logging=prefs.debug_logging,
    )


def snapshot_generation_settings(settings: DreamAiriSettings) -> GenerationSettingsSnapshot:
    return GenerationSettingsSnapshot(
        style_preset=settings.style_preset,
        triangle_budget=settings.triangle_budget,
        prompt_text=resolve_prompt_text(settings),
        max_ops=settings.max_ops,
        max_primitives=settings.max_primitives,
        strict_mode=settings.strict_mode,
    )


def resolve_custom_system_prompt(prefs: DreamAiriPreferences) -> str:
    text_block_name = prefs.custom_system_prompt_text_name
    if text_block_name:
        text_block = bpy.data.texts.get(text_block_name)
        if text_block:
            content = text_block.as_string()
            if content.strip():
                return content
    return prefs.custom_system_prompt


def _get_custom_prompt_preview(prefs: DreamAiriPreferences, limit: int = 140) -> str:
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


def resolve_prompt_text(settings: DreamAiriSettings) -> str:
    if settings.prompt_text_block:
        return settings.prompt_text_block.as_string()
    return settings.prompt_text


def _is_registered_class(cls: type) -> bool:
    checker = getattr(bpy.utils, "is_registered_class", None)
    if callable(checker):
        return checker(cls)
    return hasattr(bpy.types, cls.__name__)


def _safe_unregister_class(cls: type) -> None:
    try:
        if _is_registered_class(cls):
            bpy.utils.unregister_class(cls)
    except RuntimeError:
        return


def _safe_register_class(cls: type) -> None:
    _safe_unregister_class(cls)
    bpy.utils.register_class(cls)


def register() -> None:
    _safe_register_class(DreamAiriModelItem)
    _safe_register_class(DreamAiriPreferences)
    _safe_register_class(DreamAiriSettings)
    if hasattr(bpy.types.Scene, "dreamairi_settings"):
        del bpy.types.Scene.dreamairi_settings
    bpy.types.Scene.dreamairi_settings = PointerProperty(type=DreamAiriSettings)
    if hasattr(bpy.types.WindowManager, "dreamairi_model_cache"):
        del bpy.types.WindowManager.dreamairi_model_cache
    bpy.types.WindowManager.dreamairi_model_cache = CollectionProperty(type=DreamAiriModelItem)
    if hasattr(bpy.types.WindowManager, "dreamairi_model_fetch_error"):
        del bpy.types.WindowManager.dreamairi_model_fetch_error
    bpy.types.WindowManager.dreamairi_model_fetch_error = StringProperty(default="")
    if hasattr(bpy.types.WindowManager, "dreamairi_model_fetch_info"):
        del bpy.types.WindowManager.dreamairi_model_fetch_info
    bpy.types.WindowManager.dreamairi_model_fetch_info = StringProperty(default="")
    if hasattr(bpy.types.WindowManager, "dreamairi_model_fetch_time"):
        del bpy.types.WindowManager.dreamairi_model_fetch_time
    bpy.types.WindowManager.dreamairi_model_fetch_time = StringProperty(default="")


def unregister() -> None:
    if hasattr(bpy.types.WindowManager, "dreamairi_model_fetch_time"):
        del bpy.types.WindowManager.dreamairi_model_fetch_time
    if hasattr(bpy.types.WindowManager, "dreamairi_model_fetch_info"):
        del bpy.types.WindowManager.dreamairi_model_fetch_info
    if hasattr(bpy.types.WindowManager, "dreamairi_model_fetch_error"):
        del bpy.types.WindowManager.dreamairi_model_fetch_error
    if hasattr(bpy.types.WindowManager, "dreamairi_model_cache"):
        del bpy.types.WindowManager.dreamairi_model_cache
    if hasattr(bpy.types.Scene, "dreamairi_settings"):
        del bpy.types.Scene.dreamairi_settings
    _safe_unregister_class(DreamAiriSettings)
    _safe_unregister_class(DreamAiriPreferences)
    _safe_unregister_class(DreamAiriModelItem)
