#!/bin/bash
# Wrapper script to run keyboard_overlay_gui.py with sudo while preserving user's D-Bus session
# Also starts the D-Bus bridge helper if not already running
# Automatically creates and uses a Python virtual environment

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRIDGE_HELPER="$SCRIPT_DIR/dbus_bridge_helper.py"
VENV_DIR="$SCRIPT_DIR/venv"
BRIDGE_PID=""

# Create virtual environment if it doesn't exist (as unprivileged user)
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"

    if [ $? -ne 0 ]; then
        echo "Error: Failed to create virtual environment"
        echo "Install python3-venv: sudo apt install python3-venv"
        exit 1
    fi

    echo "Installing dependencies into venv..."
    "$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

    if [ $? -ne 0 ]; then
        echo "Error: Failed to install dependencies"
        exit 1
    fi

    echo "Virtual environment created and configured successfully"
fi

# Use venv's Python interpreter
PYTHON_BIN="$VENV_DIR/bin/python3"

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
    # Start bridge helper in background (as user, not root, using venv)
    echo "Starting D-Bus bridge helper..."
    "$PYTHON_BIN" "$BRIDGE_HELPER" &
    BRIDGE_PID=$!
    sleep 1
fi

# Preserve user's environment variables needed for D-Bus
USER_DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS"
USER_XAUTHORITY="$XAUTHORITY"
USER_DISPLAY="$DISPLAY"

# Run with sudo but preserve necessary environment, using venv's Python
sudo \
    DBUS_SESSION_BUS_ADDRESS="$USER_DBUS_SESSION_BUS_ADDRESS" \
    XAUTHORITY="$USER_XAUTHORITY" \
    DISPLAY="$USER_DISPLAY" \
    "$PYTHON_BIN" "$SCRIPT_DIR/keyboard_overlay_gui.py" "$@"


