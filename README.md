# QMK Tools

Collection of tools for QMK keyboards, including a real-time keyboard overlay GUI with GNOME Shell integration.

## Features

### Keyboard Overlay GUI
- **Real-time layer indicator** - Shows current active layer with color coding
- **DF(X) layer display** - Shows default layer when changed
- **RGB matrix effect line** - Shows the running effect and its parameters, e.g. `Cycle Pinwheel · speed 128 · H 200 S 255 V 120` (see [RGB Matrix Effect Line](#rgb-matrix-effect-line))
- **Always-on-top window** - Stays visible while typing (10-second timer after losing focus)
- **Click-through transparent window** - Doesn't interfere with your workflow
- **GNOME Shell integration** - Layer indicator in the top bar
- **Boblight integration** - Ambient LED lighting feedback based on keyboard layer (optional)
- **Home Assistant integration** - Dynamic LED brightness scaling based on a Home Assistant light (optional)
- **Home Assistant light color sync** - Sync a Home Assistant light's color to the active keyboard layer (optional)
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

**For Home Assistant integration (optional):**

With venv (automatic via script):
```bash
# Already included in requirements.txt - installed automatically
./run_overlay_with_sudo.sh
```

Without venv (manual installation):
```bash
pip3 install requests astral
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

### Home Assistant Integration (Optional)

Dynamically scale boblight LED brightness based on a Home Assistant light entity's brightness **and** solar elevation (time of day):

```bash
sudo python3 keyboard_overlay_gui.py --boblight --ha
```

**How it works:**
- Uses **max(HA brightness, solar brightness)** - whichever is brighter wins
- **Solar brightness**: Calculated from sun position (elevation angle)
  - Below horizon (night) → minimum brightness (25%)
  - At horizon (sunrise/sunset) → minimum brightness
  - Peak elevation (~60° at noon in Brno) → 100% brightness
  - Linear curve following sun elevation
- **HA brightness**: Manual control via Home Assistant light dimming
- **Combined**: Gives natural daylight curve with manual override capability

**First-time setup:**
1. Install dependencies: `pip3 install requests astral`
2. Create a long-lived access token in Home Assistant:
   - Go to your profile (bottom-left of HA sidebar)
   - Scroll to **Long-Lived Access Tokens**
   - Click **Create Token**, give it a name, copy the token
3. Run with `--ha` flag, passing the token via `--ha-token` or `HASS_TOKEN` env var:
   ```bash
   # Option A: command-line argument
   sudo python3 keyboard_overlay_gui.py --boblight --ha --ha-token "eyJhbGciOi..."

   # Option B: environment variable (recommended)
   export HASS_TOKEN="eyJhbGciOi..."
   sudo python3 keyboard_overlay_gui.py --boblight --ha
   ```

**Command-line options:**
```bash
# Basic (default URL: http://homeassistant.local:8123)
sudo python3 keyboard_overlay_gui.py --boblight --ha

# Custom Home Assistant URL
sudo python3 keyboard_overlay_gui.py --boblight --ha --ha-url http://192.168.1.50:8123

# Monitor specific light entity
sudo python3 keyboard_overlay_gui.py --boblight --ha --ha-entity light.living_room

# Custom minimum brightness (default: 0.25 = 25%)
sudo python3 keyboard_overlay_gui.py --boblight --ha --ha-min-brightness 0.10

# Custom location (latitude/longitude)
sudo python3 keyboard_overlay_gui.py --boblight --ha --ha-latitude 50.08 --ha-longitude 14.43

# Disable solar brightness (use only Home Assistant light)
sudo python3 keyboard_overlay_gui.py --boblight --ha --ha-no-solar

# Adjust polling frequency (default: 5.0 seconds)
sudo python3 keyboard_overlay_gui.py --boblight --ha --ha-poll-interval 3.0
```

**Features:**
- Uses Home Assistant REST API to poll light state
- Solar brightness based on sun elevation (automatic sunrise/sunset)
- Combines HA and solar brightness using max() - natural daylight curve with manual override
- Polls Home Assistant every 5 seconds (configurable)
- Graceful degradation to 100% brightness if Home Assistant unavailable
- Automatic reconnection on connection loss
- Thread-safe brightness scaling

**Example scenarios:**
- Night, light off → 25% (minimum)
- Night, light at 100% → 100% (HA wins)
- Daytime (noon), light off → ~100% (solar wins)
- Daytime (noon), light at 50% → ~100% (solar wins)
- Sunrise/sunset, light off → 25% (minimum)
- Sunrise/sunset, light at 100% → 100% (HA wins)

### Home Assistant Light Color Sync (Optional)

Sync a Home Assistant light's color to the active keyboard layer color. When a non-base layer is activated, the light is set to that layer's color. When returning to the base layer, the light's previous state (on/off, brightness, color) is restored.

Can use the same light as the brightness monitoring entity, or a different light.

```yaml
# In config.yaml:
home_assistant:
  color:
    enabled: true
    # entity: light.bedroom_lamp  # defaults to the entity above
```

Or via command line:
```bash
# Same light as brightness monitoring
sudo python3 keyboard_overlay_gui.py --boblight --ha --ha-color

# Different light for color
sudo python3 keyboard_overlay_gui.py --boblight --ha --ha-color --ha-color-entity light.bedroom_lamp
```

**How it works:**
- On first non-base layer activation: captures the light's current state (on/off, brightness, RGB color or color temp)
- Sets the light to the layer's color (using `boblight_colors` for fully saturated values)
- On return to base layer: restores the saved state (turns off if it was off, restores color and brightness if it was on)
- If layer changes between non-base layers, the saved state is preserved (only captured once per base-layer excursion)

### Brightness Control Keys (Optional)

Use specific keys, on specific layers, as brightness up/down controls for one or more Home Assistant lights. Requires the base Home Assistant integration (`--ha`) to be enabled.

```yaml
# In config.yaml:
home_assistant:
  enabled: true
  brightness_keys:
    - layer: 2
      row: 0
      col: 0
      entity: light.bedroom_lamp
      direction: up
      step: 10
    - layer: 2
      row: 0
      col: 1
      entity: light.bedroom_lamp
      direction: down
      step: 10
```

**Finding a key's row/col:**
```bash
python3 list_via_keyboards_usb.py --monitor
```
Press the physical key you want to bind - it prints `Key [row,col]: PRESSED`. On split keyboards the row printed already accounts for which half the key is on (matches what `row` should be in the config).

**How it works:**
- Each binding matches a physical key (`row`, `col`) only while a given `layer` is active
- Tapping the key sends one relative brightness step (`brightness_step_pct` via Home Assistant), so it works whether the light is dim, bright, or off
- Holding the key repeats the step every `repeat_interval` seconds (default: 0.2s) until released, like a real dimmer
- Multiple bindings can target different entities, layers, or keys independently
- `entity` accepts a single entity_id or a list, to step several lights together from one key
- `entity` defaults to the `home_assistant.entity` monitored light if omitted

**Interaction with layer color sync:** if you're using the MQTT-based "QMK Layer Light Sync" HA automation (see [Layer Color Sync](#home-assistant-light-color-sync-optional) below) to tint a light with the active layer's color, the first brightness step after entering a layer restores that light to its pre-layer-color state (via the automation's own `scene.qmk_light_snapshot` / `input_boolean.qmk_override_active` bookkeeping) before applying the step. This gives immediate visual feedback on the light's real color/brightness instead of dimming it while still tinted, and it also clears the override flag so returning to the base layer doesn't undo the brightness change you just made.

### Key Usage Heatmap (Optional)

Logs every key press/release (timestamp in ms, row, col, active layer) to an
append-only binary file, one file per day that rolls over at 05:00 local time
(`heatmap_data/heatmap-YYYY-MM-DD.bin`, 16 bytes per event, mode 600).
Disabled by default - enable with `heatmap.enabled: true` (see
`config.sample.yaml`).

**Privacy:** a timestamped per-key log can reconstruct what you typed,
including passwords.

Summarize with `heatmap_report.py`:

```bash
./heatmap_report.py                              # everything
./heatmap_report.py --from 7d                    # last 7 days
./heatmap_report.py --from 2026-10-01 --to 2026-10-08 --layer 0
./heatmap_report.py --csv > keys.csv
```

### Habit Sounds (Optional)

Audible feedback for retraining muscle memory, for example after moving Esc and Backspace to the thumb cluster:

- **Old pinky keys:** a harsh, low buzz when a key press resolves to Esc, Grave-Esc, Grave (`` ` ``/`~`, as on the Lower layer's old Esc position), Backspace or Delete in one of the two outer columns of either half (thumb row excluded). It looks at the keymap read from the keyboard, so it follows the layer you are on. For example Backspace on the Raise layer's right pinky key triggers it, the thumb Backspace does not.
- **Top row:** a short, mild blip when a key in the top row of either half (not a `KC_NO` key) is pressed on a layer in `top_row_layers` (default base, Lower and Raise: 0, 2, 3).
- **Cooldown:** each kind plays at most once per `cooldown` seconds (default 5), so a burst of presses makes one sound.

Enable it in `config.yaml` (see `config.sample.yaml`):

```yaml
habit_sounds:
  enabled: true
```

The overlay runs as root under sudo while the sound server belongs to you, so it first runs the player (`paplay`, `pw-play` or `aplay`, whichever is installed first) as root with `PULSE_SERVER` and `XDG_RUNTIME_DIR` pointing at your session (`SUDO_UID`), and if that fails as you through `sudo -n -u`. Every trigger is logged as `[HABIT] old_key at row R, col C, layer L`, and a failing player prints its exit code and error. The two short tones are generated at start-up into a temporary directory.

### RGB Matrix Effect Line

At the bottom of the overlay window it shows the keyboard's running RGB matrix effect, read over the VIA protocol (`CMD_CUSTOM_GET_VALUE`, RGB matrix channel): effect name, effect speed, hue, saturation and value.

- **Polling:** one value is read every 0.25 s by the keyboard monitor thread (the same thread and USB endpoint as the matrix polling), so all four values refresh about once a second and a read never stalls the matrix scan for more than one USB round trip. If a read fails (for example firmware without an RGB matrix) the line is hidden and the overlay retries after 10 s.
- **Value (V):** VIA reports `V * 255 / RGB_MATRIX_MAXIMUM_BRIGHTNESS`. The overlay converts it back to QMK's 0-255 scale (`byte * max / 255`), using `max_brightness` from `rgb_matrix_effects.json` (120 for the current firmware).
- **Off / dimmed:** effect 0 is shown as `RGB off`. An effect with `V 0` is shown with `(dimmed)`: the matrix is still enabled (indicators and reactive effects stay lit), only the base brightness is zero, which is what the firmware's own RGB toggle key does.
- **Hue/saturation** are only meaningful for effects that use them (e.g. Cycle Pinwheel ignores hue).
- **Key labels:** the RGB keys on a layer are shown with short labels (`RGB⏻`, `RGB▶`, `RGB◀`, `H+`/`H-`, `S+`/`S-`, `V+`/`V-`, `SPD+`/`SPD-`, ...) for both RGB matrix keys (`RM_*`) and underglow keys (`UG_*`); the table is `RGB_KEY_LABELS` in `rgb_matrix_info.py`.
- **Effect names:** none are stored in the overlay. At start-up and after a reconnect it asks the firmware (VIA raw command `0x51`: byte 1 = 0 gives the effect count, byte 1 = 2 plus an effect number gives the display name, e.g. `Game of Life`) and caches the result, because the effect list changes with the firmware. If the firmware does not know the command (reply byte 0 = `0xFF`) or returns an empty name, the line shows `effect N`.

The firmware needs VIA enabled with the RGB matrix channel. The exact values returned by real hardware have not yet been checked against this documentation.

### Keyboard sleep/wake API

Only the overlay can talk to the keyboard over USB (it claims the VIA interface, and the VIA protocol has no request ids), so other programs ask the overlay to send the firmware's sleep/wake command through a small HTTP API. It listens on `127.0.0.1:8765` only (port: `api.port` in `config.yaml` or `--api-port`; disable with `api.enabled: false` or `--no-api`), has **no authentication**, and rejects requests that carry an `Origin` header or a `Host` other than `127.0.0.1`/`localhost`, so a web page cannot trigger it.

| Request | Meaning |
|---|---|
| `POST /api/v1/keyboard/sleep` | put the keyboard to sleep (idempotent) |
| `POST /api/v1/keyboard/wake` | wake it (idempotent) |
| `GET /api/v1/keyboard` | query the state |
| `GET /api/v1/health` | the overlay is alive |

```bash
curl -X POST http://127.0.0.1:8765/api/v1/keyboard/sleep   # {"keyboard": "connected", "state": "asleep"}
curl http://127.0.0.1:8765/api/v1/keyboard                  # {"keyboard": "connected", "state": "awake"}
```

Errors are `{"error": "..."}` with: `501 unsupported` (firmware without the sleep command), `503 keyboard_disconnected`, `504 timeout` (no USB answer within 2 s), `403 forbidden` (Origin/Host check), `404`/`405` (unknown path/method), `400 bad_request`.

- **State:** read from the keyboard (command `0x50`, byte 1 = 1 sleep, 0 wake, 2 query; the reply carries the state after the command). The overlay queries at startup and after a reconnect.
- **While the keyboard sleeps** the overlay stops polling the matrix and the RGB effect and only queries the state about once a second, so it notices a wake by key press or encoder turn within about a second. The bottom label shows "Keyboard asleep". The key that wakes the keyboard is swallowed by the firmware and is not logged by the heatmap; the overlay takes over the current matrix state on waking instead of reporting held keys as new presses.
- **Threading:** HTTP handlers never touch USB; they queue the request for the keyboard monitor thread, which runs it between matrix polls.
- The firmware side (`users/dontpanic/host_sleep.c`) was not yet flashed when this was written, so the whole path is untested against real hardware.

### Key styles in the overlay

- **Background colour:** modifiers only. Mod-Tap keys and plain modifier combinations are tinted by modifier (Ctrl red, Alt blue, Shift green, Super yellow).
- **Border colour:** layer keys (`MO`, `LT`, `TG`, `DF`), in the colour of the layer the key leads to (Lower red, Raise blue, Adjust green, ...). `MO` and `LT` have a solid border, `TG` a dotted one and `DF` a dashed one. An `LT(layer, key)` shows the tap key on the first line and the layer name on the second.
- **Warning keys** (`QK_BOOT`, `QK_REBOOT`, `QK_CLEAR_EEPROM`): a 2 px border in a warning colour (clear EEPROM red, bootloader and reboot amber) plus diagonal stripes in the same colour.

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

### keyboard_api.py
Local HTTP API and the thread-safe gateway to the USB thread (see [Keyboard sleep/wake API](#keyboard-sleepwake-api)).

### key_labels.py
Short overlay labels for `QK_` keycodes (`BOOTLDR`, `REBOOT`, `EE CLR`, `DEBUG`, `MAKE`, `ESC~`) and the warning borders of dangerous keys: clear EEPROM has a red border, bootloader and reboot an orange one.

### layer_tap.py
Layer tracking for layer-tap keys (`LT(layer, kc)`). The overlay only sees the matrix, so a layer counts as held once the key has been down for the tapping term (220 ms) or as soon as another key is pressed while it is down. A quick tap (which sends the key) never changes the shown layer. Plain `MO(layer)` keys switch immediately as before.

### key_style.py
Decodes layer-switching keycodes (`MO`, `LT`, `TG`, `DF`) for the key styling above.

### habit_sounds.py
Classifies key presses (old pinky key / top row), applies the cooldown and plays the sounds (see [Habit Sounds](#habit-sounds-optional)).

### rgb_matrix_info.py / rgb_matrix_effects.json
Formatting of the RGB matrix effect line; `rgb_matrix_effects.json` only holds the maximum brightness (see [RGB Matrix Effect Line](#rgb-matrix-effect-line)).

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

### Testing the RGB effect formatting, key labels and the HTTP API
```bash
python3 -m unittest test_rgb_matrix_info test_key_labels test_keyboard_api test_effect_names test_habit_sounds test_layer_tap test_key_style
```

## License

See individual source files for license information.

## Credits

- QMK Firmware: https://qmk.fm/
- VIA: https://www.caniusevia.com/
