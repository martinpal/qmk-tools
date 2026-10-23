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


# Short overlay labels for the RGB keycodes (offset from 0x7800, as in QMK's keycode map).
# 0x20-0x2A are the underglow (rgblight) keys, 0x40-0x4E the RGB matrix keys.
RGB_KEY_LABELS = {
    0x20: "RGB\u23fb",   # UG_TOGG
    0x21: "RGB\u25b6",   # UG_NEXT
    0x22: "RGB\u25c0",   # UG_PREV
    0x23: "H+", 0x24: "H-",     # UG_HUEU / UG_HUED
    0x25: "S+", 0x26: "S-",     # UG_SATU / UG_SATD
    0x27: "V+", 0x28: "V-",     # UG_VALU / UG_VALD
    0x29: "SPD+", 0x2A: "SPD-",  # UG_SPDU / UG_SPDD
    0x40: "RGB on",   # RM_ON
    0x41: "RGB off",  # RM_OFF
    0x42: "RGB\u23fb",   # RM_TOGG
    0x43: "RGB\u25b6",   # RM_NEXT
    0x44: "RGB\u25c0",   # RM_PREV
    0x45: "H+", 0x46: "H-",     # RM_HUEU / RM_HUED
    0x47: "S+", 0x48: "S-",     # RM_SATU / RM_SATD
    0x49: "V+", 0x4A: "V-",     # RM_VALU / RM_VALD
    0x4B: "SPD+", 0x4C: "SPD-",  # RM_SPDU / RM_SPDD
    0x4D: "FLG+", 0x4E: "FLG-",  # RM_FLGN / RM_FLGP
}


def rgb_key_label(name: str) -> Optional[str]:
    """Short label for a key name of the form "RGB(0xNN)", else None."""
    if not (name.startswith("RGB(0x") and name.endswith(")")):
        return None
    try:
        return RGB_KEY_LABELS.get(int(name[6:-1], 16))
    except ValueError:
        return None
