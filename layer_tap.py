#!/usr/bin/env python3
"""Layer-tap keys (LT(layer, kc)) as seen from the host.

The firmware decides between tap and hold; the overlay only sees the matrix, so
it guesses the same way the firmware's settings do: the layer counts as held
once the key has been down for the tapping term, or as soon as another key is
pressed while it is down (permissive hold). A quick tap never changes layer.
"""

from typing import Dict, List, Optional, Tuple

QK_LAYER_TAP, QK_LAYER_TAP_MAX = 0x4000, 0x4FFF
TAPPING_TERM = 0.220  # seconds, the firmware's TAPPING_TERM


def is_layer_tap(keycode: int) -> bool:
    return QK_LAYER_TAP <= keycode <= QK_LAYER_TAP_MAX


def layer_of(keycode: int) -> int:
    return (keycode >> 8) & 0x0F


class LayerTapTracker:
    def __init__(self, term: float = TAPPING_TERM):
        self.term = term
        self.pending: Dict[Tuple[int, int], Tuple[int, float]] = {}  # key -> (layer, time pressed)
        self.holding: Dict[Tuple[int, int], int] = {}                # key -> layer now held

    def reset(self) -> None:
        self.pending.clear()
        self.holding.clear()

    def _promote(self, keys) -> List[int]:
        layers = []
        for key in keys:
            layer, _ = self.pending.pop(key)
            self.holding[key] = layer
            layers.append(layer)
        return layers

    def before_press(self) -> List[int]:
        """Another key goes down: pending layer-taps become holds. Returns the layers to activate."""
        return self._promote(list(self.pending))

    def press(self, key: Tuple[int, int], keycode: int, now: float) -> None:
        """Register a layer-tap key press (call after before_press)."""
        self.pending[key] = (layer_of(keycode), now)

    def release(self, key: Tuple[int, int]) -> Optional[int]:
        """Layer to deactivate when a held layer-tap is released; None for a tap or another key."""
        self.pending.pop(key, None)
        return self.holding.pop(key, None)

    def tick(self, now: float) -> List[int]:
        """Layer-taps held past the tapping term. Returns the layers to activate."""
        return self._promote([k for k, (_, t) in self.pending.items() if now - t >= self.term])
