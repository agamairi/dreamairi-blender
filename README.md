# DreamAiri-Blender

DreamAiri is a Blender add-on that runs a strict agent loop:

1. `PLAN`
2. `TOOL_CALL` (whitelisted tools only)
3. `VERIFY` (tool results returned to model)
4. iterate until `FINAL`

No arbitrary Python can be requested from the model. Scene mutations happen only through the tool registry.

## Architecture

Core modules:

- `/Users/agamairi/Downloads/dreamairi-blender-main/dreamairi_blender/core/agent.py`
  - Multi-turn agent controller
  - Enforces `PLAN` / `TOOL_CALL` / `FINAL` envelope contract
  - Guardrails: max steps, retries/backoff, max tool calls per turn, no-progress stop, repeated-call stop
- `/Users/agamairi/Downloads/dreamairi-blender-main/dreamairi_blender/llm/prompts.py`
  - Strict system prompt with response schema and tool registry catalog
  - Fast mode policy toggle (plan-first required or optional)
- `/Users/agamairi/Downloads/dreamairi-blender-main/dreamairi_blender/tools/registry.py`
  - Typed tool metadata
  - JSON-schema-like argument validator
  - Permission checks
  - Structured `ToolResult` with error taxonomy
- `/Users/agamairi/Downloads/dreamairi-blender-main/dreamairi_blender/tools/implementations.py`
  - Starter toolset (scene, animation, workspace file ops, diagnostics)

Error taxonomy:

- `validation_error`
- `tool_error`
- `blender_error`
- `model_error`

## Tooling Model

The model can only call registered tools.

Starter toolset includes:

- Scene ops: `create_primitive`, `delete_objects`, `select_objects`, `transform_object`, `assign_material`, `import_asset`, `export_asset`, `export_glb`
- Rig/animation ops: `create_action`, `set_active_action`, `pose_bone_transform`, `insert_keyframe`, `duplicate_action`, `mirror_action`, `bake_action`, `set_current_frame`
- Workspace file ops: `list_project_files`, `read_project_file`, `write_project_file`
- Diagnostics: `get_selection`, `list_actions`, `list_armatures`, `get_current_frame`, `get_diagnostics`
- Inspection/render ops: `render_viewport_snapshot`, `render_turntable_preview`, `get_object_dimensions`, `get_object_profile_samples`, `get_scene_summary`, `measure_object_symmetry`, `get_mesh_stats`

All tool calls return structured JSON-like dictionaries (`ToolResult.to_dict()`).

## Security Model

- Deny-by-default tool invocation via registry.
- Strict argument validation against each tool schema.
- Permission-gated execution (scene/anim/file/diagnostics/render scopes).
- Workspace-scoped file access only:
  - relative or absolute paths must resolve inside workspace root
  - small file limits for read/write
- No `exec`, no `eval`, no arbitrary Python from model output.

## UI

Panel is focused on:

- Chat prompt input
- Run / Stop
- Status (`Thinking`, `Running tool`, `Done`, `Error`)
- Step progress (`step/max`, last tool, last error)
- Collapsible sections:
  - Plan
  - Tool calls
  - Tool results
  - Logs
- `Fast mode` toggle (if off, agent must output plan first)
- `Verbose` toggle (raw JSON visibility)

## Add a Tool (Developer)

1. Implement handler in `/Users/agamairi/Downloads/dreamairi-blender-main/dreamairi_blender/tools/implementations.py`.
2. Define metadata:
   - `name`
   - `description`
   - `args_schema`
   - `permissions`
3. Register it in `_tool_specs()` so `register_default_tools()` includes it.
4. Run test harness.

Minimal example:

```python
from dreamairi_blender.tools.registry import ToolMetadata, ToolResult

def my_tool(args, _ctx=None):
    return ToolResult(True, "ok", {"echo": args["text"]})

ToolMetadata(
    name="my_tool",
    description="Example tool",
    args_schema={
        "type": "object",
        "required": ["text"],
        "properties": {"text": {"type": "string"}},
        "additionalProperties": False,
    },
    permissions=["diagnostics:read"],
)
```

## Testing

Lightweight (no Blender required):

```bash
python3 -m unittest \
  tests.test_registry \
  tests.test_contract \
  tests.test_tool_validation_harness \
  tests.test_validator
```

Blender smoke workflow:

```bash
blender --background --factory-startup --python /Users/agamairi/Downloads/dreamairi-blender-main/tests/smoke_test.py
```

Smoke script verifies:

1. import model
2. create rig action
3. keyframe pose
4. export GLB

## Example Prompts

- `Create tennis forehand animation for my selected character armature and export GLB.`
- `Duplicate the current backhand action, mirror it to opposite side, then assign it to the rig.`
- `Import character.glb, create an idle action with subtle arm swing, and export character_animated.glb.`
