"""Style presets for low-poly generation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class StylePreset:
    name: str
    poly_budget: int
    bevel_range: Tuple[float, float]
    flat_shading: bool
    palette: Dict[str, Tuple[float, float, float, float]]


STYLE_PRESETS: Dict[str, StylePreset] = {
    "LOW_POLY_CLEAN": StylePreset(
        name="Low-poly clean",
        poly_budget=800,
        bevel_range=(0.01, 0.03),
        flat_shading=True,
        palette={
            "Base": (0.8, 0.8, 0.8, 1.0),
            "Accent": (0.8, 0.1, 0.1, 1.0),
            "Dark": (0.2, 0.2, 0.2, 1.0),
        },
    ),
    "LOW_POLY_CHUNKY": StylePreset(
        name="Low-poly chunky",
        poly_budget=600,
        bevel_range=(0.03, 0.06),
        flat_shading=True,
        palette={
            "Base": (0.75, 0.7, 0.6, 1.0),
            "Accent": (0.9, 0.4, 0.1, 1.0),
            "Dark": (0.15, 0.15, 0.2, 1.0),
        },
    ),
    "LOW_POLY_TOY": StylePreset(
        name="Low-poly toy",
        poly_budget=900,
        bevel_range=(0.02, 0.05),
        flat_shading=True,
        palette={
            "Base": (0.9, 0.9, 0.95, 1.0),
            "Accent": (0.95, 0.1, 0.2, 1.0),
            "Dark": (0.1, 0.2, 0.4, 1.0),
        },
    ),
}

STYLE_PRESET_ITEMS: List[Tuple[str, str, str]] = [
    (key, preset.name, "") for key, preset in STYLE_PRESETS.items()
]


def get_style_preset(key: str) -> StylePreset:
    return STYLE_PRESETS.get(key, STYLE_PRESETS["LOW_POLY_CLEAN"])
