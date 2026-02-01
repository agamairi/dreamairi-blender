import os
import sys
from pathlib import Path

import bpy


def main() -> None:
    model = os.getenv("DREAMAIRI_OLLAMA_MODEL")
    if not model:
        print("Skipping Ollama integration test; DREAMAIRI_OLLAMA_MODEL not set.")
        return

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    import dreamairi_blender
    from dreamairi_blender.core.generator import execute_plan, run_generation
    from dreamairi_blender.preferences import snapshot_generation_settings, snapshot_preferences
    from dreamairi_blender.util.cancel import CancellationToken

    dreamairi_blender.register()

    settings = bpy.context.scene.dreamairi_settings
    settings.prompt_text = "Create a low-poly bowling pin"
    settings.triangle_budget = 800
    settings.max_ops = 20
    settings.max_primitives = 10

    prefs = bpy.context.preferences.addons["dreamairi_blender"].preferences
    prefs.provider = "OLLAMA"
    prefs.model_name = model
    prefs.base_url = os.getenv("DREAMAIRI_OLLAMA_BASE_URL", "http://localhost:11434")
    prefs.remember_key = False

    result = run_generation(
        prefs=snapshot_preferences(bpy.context),
        settings=snapshot_generation_settings(settings),
        session_key="",
        cancel_token=CancellationToken(),
    )
    execute_plan(result.plan, target_poly_budget=settings.triangle_budget)

    dreamairi_blender.unregister()


if __name__ == "__main__":
    main()
