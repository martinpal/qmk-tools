#!/usr/bin/env python3
"""Decoding of layer-switching keycodes for the overlay's key styling.

Layer keys get a coloured border (in the colour of the layer they lead to);
the background colour stays reserved for modifiers.
"""

from typing import NamedTuple, Optional

from layer_tap import is_layer_tap, layer_of

QK_MOMENTARY, QK_DEF_LAYER, QK_TOGGLE_LAYER = 0x5220, 0x5240, 0x5260

# kind -> CSS border style
BORDER_STYLES = {"MO": "solid", "LT": "solid", "TG": "dotted", "DF": "dashed"}


class LayerKey(NamedTuple):
    kind: str                # "MO", "LT", "TG" or "DF"
    layer: int
    tap_keycode: Optional[int]  # LT only: the key sent on a tap


def decode_layer_key(keycode: int) -> Optional[LayerKey]:
    """The layer a keycode leads to, or None for any other key."""
    if is_layer_tap(keycode):
        return LayerKey("LT", layer_of(keycode), keycode & 0xFF)
    for kind, base in (("MO", QK_MOMENTARY), ("DF", QK_DEF_LAYER), ("TG", QK_TOGGLE_LAYER)):
        if base <= keycode <= base + 0x1F:
            return LayerKey(kind, keycode & 0x1F, None)
    return None
