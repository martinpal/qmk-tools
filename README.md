# QMK Tools

Collection of tools for QMK keyboards, including a real-time keyboard overlay GUI with GNOME Shell integration.

## Features

### Keyboard Overlay GUI
- **Real-time layer indicator** - Shows current active layer with color coding
- **DF(X) layer display** - Shows default layer when changed
- **Always-on-top window** - Stays visible while typing (10-second timer after losing focus)
- **Click-through transparent window** - Doesn't interfere with your workflow
- **GNOME Shell integration** - Layer indicator in the top bar
- **Corsair mouse monitor** - Tracks mouse battery and DPI changes

### Supported Keyboards
- Via-enabled QMK keyboards connected via USB
- Tested with Sofle and Corne (crkbd) keyboards

## Installation

### System Requirements

- Linux with X11 or Wayland
- GNOME Shell (optional, for top bar integration)
- Python 3.7+
- USB access (requires root or udev rules)

### Dependencies

Install all required system packages:

```bash
sudo apt install python3-pyqt5 python3-usb python3-hid python3-dbus python3-xlib
```

**Package descriptions:**
- `python3-pyqt5` - GUI framework for overlay window
- `python3-usb` - USB device communication
- `python3-hid` - HID device interface
- `python3-dbus` - D-Bus communication for GNOME integration
- `python3-xlib` - X11 window management (click-through, always-on-top)

**Alternative installation with pip:**
```bash
pip3 install PyQt5 pyusb hidapi python-dbus python-xlib
```

**Note:** Without `python3-xlib`, the overlay will still work but click-through and always-on-top features will be disabled.

### GNOME Shell Extension

Install the layer indicator extension:
```bash
cd /home/martin/source/qmk_tools
./install_gnome_extension.sh
```

Reload the extension after changes:
```bash
./reload_gnome_extension.sh
```

**⚠️ IMPORTANT:** After modifying extension code, you MUST restart GNOME Shell:
- **On X11**: Press `Alt+F2`, type `r`, press `Enter`
- **On Wayland**: Log out and log back in

The `reload_gnome_extension.sh` script will prompt you to do this and wait for you to restart before verifying the extension is working.

## Usage

### Run with sudo (required for USB access)

```bash
./run_overlay_with_sudo.sh
```

This script:
1. Starts the D-Bus bridge helper (runs as user)
2. Launches the overlay GUI with sudo
3. Preserves your D-Bus session for GNOME integration
4. Handles cleanup on exit

### Manual execution

If you prefer to run components separately:

1. Start the D-Bus bridge helper (as user):
```bash
python3 dbus_bridge_helper.py &
```

2. Run the overlay GUI (as root):
```bash
sudo DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
     XAUTHORITY="$XAUTHORITY" \
     DISPLAY="$DISPLAY" \
     python3 keyboard_overlay_gui.py
```

## Components

### keyboard_overlay_gui.py
Main overlay application that:
- Monitors QMK keyboards via USB HID
- Displays layer information in a transparent overlay window
- Communicates with GNOME Shell extension via D-Bus
- Tracks Corsair mouse status

### dbus_bridge_helper.py
Unix socket bridge that forwards layer updates from root process to user's D-Bus session. Required because the overlay runs as root for USB access but needs to communicate with user's GNOME Shell session.

### gnome-extension/
GNOME Shell extension that displays the current keyboard layer in the top bar with:
- Layer name display
- Color-coded background matching layer colors
- Rounded corners
- Fixed width (80px) for consistent appearance

### list_via_keyboards_usb.py
VIA protocol implementation for USB HID communication with QMK keyboards.

### corsair_mouse_monitor.py
Monitors Corsair wireless mice for battery and DPI status.

## Layer Colors

- **Base**: Gray (#787878)
- **Game**: Cyan (#00FFFF)
- **Lower**: Red (#FF3232)
- **Raise**: Blue (#0000FF)
- **Adjust**: Green (#50DC50)
- **Mouse**: Orange (#FFA500)
- **Extra**: Magenta (#FF00FF)

## Architecture

```
┌─────────────────────────────────────┐
│  GNOME Shell Extension              │
│  (displays layer in top bar)        │
└────────────┬────────────────────────┘
             │ D-Bus
┌────────────┴────────────────────────┐
│  dbus_bridge_helper.py              │
│  (runs as user, D-Bus bridge)       │
└────────────┬────────────────────────┘
             │ Unix Socket
┌────────────┴────────────────────────┐
│  keyboard_overlay_gui.py            │
│  (runs as root, USB access)         │
└────────────┬────────────────────────┘
             │ USB HID RAW
┌────────────┴────────────────────────┐
│  QMK Keyboard (VIA-enabled)         │
└─────────────────────────────────────┘
```

## Troubleshooting

### Overlay doesn't show
- Ensure you're running with sudo
- Check that your keyboard is VIA-enabled
- Verify USB permissions

### GNOME extension not working
- Check that dbus_bridge_helper.py is running
- Try reloading the extension: `./reload_gnome_extension.sh`
- Check GNOME Shell logs: `journalctl -f /usr/bin/gnome-shell`

### D-Bus errors
- Ensure DBUS_SESSION_BUS_ADDRESS environment variable is preserved when running with sudo
- Check that the Unix socket exists: `ls -l /tmp/qmk-dbus-bridge.sock`

## Development

### Testing the GNOME indicator
```bash
python3 test_gnome_indicator.py
```

This sends test layer updates to verify the GNOME Shell extension is working.

## License

See individual source files for license information.

## Credits

- QMK Firmware: https://qmk.fm/
- VIA: https://www.caniusevia.com/
