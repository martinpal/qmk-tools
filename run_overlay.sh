#!/bin/bash
# Start the overlay as the current user (no sudo; needs the udev rule from the README).
# Used by ~/.config/autostart/qmk-overlay.desktop. Output goes to overlay.log.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# The overlay connects to the GNOME Shell extension once at start-up, so wait
# (up to 60 s, then start anyway) until the extension owns its D-Bus name.
for _ in $(seq 1 120); do
    if [ "$(gdbus call --session --dest org.freedesktop.DBus \
            --object-path /org/freedesktop/DBus \
            --method org.freedesktop.DBus.NameHasOwner com.qmk.LayerIndicator 2>/dev/null)" = "(true,)" ]; then
        break
    fi
    sleep 0.5
done

exec "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/keyboard_overlay_gui.py" "$@" >> "$SCRIPT_DIR/overlay.log" 2>&1
