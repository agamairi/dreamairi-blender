import os
import sys
from pathlib import Path

import bpy


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    import dreamairi_blender
    from dreamairi_blender.core.generator import execute_plan, run_generation
    from dreamairi_blender.preferences import snapshot_generation_settings, snapshot_preferences
    from dreamairi_blender.providers.factory import default_base_url
    from dreamairi_blender.util.cancel import CancellationToken

    import dreamairi_blender
    
    # Ensure addon is "enabled" - this will call register()
    addon_name = "dreamairi_blender"
    if addon_name not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module=addon_name)

    settings = bpy.context.scene.dreamairi_settings
    settings.prompt_text = "Create a bowling pin"
    settings.triangle_budget = 800

    prefs = bpy.context.preferences.addons[addon_name].preferences
    prefs.lock_url = False
    prefs.provider = "OPENAI"
    prefs.model_name = "mock-model"
    
    expected_base_url = default_base_url("OPENAI")
    assert prefs.base_url == expected_base_url, "Base URL did not update for provider"
    
    cached_models = [item.name for item in bpy.context.window_manager.dreamairi_model_cache]
    assert "mock-model" in cached_models or prefs.model_name == "mock-model", "Expected models to be available"

    prefs.provider = "OPENROUTER"
    prefs.model_name = "mock"
    settings.session_api_key = "test-key"

    os.environ["DREAMAIRI_MOCK_RESPONSE"] = """
    {
      "version": "1",
      "summary": "Bowling pin",
      "style": {"poly_budget": 800, "notes": "low poly"},
      "ops": [
        {
          "op": "ADD_PRIMITIVE",
          "payload": {
            "type": "cylinder",
            "name": "DA_BowlingPin",
            "location": [0, 0, 0],
            "params": {"radius": 0.2, "depth": 1.2, "vertices": 12}
          }
        },
        {
          "op": "MODIFIER",
          "payload": {
            "target": "DA_BowlingPin",
            "modifier": "BEVEL",
            "params": {"width": 0.02, "segments": 1}
          }
        },
        {
          "op": "APPLY_MODIFIER",
          "payload": {
            "target": "DA_BowlingPin",
            "modifier": "BEVEL"
          }
        },
        {
          "op": "MATERIAL_CREATE",
          "payload": {
            "name": "Pin_White",
            "base_color": [0.9, 0.9, 0.9, 1.0]
          }
        },
        {
          "op": "MATERIAL_ASSIGN",
          "payload": {
            "target": "DA_BowlingPin",
            "material": "Pin_White"
          }
        },
        {
          "op": "VALIDATE_MESH",
          "payload": {
            "target": "DA_BowlingPin",
            "budget": 800
          }
        }
      ]
    }
    """

    from dreamairi_blender.tools.context import build_scene_context

    pref_snap = snapshot_preferences(bpy.context)
    set_snap = snapshot_generation_settings(settings)
    ctx_snap = build_scene_context(set_snap)

    result = run_generation(
        prefs=pref_snap,
        settings=set_snap,
        scene_context=ctx_snap,
        session_key=settings.session_api_key,
        cancel_token=CancellationToken(),
    )
    execute_plan(result.plan, target_poly_budget=settings.triangle_budget)

    found = [obj for obj in bpy.data.objects if "BowlingPin" in obj.name]
    assert found, "Expected bowling pin object"
    tri_count = len(found[0].data.polygons)
    assert tri_count <= settings.triangle_budget + 80, "Poly budget exceeded"
    assert found[0].data.materials, "Expected material assigned"

    dreamairi_blender.unregister()


if __name__ == "__main__":
    main()
