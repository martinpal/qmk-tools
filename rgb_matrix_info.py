#!/usr/bin/env python3
"""Describe the keyboard's running RGB matrix effect for the overlay.

The effect table lives in rgb_matrix_effects.json (next to this file) because
the effect numbers follow the enum order of the effects enabled in the
firmware and change when that list changes.
"""

import json
import os
from typing import Dict, Optional, Tuple

DEFAULT_TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rgb_matrix_effects.json")


def load_table(path: str = DEFAULT_TABLE) -> Tuple[int, Dict[int, str]]:
    """Return (max_brightness, {effect number: enum name}); empty table on any error."""
    try:
        with open(path) as f:
            data = json.load(f)
        names = {int(k): v for k, v in data.get("effects", {}).items()}
        return int(data.get("max_brightness", 255)), names
    except (OSError, ValueError, TypeError) as e:
        print(f"Warning: could not read RGB effect table {path}: {e}")
        return 255, {}


def humanize(name: str) -> str:
    """CYCLE_PINWHEEL -> Cycle Pinwheel"""
    return name.replace("_", " ").title()


def real_value(brightness_byte: int, max_brightness: int) -> int:
    """VIA reports V * 255 / RGB_MATRIX_MAXIMUM_BRIGHTNESS; return V on QMK's 0-255 scale."""
    return round(brightness_byte * max_brightness / 255)


def format_state(state: Optional[dict], max_brightness: int, names: Dict[int, str]) -> str:
    """One-line description, or '' when the keyboard did not answer.

    state keys: effect, speed, hue, sat, brightness (raw VIA byte).
    """
    if not state:
        return ""
    effect = state["effect"]
    if effect == 0:
        return "RGB off"
    name = humanize(names[effect]) if effect in names else f"effect {effect}"
    value = real_value(state["brightness"], max_brightness)
    text = f"{name} · speed {state['speed']} · H {state['hue']} S {state['sat']} V {value}"
    if value == 0:
        text += " (dimmed)"
    return text
