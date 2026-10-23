#!/usr/bin/env python3
"""Short overlay labels for QMK keycode names that are too long or cryptic to show as-is."""

QK_LABELS = {
    "QK_BOOT": "BOOTLDR",          # jump to bootloader
    "QK_REBOOT": "REBOOT",
    "QK_CLEAR_EEPROM": "EE CLR",   # erases the EEPROM (keymap, macros, RGB settings)
    "QK_DEBUG_TOGGLE": "DEBUG",
    "QK_MAKE": "MAKE",
    "QK_GESC": "ESC~",
}


def short_label(name: str) -> str:
    """Return the short label for `name`, or `name` itself when there is none."""
    return QK_LABELS.get(name, name)


# Keys that reboot the half or erase its settings get a coloured border in the overlay.
# keycode -> (red, green, blue)
DANGER_RED = (255, 0, 0)
DANGER_ORANGE = (255, 190, 0)
DANGER_BORDERS = {
    0x7C03: DANGER_RED,     # QK_CLEAR_EEPROM
    0x7C00: DANGER_ORANGE,  # QK_BOOT
    0x7C01: DANGER_ORANGE,  # QK_REBOOT
}


def danger_border(keycode: int):
    """(r, g, b) of the warning border for a dangerous keycode, else None."""
    return DANGER_BORDERS.get(keycode)
