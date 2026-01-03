#!/bin/bash
# Install QMK Layer Indicator GNOME Shell Extension

set -e

EXTENSION_DIR="$HOME/.local/share/gnome-shell/extensions/qmk-layer-indicator@local"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing QMK Layer Indicator GNOME Shell Extension..."

# Create extension directory
mkdir -p "$EXTENSION_DIR"

# Copy extension files
cp "$SCRIPT_DIR/gnome-extension/extension.js" "$EXTENSION_DIR/"
cp "$SCRIPT_DIR/gnome-extension/metadata.json" "$EXTENSION_DIR/"

echo "Extension files installed to: $EXTENSION_DIR"
echo ""
echo "To activate the extension:"
echo "1. Log out and log back in (or press Alt+F2, type 'r', press Enter on Xorg)"
echo "2. Run: gnome-extensions enable qmk-layer-indicator@local"
echo ""
echo "Or simply restart your session and the extension will be available."
