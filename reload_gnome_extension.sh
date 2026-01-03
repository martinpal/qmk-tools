#!/bin/bash
# Reload GNOME Shell QMK Layer Indicator Extension

set -e

EXTENSION_UUID="qmk-layer-indicator@local"
EXTENSION_DIR="$HOME/.local/share/gnome-shell/extensions/$EXTENSION_UUID"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/gnome-extension"

echo "Source directory: $SOURCE_DIR"

# Validate source files exist
if [ ! -f "$SOURCE_DIR/extension.js" ]; then
    echo "ERROR: Source file not found: $SOURCE_DIR/extension.js"
    exit 1
fi

# Ensure extension directory exists
mkdir -p "$EXTENSION_DIR"

echo "Updating QMK Layer Indicator extension..."

# Disable extension
gdbus call --session --dest org.gnome.Shell.Extensions --object-path /org/gnome/Shell/Extensions \
    --method org.gnome.Shell.Extensions.DisableExtension "$EXTENSION_UUID" > /dev/null 2>&1 || true
echo "✓ Extension disabled"

# Copy files (overwrite existing)
cp -v "$SOURCE_DIR/extension.js" "$EXTENSION_DIR/"
cp -v "$SOURCE_DIR/metadata.json" "$EXTENSION_DIR/"
echo "✓ Files copied"

echo ""
echo "=========================================="
echo "GNOME Shell must be restarted for changes to take effect."
echo ""
echo "On X11: Press Alt+F2, type 'r', press Enter"
echo "On Wayland: Log out and log back in"
echo ""
read -p "Press Enter after restarting GNOME Shell to verify D-Bus registration..."
echo ""

# Enable extension
gdbus call --session --dest org.gnome.Shell.Extensions --object-path /org/gnome/Shell/Extensions \
    --method org.gnome.Shell.Extensions.EnableExtension "$EXTENSION_UUID" > /dev/null
echo "✓ Extension enabled"
sleep 2

# Check if D-Bus service is registered
if gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.ListNames | grep -q 'com.qmk.LayerIndicator'; then
    echo "✓ SUCCESS: D-Bus service 'com.qmk.LayerIndicator' is registered!"
else
    echo "✗ FAILED: D-Bus service not registered"
    echo ""
    echo "Extension state:"
    echo "================"
    gdbus call --session --dest org.gnome.Shell.Extensions --object-path /org/gnome/Shell/Extensions \
        --method org.gnome.Shell.Extensions.GetExtensionInfo "$EXTENSION_UUID" 2>&1 | grep -Eo "'(state|error|enabled)'[^,}]+" || echo "(extension not found)"
    exit 1
fi
