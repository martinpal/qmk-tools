#!/bin/bash
# Wrapper script to run keyboard_overlay_gui.py with sudo while preserving user's D-Bus session
# Also starts the D-Bus bridge helper if not already running

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRIDGE_HELPER="$SCRIPT_DIR/dbus_bridge_helper.py"
BRIDGE_PID=""

# Trap to kill bridge helper on exit
cleanup() {
    if [ -n "$BRIDGE_PID" ]; then
        echo "Stopping D-Bus bridge helper (PID: $BRIDGE_PID)..."
        kill $BRIDGE_PID 2>/dev/null
    fi
}

trap cleanup EXIT INT TERM

# Check if bridge helper is already running
if pgrep -f "dbus_bridge_helper.py" > /dev/null; then
    echo "D-Bus bridge helper is already running"
else
    # Start bridge helper in background (as user, not root)
    echo "Starting D-Bus bridge helper..."
    python3 "$BRIDGE_HELPER" &
    BRIDGE_PID=$!
    sleep 1
fi

# Preserve user's environment variables needed for D-Bus
USER_DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS"
USER_XAUTHORITY="$XAUTHORITY"
USER_DISPLAY="$DISPLAY"

# Run with sudo but preserve necessary environment
sudo \
    DBUS_SESSION_BUS_ADDRESS="$USER_DBUS_SESSION_BUS_ADDRESS" \
    XAUTHORITY="$USER_XAUTHORITY" \
    DISPLAY="$USER_DISPLAY" \
    python3 "$SCRIPT_DIR/keyboard_overlay_gui.py" "$@"


