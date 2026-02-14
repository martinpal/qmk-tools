# Boblight Integration for QMK Overlay

The QMK keyboard overlay now supports boblight integration for ambient lighting feedback based on keyboard layer changes.

## Features

- **Layer-based colors**: LEDs change color to match the current keyboard layer
- **Selective LED control**: Configure which LEDs participate (e.g., only top edge LEDs)
- **Base layer passthrough**: Base layer (0) doesn't affect boblight, leaving it under boblight-X11 control
- **Automatic reconnection**: Handles boblightd restarts gracefully
- **Configurable priority**: Set boblight priority to override or coexist with other clients

## Requirements

1. `boblightd` daemon running (typically on localhost:19333)
2. Boblight configuration with your LED setup

## Usage

### Basic Usage

Enable boblight with default settings (all LEDs, localhost:19333):

```bash
sudo python3 keyboard_overlay_gui.py --boblight
```

### Controlling Specific LEDs

To control only specific LEDs (e.g., top edge LEDs at indices 0-9):

```bash
sudo python3 keyboard_overlay_gui.py --boblight --boblight-leds "0,1,2,3,4,5,6,7,8,9"
```

### Custom Host/Port

Connect to boblight on a different host or port:

```bash
sudo python3 keyboard_overlay_gui.py --boblight --boblight-host 192.168.1.100 --boblight-port 19444
```

### Setting Priority

Set a higher priority to ensure keyboard layer colors override other boblight clients:

```bash
sudo python3 keyboard_overlay_gui.py --boblight --boblight-priority 255
```

### Using with run_overlay_with_sudo.sh

Edit the script to add boblight arguments:

```bash
# In run_overlay_with_sudo.sh, modify the last line:
sudo -E python3 keyboard_overlay_gui.py --keyboard="${kbd}" --x="${pos_x}" --y="${pos_y}" \
    --boblight --boblight-leds "0,1,2,3,4,5,6,7,8,9"
```

## Command-Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--boblight` | disabled | Enable boblight integration |
| `--boblight-host` | localhost | Boblight server hostname |
| `--boblight-port` | 19333 | Boblight server port |
| `--boblight-priority` | 100 | Priority level (0-254, **LOWER = higher priority**, 255 = disabled) |
| `--boblight-leds` | all LEDs | Comma-separated LED indices (e.g., "0,1,2,3,4") |

## Behavior

### Layer Colors

Each keyboard layer has a designated color:

- **Layer 0 (Base)**: QMK overlay disconnects (allows boblight-X11 or other clients to control LEDs)
- **Layer 1 (Game)**: Cyan (#00FFFF)
- **Layer 2 (Lower)**: Red (#FF0000)
- **Layer 3 (Raise)**: Blue (#0000FF)
- **Layer 4 (Adjust)**: Green (#00FF00)
- **Layer 5 (Mouse)**: Orange (#FF8000)
- **Layer 6 (Extra)**: Magenta (#FF00FF)

**Note:** Boblight uses fully saturated colors for better LED visibility, which differ from the softer colors shown in the screen overlay.

### Connection Handling

- Connects to boblightd on startup
- If connection fails, continues without boblight (warning displayed)
- Automatically attempts to reconnect if connection is lost during operation
- No visual feedback loss if boblight is unavailable

## Troubleshooting

### Boblight not responding

1. Verify boblightd is running:
   ```bash
   ps aux | grep boblightd
   ```

2. Check boblight connection:
   ```bash
   telnet localhost 19333
   hello
   ```
   You should see `hello` response.

3. Check boblight configuration for LED names:
   ```bash
   # In telnet session:
   get lights
   ```

### Wrong LEDs lighting up

Use the boblight configuration to identify LED indices:
- LEDs are numbered starting from 0
- Use `--boblight-leds` to specify which ones to control

### Priority conflicts with boblight-X11

**IMPORTANT: Priority works backwards!** In boblight, **LOWER numbers = HIGHER priority**:
- Priority 0 = Highest priority (wins over everything)
- Priority 100 = QMK overlay default (beats boblight-X11)
- Priority 128 = boblight-X11 default
- Priority 254 = Lowest usable priority
- Priority 255 = DISABLED (client is completely ignored)

**Default behavior (priority 100):** The QMK overlay uses priority 100 by default, which BEATS boblight-X11's priority 128.

If you want boblight-X11 to win instead:
- Increase the QMK overlay priority: `--boblight-priority 200` (200 > 128, so boblight-X11 wins)

**How it works:**
- When on non-base layers, QMK overlay continuously refreshes at 50Hz to override boblight-X11
- When on base layer (0), QMK overlay stops refreshing, allowing boblight-X11 to show screen colors
- This gives you screen-following lighting on base layer, layer-specific colors on other layers

## Example: Top Edge Only

For a setup with 50 total LEDs where indices 0-12 are the top edge:

```bash
sudo python3 keyboard_overlay_gui.py \
    --boblight \
    --boblight-leds "0,1,2,3,4,5,6,7,8,9,10,11,12" \
    --boblight-priority 220
```

## Integration with boblight-X11

The integration is designed to coexist with boblight-X11:

1. **Base layer (0)**: boblight-X11 controls colors (screen capture mode)
2. **Other layers**: QMK overlay takes control with layer-specific colors
3. When returning to base layer, control returns to boblight-X11

This allows you to have ambient screen-following lighting during normal use, with layer-specific colors when using special keyboard layers.
