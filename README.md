# QMK Tools

Collection of tools for QMK keyboards, including a real-time keyboard overlay GUI with GNOME Shell integration.

## Features

### Keyboard Overlay GUI
- **Real-time layer indicator** - Shows current active layer with color coding
- **DF(X) layer display** - Shows default layer when changed
- **Always-on-top window** - Stays visible while typing (10-second timer after losing focus)
- **Click-through transparent window** - Doesn't interfere with your workflow
- **GNOME Shell integration** - Layer indicator in the top bar
- **Boblight integration** - Ambient LED lighting feedback based on keyboard layer (optional)
- **Hue bridge integration** - Dynamic LED brightness scaling based on Philips Hue light (optional)
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

**Python virtual environment (recommended):**

The `run_overlay_with_sudo.sh` script automatically creates and manages a Python virtual environment. You only need to install the venv package:

```bash
sudo apt install python3-venv
```

On first run, the script will automatically:
1. Create a `venv/` directory as your user (not root)
2. Install all dependencies from `requirements.txt`
3. Use the venv's Python for all subsequent runs

**System packages (alternative approach):**

If you prefer system-wide installation instead of venv:

```bash
sudo apt install python3-pyqt5 python3-usb python3-hid python3-dbus python3-xlib
```

**Package descriptions:**
- `python3-pyqt5` - GUI framework for overlay window
- `python3-usb` - USB device communication
- `python3-hid` - HID device interface
- `python3-dbus` - D-Bus communication for GNOME integration
- `python3-xlib` - X11 window management (click-through, always-on-top)

**For Hue bridge integration (optional):**

With venv (automatic via script):
```bash
# Already included in requirements.txt - installed automatically
./run_overlay_with_sudo.sh
```

Without venv (manual installation):
```bash
pip3 install phue requests
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

### Boblight Integration (Optional)

Enable ambient LED lighting that changes color based on your keyboard layer:

```bash
./run_overlay_with_sudo.sh  # Edit script to add --boblight arguments
# OR
sudo python3 keyboard_overlay_gui.py --boblight --boblight-leds "0,1,2,3,4,5"
```

**Features:**
- Base layer (0) doesn't affect boblight - leaves control to boblight-X11
- Other layers set LEDs to layer-specific colors
- Configurable LED selection (e.g., top edge only)
- Automatic reconnection if boblightd restarts

See [BOBLIGHT_INTEGRATION.md](BOBLIGHT_INTEGRATION.md) for detailed configuration and usage.

### Hue Bridge Integration (Optional)

Dynamically scale boblight LED brightness based on Philips Hue light brightness **and** solar elevation (time of day):

```bash
sudo python3 keyboard_overlay_gui.py --boblight --hue
```

**How it works:**
- Uses **max(Hue brightness, solar brightness)** - whichever is brighter wins
- **Solar brightness**: Calculated from sun position (elevation angle)
  - Below horizon (night) → minimum brightness (25%)
  - At horizon (sunrise/sunset) → minimum brightness
  - Peak elevation (~60° at noon in Brno) → 100% brightness
  - Linear curve following sun elevation
- **Hue brightness**: Manual control via Hue light dimming
- **Combined**: Gives natural daylight curve with manual override capability

**First-time setup:**
1. Install phue: `pip3 install phue requests`
2. Run with `--hue` flag
3. Press the button on your Hue bridge when prompted
4. Credentials saved to `~/.python_hue` for future use

**Command-line options:**
```bash
# Basic (auto-discover bridge, solar enabled for Brno, CZ)
sudo python3 keyboard_overlay_gui.py --boblight --hue

# Manual bridge IP
sudo python3 keyboard_overlay_gui.py --boblight --hue --hue-bridge 192.168.1.123

# Monitor specific light
sudo python3 keyboard_overlay_gui.py --boblight --hue --hue-light "Living Room"

# Custom minimum brightness (default: 0.25 = 25%)
sudo python3 keyboard_overlay_gui.py --boblight --hue --hue-min-brightness 0.10

# Custom location (latitude/longitude)
sudo python3 keyboard_overlay_gui.py --boblight --hue --hue-latitude 50.08 --hue-longitude 14.43

# Disable solar brightness (use only Hue light)
sudo python3 keyboard_overlay_gui.py --boblight --hue --hue-no-solar

# Adjust polling frequency (default: 5.0 seconds)
sudo python3 keyboard_overlay_gui.py --boblight --hue --hue-poll-interval 3.0
```

**Features:**
- Auto-discovery of Hue bridge (or manual IP configuration)
- Solar brightness based on sun elevation (automatic sunrise/sunset)
- Combines Hue and solar brightness using max() - natural daylight curve with manual override
- Polls Hue bridge every 5 seconds (configurable)
- Graceful degradation to 100% brightness if bridge unavailable
- Automatic reconnection on connection loss
- Thread-safe brightness scaling

**Example scenarios:**
- Night, Hue off → 25% (minimum)
- Night, Hue at 100% → 100% (Hue wins)
- Daytime (noon), Hue off → ~100% (solar wins)
- Daytime (noon), Hue at 50% → ~100% (solar wins)
- Sunrise/sunset, Hue off → 25% (minimum)
- Sunrise/sunset, Hue at 100% → 100% (Hue wins)

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
