"""DreamAiri Blender add-on entry point."""
from __future__ import annotations

import importlib

bl_info = {
    "name": "DreamAiri-blender",
    "author": "DreamAiri",
    "version": (1, 0, 0),
    "blender": (5, 0, 1),
    "location": "View3D > Sidebar > DreamAiri-blender",
    "description": "Generate meshes from plain-English requests using a safe, tool-based LLM pipeline.",
    "category": "3D View",
}

MODULE_NAMES = ("preferences", "ui")
_REGISTERED = False


def register() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    for name in MODULE_NAMES:
        module = importlib.import_module(f"{__package__}.{name}")
        module.register()
    _REGISTERED = True


def unregister() -> None:
    global _REGISTERED
    if not _REGISTERED:
        return
    for name in reversed(MODULE_NAMES):
        module = importlib.import_module(f"{__package__}.{name}")
        module.unregister()
    _REGISTERED = False


if __name__ == "__main__":
    register()
