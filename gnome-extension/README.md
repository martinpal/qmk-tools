# QMK Layer Indicator GNOME Shell Extension

This extension displays the current QMK keyboard layer in the GNOME Shell top bar with a colored background.

## Installation

```bash
./install_gnome_extension.sh
```

Then either:
- Log out and log back in, OR
- Press Alt+F2, type 'r', press Enter (Xorg only)

Finally, enable the extension:
```bash
gnome-extensions enable qmk-layer-indicator@local
```

## Usage

The extension works automatically with `keyboard_overlay_gui.py`. When you switch layers on your keyboard, the indicator in the top bar will update to show:
- Current layer name (e.g., "Base", "Lower", "Raise")
- Layer-specific background color

## Files

- `extension.js` - Main extension code
- `metadata.json` - Extension metadata
- `install_gnome_extension.sh` - Installation script

## Requirements

- GNOME Shell 45 or 46
- Python dbus library (`pip install dbus-python`)
